"""Start a local Valkey (with vector search), connect, and create the indexes.

This is the notebook-friendly replacement for the CDK/ElastiCache stack. Instead
of provisioning a VPC + node-based Valkey cluster, it runs the official
``valkey/valkey-bundle`` image locally with Docker. That image ships the
``search`` module, which provides the ``FT.*`` vector-search commands the cache
needs - the same commands the production ElastiCache track uses.

Why port 6380 by default: a native Valkey/Redis installed via Homebrew usually
already listens on 6379, and it does NOT have the search module. Publishing the
container on 6380 avoids that collision. Override in ``ValkeyCacheConfig`` if you
prefer another port.
"""

import shutil
import subprocess  # nosec B404 - subprocess used with fixed docker arg lists, no shell, no user input
import time

from cache_lib.config import (
    PREFIX_SEM_VEC,
    PREFIX_TRAJ_VEC,
    SEMCACHE_INDEX,
    TRAJ_INDEX,
    VECTOR_DIM,
    ValkeyCacheConfig,
)

_clients: dict = {}


# ---------------------------------------------------------------------------
# Docker lifecycle
# ---------------------------------------------------------------------------

def _docker() -> str:
    exe = shutil.which("docker")
    if not exe:
        raise RuntimeError(
            "docker not found on PATH. Install Docker (or colima) and start the "
            "daemon. The Valkey local track needs a container that provides the "
            "FT.* search module (valkey/valkey-bundle)."
        )
    return exe


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([_docker(), *args], capture_output=True, text=True, check=check)  # nosemgrep: dangerous-subprocess-use-audit  # nosec B603 B607 - fixed argument list, no shell, docker binary path resolved internally, no user input


def _container_running(name: str) -> bool:
    out = _run("ps", "--filter", f"name=^{name}$", "--format", "{{.Names}}", check=False).stdout
    return name in out.split()


def _container_exists(name: str) -> bool:
    out = _run("ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}", check=False).stdout
    return name in out.split()


def start_local_valkey(cfg: ValkeyCacheConfig, pull: bool = True) -> dict:
    """Start the Valkey container with vector search. Idempotent.

    Returns a status dict, e.g.
    ``{"started": True, "already_running": False, "port": 6380}``.
    """
    name = cfg.container_name

    if _container_running(name):
        return {"started": False, "already_running": True, "port": cfg.port,
                "container": name}

    # Remove a stopped container of the same name so `run` won't clash.
    if _container_exists(name):
        _run("rm", "-f", name, check=False)

    if pull:
        _run("pull", cfg.image, check=False)

    proc = _run(
        "run", "-d", "--name", name,
        "-p", f"{cfg.port}:6379",
        cfg.image,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"failed to start Valkey container: {proc.stderr.strip()}\n"
            "If Docker Desktop demands an org sign-in, start the daemon with "
            "colima instead: `colima start`."
        )

    # Wait for the search module to be ready.
    deadline = time.time() + 30
    last_err = ""
    while time.time() < deadline:
        try:
            client = _connect(cfg)
            if supports_ft_search(client):
                return {"started": True, "already_running": False,
                        "port": cfg.port, "container": name}
        except Exception as exc:  # noqa: BLE001 - retry until ready
            last_err = str(exc)
        time.sleep(1.5)  # nosemgrep: arbitrary-sleep - intentional wait for local container
    raise RuntimeError(f"Valkey did not become ready in time. Last error: {last_err}")


def stop_local_valkey(cfg: ValkeyCacheConfig, remove: bool = True) -> dict:
    """Stop (and by default remove) the Valkey container. Idempotent."""
    name = cfg.container_name
    if not _container_exists(name):
        return {"stopped": False, "reason": "not found", "container": name}
    _run("rm", "-f", name, check=False) if remove else _run("stop", name, check=False)
    _clients.pop((cfg.host, cfg.port), None)
    return {"stopped": True, "removed": remove, "container": name}


# ---------------------------------------------------------------------------
# Client + indexes
# ---------------------------------------------------------------------------

def _connect(cfg: ValkeyCacheConfig):
    import valkey
    return valkey.Valkey(host=cfg.host, port=cfg.port,
                         socket_timeout=5, socket_connect_timeout=5)


def get_client(cfg: ValkeyCacheConfig):
    """Lazy singleton Valkey client for this host/port."""
    key = (cfg.host, cfg.port)
    if key not in _clients:
        _clients[key] = _connect(cfg)
    return _clients[key]


def supports_ft_search(client) -> bool:
    """Probe with FT._LIST - reliable regardless of reported engine version."""
    try:
        client.execute_command("FT._LIST")
        return True
    except Exception:
        return False


def ensure_indexes(client) -> dict:
    """Create both HNSW COSINE indexes once. Idempotent.

    - idx:semcache   over semcache:vec:*   (level 1, response cache)
    - idx:trajcache  over trajcache:vec:*  (level 2, reasoning cache)
    """
    if not supports_ft_search(client):
        raise RuntimeError(
            "This Valkey has no FT.* search module. Use the valkey/valkey-bundle "
            "image (start_local_valkey handles that)."
        )
    from valkey.exceptions import ResponseError

    created = []
    # Level 1 - response cache (question embedding -> answer).
    try:
        client.execute_command(
            "FT.CREATE", SEMCACHE_INDEX, "ON", "HASH", "PREFIX", "1", PREFIX_SEM_VEC,
            "SCHEMA",
            "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", str(VECTOR_DIM), "DISTANCE_METRIC", "COSINE",
        )
        created.append(SEMCACHE_INDEX)
    except ResponseError as e:
        if "already exists" not in str(e).lower():
            raise
    # Level 2 - trajectory cache.
    try:
        client.execute_command(
            "FT.CREATE", TRAJ_INDEX, "ON", "HASH", "PREFIX", "1", PREFIX_TRAJ_VEC,
            "SCHEMA",
            "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", str(VECTOR_DIM), "DISTANCE_METRIC", "COSINE",
            "entry_id", "TAG",
        )
        created.append(TRAJ_INDEX)
    except ResponseError as e:
        if "already exists" not in str(e).lower():
            raise

    existing = [i.decode() if isinstance(i, bytes) else i
                for i in client.execute_command("FT._LIST")]
    return {"created": created, "indexes": existing}
