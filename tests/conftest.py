import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

# ── Stub env vars required by pydantic Settings before any app imports ────────
_ENV_DEFAULTS = {
    "DATABASE_URL": "postgresql://test:test@localhost/test",
    "JWKS_URL": "http://localhost/.well-known/jwks.json",
    "JWT_ISSUER": "http://localhost",
    "JWT_AUDIENCE": "hackonomics",
    "GROQ_API_KEY": "test-groq-key",
    "AI_SERVICE_INTERNAL_TOKEN": "test-internal-token",
}
for _k, _v in _ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

# ── Stub packages unavailable locally ─────────────────────────────────────────
# psycopg2: native PostgreSQL driver (not needed for unit tests)
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extensions", MagicMock())

# fastembed + onnxruntime: no wheel for this platform.
# Must register all sub-packages as real ModuleType objects so that
# `from fastembed.rerank.cross_encoder import TextCrossEncoder` resolves.
def _make_pkg(name: str) -> ModuleType:
    m = ModuleType(name)
    m.__path__ = []  # marks it as a package
    return m

_fastembed_pkg = _make_pkg("fastembed")
_fastembed_pkg.TextEmbedding = MagicMock()  # type: ignore
_fastembed_rerank = _make_pkg("fastembed.rerank")
_fastembed_ce = _make_pkg("fastembed.rerank.cross_encoder")
_fastembed_ce.TextCrossEncoder = MagicMock()  # type: ignore

sys.modules["fastembed"] = _fastembed_pkg
sys.modules["fastembed.rerank"] = _fastembed_rerank
sys.modules["fastembed.rerank.cross_encoder"] = _fastembed_ce

for _mod in [
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.models",
    "qdrant_client.models",
    # aiokafka: not installed in local dev venv (runs inside Docker in prod)
    "aiokafka",
]:
    sys.modules.setdefault(_mod, MagicMock())

# ── Stub SQLAlchemy engine creation (db.py creates engine at import time) ─────
_create_engine_patcher = patch("sqlalchemy.create_engine", return_value=MagicMock())
_create_engine_patcher.start()

# ── Make proto stubs importable as `from ai.v1 import ai_pb2` ─────────────────
# Matches PYTHONPATH=/app/app/gen set in Dockerfile.
_gen_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "gen"))
if _gen_path not in sys.path:
    sys.path.insert(0, _gen_path)

import pytest  # noqa: E402


@pytest.fixture
def mock_grpc_context():
    ctx = MagicMock()
    ctx.set_code = MagicMock()
    ctx.set_details = MagicMock()
    return ctx


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def sample_contexts():
    return [
        {"title": "Market Rally", "description": "Stocks rose 2%."},
        {"title": "Rate Cut", "description": "Fed cuts rates by 25bp."},
    ]
