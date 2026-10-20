"""The Vercel entry point restores the original path passed by the rewrite in vercel.json."""

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_rewrite_destination_passes_path():
    config = json.loads((Path(__file__).parent.parent / "vercel.json").read_text())
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index?__path=$1"}]


def test_entry_point_restores_path_and_query():
    from api.index import app

    with TestClient(app) as client:
        r = client.get("/api/index", params={"__path": "api/v1/health"})
        assert r.status_code == 200 and r.json()["database"] == "ok"
        # Other query parameters survive; the helper parameter is removed.
        r = client.get("/api/index", params={"__path": "api/v1/registrars", "kind": "domain"})
        assert r.status_code == 401  # reached the real route (needs login)
        r = client.get("/api/index", params={"__path": ""})
        assert r.json()["service"] == "Domain & Hosting Monitor API"
        # Direct paths (local / Docker) are untouched.
        assert client.get("/api/v1/health").status_code == 200
