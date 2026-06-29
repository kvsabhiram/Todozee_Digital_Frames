"""
CI smoke tests.

Importing ``app.main`` eagerly builds the singleton ``FrameProcessor`` —
which creates the rembg session and loads the YuNet ONNX face detector — so
just importing the app already validates that every ML dependency installs and
loads. On top of that we exercise the two read-only endpoints to confirm the
service boots and serves requests.

These intentionally do NOT call ``POST /process`` (no real photo / heavy
inference) — that keeps the gate fast and deterministic. The deploy job's own
post-restart health check covers the running service.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["port"] == 5016


def test_list_frames_returns_catalogue():
    resp = client.get("/frames")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 8
    ids = {f["id"] for f in data["frames"]}
    assert "diwali_01" in ids


def test_unknown_download_is_404():
    resp = client.get("/download/does_not_exist.jpg")
    assert resp.status_code == 404
