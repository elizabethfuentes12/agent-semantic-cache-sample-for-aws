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
    from cache_lib.config import (ValkeyCacheConfig, TOOL_TTL_SECONDS, VECTOR_DIM,
                                  NEGATIVE_TTL_SECONDS, SEMCACHE_INDEX, TRAJ_INDEX)
    cfg = ValkeyCacheConfig()
    ok &= check("default region us-east-1", cfg.region == "us-east-1")
    ok &= check("default port 6380", cfg.port == 6380)
    ok &= check("threshold 0.85", cfg.similarity_threshold == 0.85)
    ok &= check("VECTOR_DIM 1024", VECTOR_DIM == 1024)
    ok &= check("two distinct indexes", SEMCACHE_INDEX != TRAJ_INDEX)
    ok &= check("flights TTL is 5 min", TOOL_TTL_SECONDS["search_flights"] == 300)
    ok &= check("negative TTL is 5 min", NEGATIVE_TTL_SECONDS == 300)
    ok &= check("rewrite model is a cheap model", "lite" in cfg.rewrite_model_id.lower())
    ok &= check("rewrite_on_hit default True", cfg.rewrite_on_hit is True)

    print("cache_lib.embeddings")
    from cache_lib.embeddings import embedding_to_bytes, cosine_similarity
    ok &= check("embedding_to_bytes is FLOAT32 (4 bytes/elem)",
                len(embedding_to_bytes([0.5, -1.0, 2.0])) == 12)
    ok &= check("cosine identical == 1.0", abs(cosine_similarity([1, 2, 3], [1, 2, 3]) - 1.0) < 1e-9)
    ok &= check("cosine orthogonal == 0.0", abs(cosine_similarity([1, 0], [0, 1])) < 1e-9)
    ok &= check("cosine zero-vec safe", cosine_similarity([0, 0], [1, 1]) == 0.0)

    # cache_lib.caches must import. A failure here is OUR bug, not the env,
    # unless it is specifically the strands runtime missing.
    print("cache_lib.caches")
    try:
        from cache_lib.caches import (ResponseCache, ToolResultCache,
                                      ReasoningCache)
    except ImportError as exc:
        if "strands" in str(exc).lower():
            print(f"  SKIP  strands runtime not installed: {exc}")
            print("        (environment issue; the pure-python checks above still ran)")
            print("\nRESULT:", "PASSED (strands not installed)" if ok else "SOME CHECKS FAILED")
            return 0 if ok else 1
        raise   # any other ImportError is a real cache_lib bug -> fail loudly

    ok &= check("three separate hook classes",
                len({ResponseCache, ToolResultCache, ReasoningCache}) == 3)
    # TTL-refresh guard: ToolResultCache must track served toolUseIds so a hit
    # does not re-store (and refresh the TTL of) the cached result.
    import inspect
    trc_src = inspect.getsource(ToolResultCache)
    ok &= check("tool cache guards served hits (no TTL refresh)",
                "_served" in trc_src and "toolUseId" in trc_src)
    ok &= check("tool key canonicalizes case/space",
                ToolResultCache._tool_key("geocode_destination", {"place": "Tokyo"})
                == ToolResultCache._tool_key("geocode_destination", {"place": "  tokyo "}))
    ok &= check("critical params extract dates",
                "2026-09-15" in ResponseCache._critical_params("flights on 2026-09-15"))
    ok &= check("date mismatch detected",
                ResponseCache._critical_params("on 2026-09-15") != ResponseCache._critical_params("on 2026-12-15"))
    ok &= check("failure marker detected", not ToolResultCache._is_useful("No location found for 'Xyz'."))
    ok &= check("duffel no-key marked not useful", not ToolResultCache._is_useful("No Duffel API key. Set ..."))
    ok &= check("useful result passes", ToolResultCache._is_useful('{"name": "Tokyo"}'))

    print("cache_lib.agent")
    from cache_lib.agent import _clean_answer, SYSTEM_PROMPT, VERBATIM_SIMILARITY
    ok &= check("clean_answer strips thinking",
                _clean_answer("<thinking>x</thinking>Answer.") == "Answer.")
    ok &= check("system prompt asks for question's language",
                "same language" in SYSTEM_PROMPT.lower())
    ok &= check("verbatim threshold above main threshold",
                VERBATIM_SIMILARITY > cfg.similarity_threshold)

    print("cache_lib.rewrite")
    from cache_lib.rewrite import Localized, rewrite_to_question_language
    fields = set(Localized.model_fields)
    ok &= check("Localized has same_language + answer",
                {"same_language", "answer"} <= fields)
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
