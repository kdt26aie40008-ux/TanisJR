"""スマホから使う（Tailscale 経由）: 中継のオン・オフ、ペアリング、ペアリングしていない端末の遮断。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import ORIGIN, REMOTE_HOST, FakeTailscale

PHONE = f"https://{REMOTE_HOST}"


def phone(client: TestClient) -> TestClient:
    """同じアプリに、スマホ（Tailscale の名前・https）からつなぐ。"""
    c = TestClient(client.app, base_url=PHONE, headers={"Origin": PHONE})
    c.__enter__()
    return c


def enable(client: TestClient) -> None:
    res = client.post("/api/remote/enable")
    assert res.status_code == 200, res.text


def test_phone_is_rejected_until_remote_is_enabled(setup_done: TestClient) -> None:
    res = phone(setup_done).get("/api/settings")
    assert res.status_code == 400  # 知らない名前（Host 検証）


def test_enable_runs_tailscale_serve(setup_done: TestClient, fake_tailscale: FakeTailscale) -> None:
    enable(setup_done)
    assert ["serve", "--bg", "--https=443", "http://127.0.0.1:8765"] in fake_tailscale.commands
    body = setup_done.get("/api/remote/status").json()
    assert body["enabled"] and body["url"] == PHONE and body["tailscale"]["serving"]
    assert setup_done.post("/api/remote/disable").json()["tailscale"]["serving"] is False
    assert ["serve", "--https=443", "off"] in fake_tailscale.commands
    assert phone(setup_done).get("/api/health").status_code == 400


def test_enable_explains_what_is_missing(setup_done: TestClient, fake_tailscale: FakeTailscale) -> None:
    fake_tailscale.https = False
    res = setup_done.post("/api/remote/enable")
    assert res.status_code == 409 and "Enable HTTPS" in res.json()["detail"]["message"]
    fake_tailscale.logged_in = False
    assert setup_done.post("/api/remote/enable").json()["detail"]["code"] == "tailscale_logged_out"


def test_unpaired_phone_sees_only_the_screen(setup_done: TestClient) -> None:
    enable(setup_done)
    p = phone(setup_done)
    assert p.get("/api/health").status_code == 200
    assert p.get("/api/remote/me").json() == {"remote": True, "paired": False}
    for path in ("/api/settings", "/api/setup/status", "/api/conversations", "/api/calendar/events"):
        res = p.get(path)
        assert res.status_code == 401 and res.json()["detail"]["code"] == "pairing_required", path


def test_pairing_with_pin(setup_done: TestClient) -> None:
    enable(setup_done)
    pin = setup_done.post("/api/remote/pairing").json()["pin"]
    p = phone(setup_done)
    res = p.post("/api/remote/pair", json={"pin": pin, "name": "iPhone"})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    assert p.get("/api/settings").status_code == 200
    assert p.get("/api/remote/me").json() == {"remote": True, "paired": True}
    # 合言葉は1回だけ
    assert phone(setup_done).post("/api/remote/pair", json={"pin": pin, "name": "x"}).status_code == 403
    devices = setup_done.get("/api/remote/status").json()["devices"]
    assert [d["name"] for d in devices] == ["iPhone"] and "token_hash" not in devices[0]


def test_wrong_pin_locks_after_five_tries(setup_done: TestClient) -> None:
    enable(setup_done)
    pin = setup_done.post("/api/remote/pairing").json()["pin"]
    wrong = "000000" if pin != "000000" else "111111"
    p = phone(setup_done)
    codes = [p.post("/api/remote/pair", json={"pin": wrong}).json()["detail"]["code"] for _ in range(5)]
    assert codes == ["pin_wrong"] * 4 + ["pin_locked"]
    # 正しい合言葉でも、もう使えない
    assert p.post("/api/remote/pair", json={"pin": pin}).json()["detail"]["code"] == "pin_expired"


def test_phone_cannot_manage_the_pc(setup_done: TestClient) -> None:
    enable(setup_done)
    pin = setup_done.post("/api/remote/pairing").json()["pin"]
    p = phone(setup_done)
    p.post("/api/remote/pair", json={"pin": pin})
    for method, path in (("post", "/api/remote/pairing"), ("post", "/api/system/stop"), ("get", "/api/remote/status")):
        res = getattr(p, method)(path)
        assert res.status_code == 403 and res.json()["detail"]["code"] == "local_only", path


def test_removed_device_is_rejected(setup_done: TestClient) -> None:
    enable(setup_done)
    pin = setup_done.post("/api/remote/pairing").json()["pin"]
    p = phone(setup_done)
    p.post("/api/remote/pair", json={"pin": pin})
    device_id = setup_done.get("/api/remote/status").json()["devices"][0]["id"]
    assert setup_done.delete(f"/api/remote/devices/{device_id}").json() == {"deleted": True}
    assert p.get("/api/settings").status_code == 401


def test_pairing_must_come_from_the_phone(setup_done: TestClient) -> None:
    enable(setup_done)
    pin = setup_done.post("/api/remote/pairing").json()["pin"]
    assert setup_done.post("/api/remote/pair", json={"pin": pin}).json()["detail"]["code"] == "not_remote"


def test_remote_stays_on_after_restart(make_client: Callable[[], TestClient], fake_tailscale: FakeTailscale) -> None:
    first = make_client()
    first.post("/api/setup/complete", json={"consent": True, "answers": ["a", "b", "c"], "ai_name": "タニス"})
    enable(first)
    again = make_client()
    assert phone(again).get("/api/health").status_code == 200


def test_other_sites_cannot_post(setup_done: TestClient) -> None:
    enable(setup_done)
    res = TestClient(setup_done.app, headers={"Origin": "https://evil.example"}).post("/api/remote/pairing")
    assert res.status_code == 403
    assert ORIGIN  # PC 本体からは今までどおり
