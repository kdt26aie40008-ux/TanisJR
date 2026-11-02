from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import system


def test_status(setup_done: TestClient) -> None:
    data = setup_done.get("/api/system/status").json()
    assert data["autostart"] is False
    assert data["pid"] > 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows のショートカット作成")
def test_autostart_creates_and_removes_shortcut(setup_done: TestClient, tmp_path: Path) -> None:
    r = setup_done.put("/api/system/autostart", json={"enabled": True})
    assert r.json() == {"autostart": True}
    lnk = tmp_path / "startup" / system.SHORTCUT_NAME
    assert lnk.is_file()
    assert setup_done.put("/api/system/autostart", json={"enabled": False}).json() == {"autostart": False}
    assert not lnk.exists()


def test_process_control_is_disabled_in_tests(setup_done: TestClient) -> None:
    assert setup_done.post("/api/system/stop").status_code == 409
    assert setup_done.post("/api/system/restart").status_code == 409


def test_process_control_requires_same_origin(setup_done: TestClient) -> None:
    r = setup_done.post("/api/system/stop", headers={"Origin": "https://evil.example.com"})
    assert r.status_code == 403
