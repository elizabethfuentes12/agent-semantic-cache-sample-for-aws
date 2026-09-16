"""Offline smoke test for the pure-Python helpers (no AWS, no network).

Run: python3 smoke_test.py
Exit 0 = all checks passed. A cache_lib ImportError is a real failure; only a
missing strands runtime is tolerated (it is an environment issue, not our code).
"""
import sys


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    return bool(cond)


def main():
    ok = True

    print("cache_lib.config")
    from cache_lib.config import (CacheConfig, KIND_ANSWER, KIND_TRAJECTORY,
                                  KIND_TOOL, TOOL_TTL_SECONDS, VECTOR_DIM,
                                  NEGATIVE_TTL_SECONDS)
    cfg = CacheConfig()
    ok &= check("default region us-east-1", cfg.region == "us-east-1")
    ok &= check("default table name", cfg.table_name == "agent-cache-dynamodb-local")
    ok &= check("threshold 0.85", cfg.similarity_threshold == 0.85)
    ok &= check("VECTOR_DIM 1024", VECTOR_DIM == 1024)
    ok &= check("kinds distinct", len({KIND_ANSWER, KIND_TRAJECTORY, KIND_TOOL}) == 3)
    ok &= check("all_kinds has 3", len(cfg.all_kinds) == 3)
    ok &= check("flights TTL is 5 min", TOOL_TTL_SECONDS["search_flights"] == 300)
    ok &= check("negative TTL is 5 min", NEGATIVE_TTL_SECONDS == 300)
    ok &= check("rewrite model is a cheap model", "lite" in cfg.rewrite_model_id.lower())
    ok &= check("rewrite_on_hit default True", cfg.rewrite_on_hit is True)

    print("cache_lib.embeddings")
    from cache_lib.embeddings import to_ddb_vector, cosine_similarity
    ok &= check("to_ddb_vector shape",
                to_ddb_vector([0.5, -1.0]) == [{"N": "0.5"}, {"N": "-1.0"}])
    ok &= check("cosine identical == 1.0", abs(cosine_similarity([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9)
    ok &= check("cosine orthogonal == 0.0", abs(cosine_similarity([1, 0], [0, 1])) < 1e-9)
    ok &= check("cosine zero-vec safe", cosine_similarity([0, 0], [1, 1]) == 0.0)

    print("cache_lib.table (version guard, no AWS calls)")
    from cache_lib.table import assert_boto3_supports_vectors, MIN_BOTO3
    ok &= check("MIN_BOTO3 is 1.43.72", MIN_BOTO3 == (1, 43, 72))
    try:
        assert_boto3_supports_vectors()
        ok &= check("installed boto3 supports vectors", True)
    except RuntimeError as exc:
        print(f"  INFO  boto3 too old in this env: {exc}")

    # cache_lib.caches must import. A failure here is OUR bug, not the env,
    # unless it is specifically the strands runtime missing.
    print("cache_lib.caches")
    try:
        from cache_lib.caches import ResponseCache, ToolResultCache
        # helpers are now @staticmethod on the hook classes (harness-native
        # style, mirroring notebook 01); bind them to local names for the checks
        _tool_key = ToolResultCache._tool_key
        _is_useful = ToolResultCache._is_useful
        _critical_params = ResponseCache._critical_params
        _question_of = ResponseCache._question_of
    except ImportError as exc:
        if "strands" in str(exc).lower():
            print(f"  SKIP  strands runtime not installed: {exc}")
            print("        (environment issue; the pure-python checks above still ran)")
            print("\nRESULT:", "PASSED (strands not installed)" if ok else "SOME CHECKS FAILED")
            return 0 if ok else 1
        raise   # any other ImportError is a real cache_lib bug -> fail loudly

    ok &= check("tool key canonicalizes case/space",
                _tool_key("geocode_destination", {"place": "Tokyo"})
                == _tool_key("geocode_destination", {"place": "  tokyo "}))
    # TTL-refresh guard: ToolResultCache must track served toolUseIds so a hit
    # does not re-store (and refresh the TTL of) the cached result.
    import inspect
    trc_src = inspect.getsource(ToolResultCache)
    ok &= check("tool cache guards served hits (no TTL refresh)",
                "_served" in trc_src and "toolUseId" in trc_src)
    ok &= check("critical params extract dates",
                "2026-09-15" in _critical_params("flights on 2026-09-15"))
    ok &= check("date mismatch detected",
                _critical_params("on 2026-09-15") != _critical_params("on 2026-12-15"))
    ok &= check("failure marker detected", not _is_useful("No location found for 'Xyz'."))
    ok &= check("duffel no-key marked not useful", not _is_useful("No Duffel API key. Set ..."))
    ok &= check("useful result passes", _is_useful('{"name": "Tokyo"}'))

    print("cache_lib.agent")
    from cache_lib.agent import (CachedTravelAgent, _clean_answer, SYSTEM_PROMPT,
                                 VERBATIM_SIMILARITY)
    ok &= check("clean_answer strips thinking",
                _clean_answer("<thinking>x</thinking>Answer.") == "Answer.")
    ok &= check("system prompt asks for question's language",
                "same language" in SYSTEM_PROMPT.lower())
    ok &= check("verbatim threshold above main threshold",
                VERBATIM_SIMILARITY > cfg.similarity_threshold)
    # The rewrite must be gated on the language, not on similarity alone: a
    # same-language paraphrase costs more in rewrite tokens than the hit saves.
    ok &= check("both hit and miss paths gate the rewrite on language_differs",
                inspect.getsource(CachedTravelAgent.ask).count("language_differs(") == 2)

    print("cache_lib.rewrite")
    from cache_lib.rewrite import (Localized, language_differs,
                                   rewrite_to_question_language)
    fields = set(Localized.model_fields)
    ok &= check("Localized has same_language + answer",
                {"same_language", "answer"} <= fields)
    # The gate runs BEFORE the model call, so it has to be right offline.
    _en_answer = ("The best time to visit is spring, and most visitors do not "
                  "need a visa for a short stay.")
    ok &= check("same-language paraphrase needs no rewrite",
                language_differs("When should I travel to Japan, and is a visa "
                                 "required?", _en_answer) is False)
    ok &= check("spanish question on an english answer needs a rewrite",
                language_differs("Cuando es mejor viajar a Japon y necesito "
                                 "visa?", _en_answer) is True)
    # Fail-open, verified offline: force the model construction to raise (no
    # network) and confirm the cached answer is returned unchanged.
    import strands.models as _sm
    _orig = _sm.BedrockModel
    _sm.BedrockModel = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))
    try:
        out = rewrite_to_question_language("q", "cached answer",
                                           "any.model", "us-east-1")
    finally:
        _sm.BedrockModel = _orig
    ok &= check("rewrite fails open to original", out["answer"] == "cached answer")
    ok &= check("rewrite fail marks not rewritten", out["rewritten"] is False)

    print("\nRESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
