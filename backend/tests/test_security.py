from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, validate_local_url
from tests.conftest import VALID_SETUP


def test_rejects_foreign_host_header(client: TestClient) -> None:
    # DNS リバインディング攻撃では Host が攻撃者のドメインになる
    response = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert response.status_code == 400


def test_rejects_cross_origin_post(client: TestClient) -> None:
    response = client.post("/api/setup/complete", json=VALID_SETUP, headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 403
    assert client.get("/api/setup/status").json() == {"completed": False}


def test_security_headers(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    # 外部への接続は許可しない（blob: はページ内データのみ）
    assert "connect-src 'self' blob:;" in csp + ";"


@pytest.mark.parametrize("url", ["http://example.com:11434", "http://192.168.1.10:11434", "file:///etc/passwd"])
def test_ollama_url_must_be_local(url: str) -> None:
    with pytest.raises(ConfigError):
        validate_local_url(url)


def test_ollama_url_local_ok() -> None:
    assert validate_local_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"


def test_static_path_traversal(client: TestClient, config) -> None:  # noqa: ANN001
    dist = config.frontend_dist
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    secret = config.data_dir / "secret.txt"
    secret.write_text("SECRET", encoding="utf-8")
    for path in ["/../data/secret.txt", "/%2e%2e/data/secret.txt", "/..%5cdata%5csecret.txt"]:
        response = client.get(path)
        assert "SECRET" not in response.text, path
    assert client.get("/some/route").text == "<html>app</html>"


def test_unknown_api_path_is_json_404(client: TestClient) -> None:
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"
