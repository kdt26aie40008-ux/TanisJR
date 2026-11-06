"""アプリに同梱した OAuth クライアントで、「Google でログイン」だけで連携できること。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from tests.conftest import FakeGoogle

BUNDLED = {"installed": {"client_id": "999-team.apps.googleusercontent.com", "client_secret": "GOCSPX-team", "redirect_uris": ["http://localhost"]}}
OWN = {"installed": {"client_id": "123-own.apps.googleusercontent.com", "client_secret": "GOCSPX-own", "redirect_uris": ["http://localhost"]}}


@pytest.fixture
def bundled_file(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "google-oauth-client.json"
    path.parent.mkdir()
    path.write_text(json.dumps(BUNDLED), encoding="utf-8")
    return path


@pytest.fixture
def config(config: Config, bundled_file: Path) -> Config:  # conftest の config を上書きする
    return dataclasses.replace(config, google_client_file=bundled_file)


@pytest.fixture(autouse=True)
def google_backend(client: TestClient) -> None:
    assert client.put("/api/settings", json={"calendar_backend": "google"}).status_code == 200


def client_id_in(url: str) -> str:
    return parse_qs(urlparse(url).query)["client_id"][0]


def test_login_only_with_bundled_client(setup_done: TestClient, fake_google: FakeGoogle) -> None:
    status = setup_done.get("/api/calendar/status").json()
    assert (status["configured"], status["source"], status["connected"]) == (True, "bundled", False)

    # JSON を登録しなくても、すぐにログインを始められる
    url = setup_done.post("/api/calendar/auth/start").json()["url"]
    assert client_id_in(url) == BUNDLED["installed"]["client_id"]
    state = parse_qs(urlparse(url).query)["state"][0]
    page = setup_done.get("/api/calendar/auth/callback", params={"state": state, "code": "auth-code"})
    assert "連携しました" in page.text
    assert setup_done.get("/api/calendar/status").json()["connected"] is True


def test_own_client_takes_priority_and_falls_back(setup_done: TestClient) -> None:
    setup_done.post("/api/calendar/client", content=json.dumps(OWN))
    assert setup_done.get("/api/calendar/status").json()["source"] == "own"
    assert client_id_in(setup_done.post("/api/calendar/auth/start").json()["url"]) == OWN["installed"]["client_id"]
    # 自分の登録を消すと、同梱のものに戻る
    setup_done.delete("/api/calendar/client")
    assert setup_done.get("/api/calendar/status").json()["source"] == "bundled"


def test_broken_bundled_file_is_ignored(setup_done: TestClient, bundled_file: Path) -> None:
    bundled_file.write_text('{"web": {"client_id": "x"}}', encoding="utf-8")
    status = setup_done.get("/api/calendar/status").json()
    assert (status["configured"], status["source"]) == (False, None)
