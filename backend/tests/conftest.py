from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app

ORIGIN = "http://127.0.0.1:8765"

# 埋め込みの代わりに、キーワードの出現で決まるベクトルを使う（同じ語を含む文は近くなる）
VOCAB = ["ラーメン", "麺", "猫", "犬", "雨", "ゲーム", "数学", "山田", "東京", "コーヒー"]


def fake_embedding(text: str) -> list[float]:
    vec = [float(text.count(w)) for w in VOCAB] + [0.05]
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


class FakeOllama:
    """Ollama API の代わりに応答する。テストごとに handler を差し替える。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.chat_handler: Callable[[dict], httpx.Response] = lambda body: ndjson(
            [{"message": {"role": "assistant", "content": "こんにちは"}, "done": False}, {"done": True}]
        )
        # 記憶抽出（format 指定の非ストリーミング呼び出し）の結果
        self.extraction: list[dict] = []
        self.extraction_raw: str | None = None
        self.format_queue: list[dict] = []
        self.embed_available = True
        self.models = [{"name": "qwen3:8b", "size": 5_200_000_000}, {"name": "qwen3-embedding:0.6b", "size": 639_000_000}]

    def paths(self, path: str) -> list[dict]:
        return [r["body"] for r in self.requests if r["path"] == path]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else {}
            self.requests.append({"path": request.url.path, "body": body})
            if request.url.path == "/api/version":
                return httpx.Response(200, json={"version": "test"})
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": self.models})
            if request.url.path == "/api/embed":
                if not self.embed_available:
                    return httpx.Response(404, json={"error": f"model '{body['model']}' not found"})
                return httpx.Response(200, json={"embeddings": [fake_embedding(t) for t in body["input"]]})
            if request.url.path == "/api/ps":
                return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
            if request.url.path == "/api/generate":
                return httpx.Response(200, json={"done": True})
            if request.url.path == "/api/delete":
                return httpx.Response(200)
            if request.url.path == "/api/chat":
                if "format" not in body and body.get("stream") is False:
                    # 蒸留など、形式指定のない非ストリーミング呼び出し
                    return httpx.Response(200, json={"message": {"role": "assistant", "content": "教師の回答です"}, "done": True})
                if "format" in body and self.format_queue:
                    # 形式指定の呼び出しへの応答を、呼ばれた順に返す（予定の下書き・返事の分類など）
                    content = json.dumps(self.format_queue.pop(0), ensure_ascii=False)
                    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "done": True})
                if "format" in body:
                    content = self.extraction_raw if self.extraction_raw is not None else json.dumps(
                        {"memories": self.extraction}, ensure_ascii=False
                    )
                    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "done": True})
                return self.chat_handler(body)
            if request.url.path == "/api/pull":
                return ndjson([{"status": "pulling", "completed": 1, "total": 2}, {"status": "success"}])
            return httpx.Response(404, json={"error": "not found"})

        return httpx.MockTransport(handle)


WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt "  # 合成音声の代わり（中身は検証しない）
SPEAKER_UUID = "e756b8e4-b606-4e15-99b1-3f9c6a1b2317"


class FakeAivis:
    """AivisSpeech Engine（VOICEVOX 互換 API）の代わり。"""

    def __init__(self) -> None:
        self.available = True
        self.requests: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            if not self.available:
                raise httpx.ConnectError("refused")
            self.requests.append({"path": request.url.path, "params": dict(request.url.params)})
            if request.url.path == "/speakers":
                return httpx.Response(
                    200,
                    json=[{"name": "テスト話者", "speaker_uuid": SPEAKER_UUID, "styles": [{"id": 888753760, "name": "ノーマル"}]}],
                )
            if request.url.path == "/speaker_info":
                return httpx.Response(200, json={"policy": "# 利用規約\nクレジット表記が必要です。", "portrait": "BASE64"})
            if request.url.path == "/audio_query":
                return httpx.Response(200, json={"accent_phrases": [], "speedScale": 1.0})
            if request.url.path == "/synthesis":
                return httpx.Response(200, content=WAV_BYTES, headers={"content-type": "audio/wav"})
            return httpx.Response(404, json={"detail": "not found"})

        return httpx.MockTransport(handle)


class FakeTranscriber:
    """faster-whisper の代わり。受け取った音声は保持しない（呼び出し回数だけ記録）。"""

    def __init__(self) -> None:
        self.text = "こんにちは"
        self.calls: list[tuple[int, str, str]] = []
        self.options: list[tuple[str, bool]] = []
        self.error: Exception | None = None
        self.downloads: list[str] = []

    def status(self) -> dict:
        return {"models": [], "models_dir": "x", "loaded": None, "download": None}

    async def transcribe(  # noqa: ANN201
        self, audio: bytes, model: str, device: str, language: str = "ja", fast: bool = False, hotwords: str | None = None
    ):
        from app.speech.stt import Transcript

        self.hotwords = hotwords
        self.calls.append((len(audio), model, device))
        self.options.append((language, fast))
        if self.error:
            raise self.error
        return Transcript(text=self.text, duration=1.0, elapsed=0.1, device=device)

    def start_download(self, model: str) -> None:
        self.downloads.append(model)

    async def warmup(self, model: str, device: str) -> bool:
        self.warmed = (model, device)
        return True


class FakeGoogle:
    """Google OAuth / Calendar API の代わり。予定はメモリ上で管理する。"""

    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.token_error: str | None = None
        self.api_status: int | None = None
        self.next_id = 1

    def add_event(self, summary: str, start: str, end: str, **extra: object) -> str:
        event_id = f"ev{self.next_id}"
        self.next_id += 1
        self.events[event_id] = {
            "id": event_id, "summary": summary, "status": "confirmed",
            "start": {"dateTime": start}, "end": {"dateTime": end}, **extra,
        }
        return event_id

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            body = request.content.decode() if request.content else ""
            self.requests.append({"method": request.method, "url": str(request.url), "body": body})
            host, path = request.url.host, request.url.path
            if host == "oauth2.googleapis.com" and path == "/token":
                if self.token_error:
                    return httpx.Response(400, json={"error": self.token_error})
                form = dict(x.split("=", 1) for x in body.split("&"))
                data = {"access_token": f"access-{len(self.requests)}", "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/calendar.events", "token_type": "Bearer"}
                if form.get("grant_type") == "authorization_code":
                    data["refresh_token"] = "refresh-1"
                return httpx.Response(200, json=data)
            if host == "oauth2.googleapis.com" and path == "/revoke":
                return httpx.Response(200)
            if host == "www.googleapis.com" and path.startswith("/calendar/v3/calendars/primary/events"):
                if self.api_status:
                    return httpx.Response(self.api_status, json={"error": {"message": "x"}})
                event_id = path.rsplit("/", 1)[-1] if path.count("/") > 5 else None
                if request.method == "GET" and event_id is None:
                    items = sorted(self.events.values(), key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
                    return httpx.Response(200, json={"items": items})
                if request.method == "POST":
                    new = json.loads(body)
                    new["id"] = f"ev{self.next_id}"
                    self.next_id += 1
                    self.events[new["id"]] = new
                    return httpx.Response(200, json=new)
                if event_id not in self.events:
                    return httpx.Response(404, json={"error": {"message": "Not Found"}})
                if request.method == "GET":
                    return httpx.Response(200, json=self.events[event_id])
                if request.method == "PATCH":
                    self.events[event_id].update(json.loads(body))
                    return httpx.Response(200, json=self.events[event_id])
                if request.method == "DELETE":
                    del self.events[event_id]
                    return httpx.Response(204)
            return httpx.Response(404)

        return httpx.MockTransport(handle)


class FakeNotifier:
    def __init__(self) -> None:
        self.shown: list[tuple[str, str]] = []

    async def notify(self, title: str, body: str) -> bool:
        self.shown.append((title, body))
        return True


class FakeProtector:
    """DPAPI の代わり（鍵ファイルの形式だけ変える）。DPAPI 自体は test_crypto.py で検証する。"""

    def protect(self, data: bytes) -> bytes:
        return b"P" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        if not data.startswith(b"P"):
            from app.crypto import CryptoError

            raise CryptoError("bad")
        return data[1:][::-1]


def ndjson(chunks: list[dict], status: int = 200) -> httpx.Response:
    return httpx.Response(status, content="\n".join(json.dumps(c, ensure_ascii=False) for c in chunks).encode())


def sse_events(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def fake_ollama() -> FakeOllama:
    return FakeOllama()


@pytest.fixture
def fake_aivis() -> FakeAivis:
    return FakeAivis()


@pytest.fixture
def fake_stt() -> FakeTranscriber:
    return FakeTranscriber()


@pytest.fixture
def fake_google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def fake_notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        data_dir=tmp_path / "data",
        ollama_url="http://127.0.0.1:11434",
        port=8765,
        frontend_dist=tmp_path / "dist",
        models_dir=tmp_path / "models",
        allowed_hosts=("127.0.0.1", "localhost", "testserver"),
        allowed_origins=(ORIGIN,),
    )


@pytest.fixture
def make_client(
    config: Config,
    tmp_path: Path,
    fake_ollama: FakeOllama,
    fake_aivis: FakeAivis,
    fake_stt: FakeTranscriber,
    fake_google: FakeGoogle,
    fake_notifier: FakeNotifier,
) -> Iterator[Callable[[], TestClient]]:
    """同じデータフォルダーでアプリを起動し直せるようにする。"""
    clients: list[TestClient] = []

    def make() -> TestClient:
        app = create_app(
            config,
            ollama_transport=fake_ollama.transport(),
            protector=FakeProtector(),
            aivis_transport=fake_aivis.transport(),
            transcriber=fake_stt,
            google_transport=fake_google.transport(),
            notifier=fake_notifier,
            startup_dir=tmp_path / "startup",
            start_scheduler=False,
            allow_process_control=False,
            # 実際の AivisSpeech を起動しないよう、存在しないパスを渡す
            aivis_engine_path=tmp_path / "no-aivis" / "run.exe",
        )
        c = TestClient(app, headers={"Origin": ORIGIN})
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[[], TestClient]) -> TestClient:
    return make_client()


VALID_SETUP = {
    "consent": True,
    "answers": ["山田太郎。エンジニアです。", "好奇心が強い。嘘が嫌い。", "タニスにして"],
    "ai_name": "タニス",
}


@pytest.fixture
def setup_done(client: TestClient) -> TestClient:
    response = client.post("/api/setup/complete", json=VALID_SETUP)
    assert response.status_code == 200, response.text
    return client
