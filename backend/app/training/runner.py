"""学習の実行管理（必ず手動・実行前に確認）。

流れ: 確認 → 学習前バックアップ（データの暗号化スナップショット）→ Ollama の GPU メモリ解放
      → 別 venv の学習プロセス → 進捗の監視 → GGUF 変換 → Ollama に登録 → 平文の一時ファイルを削除
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config import REPO_ROOT
from app.crypto import Vault
from app.db import Database, now_iso
from app.llm.ollama import OllamaClient, OllamaError
from app.repositories.settings import SettingsRepository
from app.training.data import TrainingDataRepository

logger = logging.getLogger(__name__)

TRAINING_DIR = REPO_ROOT / "training"
TRAINING_PYTHON = TRAINING_DIR / ".venv" / "Scripts" / ("python.exe" if sys.platform == "win32" else "python")
TRAIN_SCRIPT = TRAINING_DIR / "train_lora.py"
CONVERT_SCRIPT = TRAINING_DIR / "llama.cpp" / "convert_hf_to_gguf.py"
# Ollama に登録するときの量子化（8GB VRAM で会話に使える大きさにする）
QUANTIZATION = "q4_K_M"
MIN_EXAMPLES = 5

# 学習後の比較に使う、個人情報を含まない固定の質問
EVAL_PROMPTS = ["自己紹介をしてください。", "今日は少し疲れたよ。", "休日の過ごし方について何か提案して。"]


@dataclass(frozen=True)
class BaseModelInfo:
    id: str
    label: str
    hf_dir: str  # models/hf 以下のフォルダー名
    hf_repo: str
    ollama_model: str
    quantize_4bit: bool
    size_gb: float
    note: str


BASE_MODELS: tuple[BaseModelInfo, ...] = (
    BaseModelInfo("qwen3-1.7b", "Qwen3 1.7B（検証向け・LoRA）", "Qwen3-1.7B", "Qwen/Qwen3-1.7B", "qwen3:1.7b", False, 4.1,
                  "RTX 5060 8GB で余裕を持って学習できます。"),
    BaseModelInfo("qwen3-8b", "Qwen3 8B（会話用と同じ・QLoRA）", "Qwen3-8B", "Qwen/Qwen3-8B", "qwen3:8b", True, 16.4,
                  "8GB の GPU ではメモリが不足する可能性があります（未検証）。"),
)


def find_base(base_id: str) -> BaseModelInfo | None:
    return next((b for b in BASE_MODELS if b.id == base_id), None)


class TrainingError(Exception):
    def __init__(self, message: str, code: str = "training_error", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class TrainingParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: str = Field(pattern=r"^[a-z0-9.\-]+$")
    # 少ないデータで同じ言い回しを繰り返す過学習を避けるため、控えめな既定値にする（実機検証で 3/2e-4 は崩れた）
    epochs: int = Field(default=2, ge=1, le=10)
    learning_rate: float = Field(default=1e-4, gt=0, le=1e-2)
    lora_r: int = Field(default=16, ge=4, le=64)
    lora_alpha: int = Field(default=32, ge=4, le=128)
    max_seq_len: int = Field(default=1024, ge=256, le=4096)
    grad_accum: int = Field(default=4, ge=1, le=32)
    # 実行前の確認画面で同意したことを示す
    confirmed: bool


class TrainingRun(BaseModel):
    id: str
    base: str
    status: str  # running | succeeded | failed | cancelled
    example_count: int
    params: dict[str, Any]
    metrics: dict[str, Any] | None
    error: str | None
    ollama_model: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    progress: dict[str, Any] | None = None
    active: bool = False


class TrainingManager:
    def __init__(
        self,
        db: Database,
        vault: Vault,
        settings: SettingsRepository,
        data: TrainingDataRepository,
        ollama: OllamaClient,
        runs_dir: Path,
        models_dir: Path,
    ) -> None:
        self.db = db
        self.vault = vault
        self.settings = settings
        self.data = data
        self.ollama = ollama
        self.runs_dir = runs_dir
        self.models_dir = models_dir
        self._process: subprocess.Popen | None = None
        self._current: str | None = None
        self._monitor: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        """学習中は GPU を学習専用にするため、会話・埋め込みなど Ollama を使う処理を止める。"""
        return self._current is not None

    # ---------- 環境の確認 ----------

    def environment(self) -> dict[str, Any]:
        return {
            "training_python": TRAINING_PYTHON.exists(),
            "converter": CONVERT_SCRIPT.exists(),
            "bases": [
                {**asdict(b), "downloaded": (self.models_dir / "hf" / b.hf_dir / "config.json").exists()} for b in BASE_MODELS
            ],
            "min_examples": MIN_EXAMPLES,
            "approved_examples": self.data.counts()["approved"],
            "running": self._current,
        }

    # ---------- 実行 ----------

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_dir / uuid.UUID(hex=run_id).hex

    async def _free_gpu(self) -> None:
        """Ollama が読み込んでいるモデルを解放して、学習に GPU メモリを使えるようにする。"""
        try:
            for model in await self.ollama.loaded_models():
                await self.ollama.unload(model)
        except OllamaError as exc:
            logger.warning("Could not unload Ollama models: %s", exc.code)

    async def start(self, params: TrainingParams, system_prompt: str) -> TrainingRun:
        if not params.confirmed:
            raise TrainingError("学習の内容を確認し、同意してから開始してください。", "confirmation_required")
        if self._current:
            raise TrainingError("別の学習を実行中です。", "training_running", 409)
        base = find_base(params.base)
        if base is None:
            raise TrainingError("指定されたベースモデルは対応していません。")
        base_path = self.models_dir / "hf" / base.hf_dir
        if not (base_path / "config.json").exists():
            raise TrainingError(f"学習用のモデル（{base.hf_repo}）がダウンロードされていません。", "base_missing", 409)
        if not TRAINING_PYTHON.exists():
            raise TrainingError("学習用の環境（training/.venv）がありません。README の手順で導入してください。", "env_missing", 409)
        pairs = self.data.approved_pairs()
        if len(pairs) < MIN_EXAMPLES:
            raise TrainingError(f"承認済みの学習データが{MIN_EXAMPLES}件以上必要です（現在 {len(pairs)} 件）。", "not_enough_data")

        run_id = uuid.uuid4().hex
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        jsonl = self.data.export_jsonl(system_prompt)
        # 学習前バックアップ: 使ったデータを暗号化して保存（どのデータで学習したか後から確認・再現できる）
        (run_dir / "dataset.enc").write_text(self.vault.encrypt(jsonl), encoding="ascii")
        # 学習プロセス用の平文ファイル（終了時に必ず削除する）
        (run_dir / "train.jsonl").write_text(jsonl, encoding="utf-8")
        config = {
            **params.model_dump(exclude={"confirmed"}),
            "base_path": str(base_path),
            "quantize_4bit": base.quantize_4bit,
            "system_prompt": system_prompt,
            "eval_prompts": EVAL_PROMPTS,
            "seed": 42,
        }
        (run_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO training_runs (id, base, status, example_count, params, created_at, started_at) VALUES (?, ?, 'running', ?, ?, ?, ?)",
                (run_id, base.id, len(pairs), json.dumps(params.model_dump(exclude={"confirmed"})), ts, ts),
            )
        await self._free_gpu()
        log = open(run_dir / "train.log", "w", encoding="utf-8")  # noqa: SIM115  プロセス終了まで書き込む
        self._process = subprocess.Popen(  # noqa: S603  固定のスクリプトを専用 venv で実行する
            [str(TRAINING_PYTHON), str(TRAIN_SCRIPT), "--run-dir", str(run_dir)],
            cwd=str(TRAINING_DIR),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**_clean_env(), "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"},
        )
        self._current = run_id
        self._monitor = asyncio.create_task(self._watch(run_id, log))
        run = self.get(run_id)
        assert run is not None
        return run

    async def _watch(self, run_id: str, log: Any) -> None:
        process = self._process
        assert process is not None
        try:
            while process.poll() is None:
                await asyncio.sleep(2)
            log.flush()
            await self._finalize(run_id, process.returncode)
        finally:
            log.close()
            self._process = None
            self._current = None

    async def _finalize(self, run_id: str, returncode: int) -> None:
        run_dir = self._run_dir(run_id)
        status = self._read_status(run_dir) or {}
        current = self.get(run_id)
        if current is not None and current.status == "cancelled":
            self._scrub(run_dir)
            return
        if returncode != 0 or status.get("state") != "succeeded":
            self._finish(run_id, "failed", error=status.get("error") or "学習プロセスが異常終了しました。ログを確認してください。")
            self._scrub(run_dir)
            return
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        try:
            name = await asyncio.to_thread(self._register_with_ollama, run_id, run_dir)
        except TrainingError as exc:
            self._finish(run_id, "failed", error=exc.message, metrics=metrics)
            self._scrub(run_dir)
            return
        self._finish(run_id, "succeeded", metrics=metrics, ollama_model=name)
        self._scrub(run_dir)

    @staticmethod
    def _run_logged(args: list[str], cwd: Path, run_dir: Path, label: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(  # noqa: S603  固定のツールを固定の引数で実行する
            args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=env,
        )
        with open(run_dir / "train.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- {label} (exit {result.returncode}) ---\n" + result.stdout[-3000:] + result.stderr[-3000:])
        return result

    def _register_with_ollama(self, run_id: str, run_dir: Path) -> str:
        """統合済みモデルを Ollama に登録する。

        Ollama は LoRA アダプター単体にも、GGUF の登録時量子化にも対応していないため（0.40 で確認）、
        1. 統合済みモデル（safetensors）をそのまま読み込ませ、登録時に q4_K_M へ量子化する
        2. それが失敗した場合は、llama.cpp で q8_0 の GGUF に変換して登録する
        会話の書式（テンプレート）とパラメーターは元の Ollama モデルから引き継ぐ。
        """
        run = self.get(run_id)
        base = find_base(run.base) if run else None
        if base is None:
            raise TrainingError("ベースモデルが見つかりません。")
        merged = run_dir / "merged"
        gguf = run_dir / "model-q8_0.gguf"
        name = f"twin-{base.id}-{run_id[:8]}"
        try:
            shown = self._run_logged(["ollama", "show", base.ollama_model, "--modelfile"], run_dir, run_dir, "ollama show")
            if shown.returncode != 0:
                raise TrainingError(f"元モデル「{base.ollama_model}」が Ollama に導入されていません。", "ollama_base_missing")
            # FROM だけを差し替え、テンプレート・停止語・パラメーターは元モデルのものを使う
            (run_dir / "Modelfile").write_text(replace_from(shown.stdout, "./merged"), encoding="utf-8")
            result = self._run_logged(
                ["ollama", "create", name, "-q", QUANTIZATION, "-f", "Modelfile"], run_dir, run_dir, "ollama create (safetensors)"
            )
            if result.returncode == 0:
                return name
            if not CONVERT_SCRIPT.exists():
                raise TrainingError("Ollama への登録に失敗しました。ログを確認してください。", "ollama_create_failed")
            result = self._run_logged(
                [str(TRAINING_PYTHON), str(CONVERT_SCRIPT), str(merged), "--outfile", str(gguf), "--outtype", "q8_0"],
                CONVERT_SCRIPT.parent, run_dir, "convert_hf_to_gguf (q8_0)", _clean_env(),
            )
            if result.returncode != 0 or not gguf.exists():
                raise TrainingError("学習結果を GGUF に変換できませんでした。ログを確認してください。", "convert_failed")
            (run_dir / "Modelfile").write_text(replace_from(shown.stdout, f"./{gguf.name}"), encoding="utf-8")
            result = self._run_logged(["ollama", "create", name, "-f", "Modelfile"], run_dir, run_dir, "ollama create (gguf)")
            if result.returncode != 0:
                raise TrainingError("Ollama への登録に失敗しました。ログを確認してください。", "ollama_create_failed")
            return name
        finally:
            # 大きな中間ファイル（統合モデル・GGUF）は登録後に削除する。LoRA アダプター（数十MB）は残す
            shutil.rmtree(merged, ignore_errors=True)
            gguf.unlink(missing_ok=True)

    def _scrub(self, run_dir: Path) -> None:
        """平文の個人データを残さない: 学習データ・設定内のプロフィール・評価の回答例を削除する。"""
        (run_dir / "train.jsonl").unlink(missing_ok=True)
        config = run_dir / "config.json"
        if config.exists():
            data = json.loads(config.read_text(encoding="utf-8"))
            data.pop("system_prompt", None)
            config.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (run_dir / "metrics.json").unlink(missing_ok=True)  # 評価結果は暗号化して DB に保存済み

    def _finish(
        self, run_id: str, status: str, error: str | None = None, metrics: dict | None = None, ollama_model: str | None = None
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE training_runs SET status = ?, error = ?, metrics = ?, ollama_model = ?, finished_at = ? WHERE id = ?",
                (status, error, self.vault.encrypt(json.dumps(metrics, ensure_ascii=False)) if metrics else None,
                 ollama_model, now_iso(), run_id),
            )

    def cancel(self, run_id: str) -> TrainingRun:
        if self._current != run_id or self._process is None:
            raise TrainingError("この学習は実行中ではありません。", "not_running", 409)
        with self.db.transaction() as conn:
            conn.execute("UPDATE training_runs SET status = 'cancelled', finished_at = ? WHERE id = ?", (now_iso(), run_id))
        self._process.terminate()
        run = self.get(run_id)
        assert run is not None
        return run

    def recover_interrupted(self) -> None:
        """サーバーの停止で監視できなくなった学習を「失敗」にし、平文の一時ファイルを削除する。"""
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT id FROM training_runs WHERE status = 'running'").fetchall()
        for row in rows:
            self._finish(row["id"], "failed", error="サーバーが停止したため学習が中断されました。")
            run_dir = self._run_dir(row["id"])
            if run_dir.exists():
                self._scrub(run_dir)

    # ---------- 参照 ----------

    @staticmethod
    def _read_status(run_dir: Path) -> dict | None:
        try:
            return json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def get(self, run_id: str) -> TrainingRun | None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM training_runs WHERE id = ?", (run_id,)).fetchone()
        return self._to_model(row) if row else None

    def list(self) -> list[TrainingRun]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT * FROM training_runs ORDER BY created_at DESC, rowid DESC").fetchall()
        return [self._to_model(r) for r in rows]

    def log_tail(self, run_id: str, lines: int = 80) -> str:
        path = self._run_dir(run_id) / "train.log"
        if not path.exists():
            return ""
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    def _to_model(self, row: Any) -> TrainingRun:
        data = dict(row)
        data["params"] = json.loads(data["params"])
        data["metrics"] = json.loads(self.vault.decrypt(data["metrics"])) if data["metrics"] else None
        run = TrainingRun(**data)
        if run.status == "running":
            run.progress = self._read_status(self._run_dir(run.id))
        run.active = bool(run.ollama_model) and self.settings.get().model == run.ollama_model
        return run

    # ---------- 切り替え・元に戻す ----------

    def activate(self, run_id: str) -> TrainingRun:
        run = self.get(run_id)
        if run is None or run.status != "succeeded" or not run.ollama_model:
            raise TrainingError("使用できる学習結果ではありません。", "not_usable", 409)
        current = self.settings.get().model
        # 元のモデルを覚えておき、いつでも戻せるようにする（学習済みモデル同士の切り替えでは上書きしない）
        if not current.startswith("twin-"):
            self.settings.set_raw("model_before_adapter", current)
        self.settings.update({"model": run.ollama_model})
        result = self.get(run_id)
        assert result is not None
        return result

    def revert(self) -> str:
        original = self.settings.get_raw("model_before_adapter") or "qwen3:8b"
        self.settings.update({"model": original})
        return original

    async def delete(self, run_id: str) -> None:
        run = self.get(run_id)
        if run is None:
            raise TrainingError("指定された学習結果が見つかりません。", "not_found", 404)
        if run.status == "running":
            raise TrainingError("実行中の学習は削除できません。中止してから削除してください。", "training_running", 409)
        if run.active:
            self.revert()
        if run.ollama_model:
            try:
                await self.ollama.delete_model(run.ollama_model)
            except OllamaError:
                logger.warning("Could not delete Ollama model %s", run.ollama_model)
        shutil.rmtree(self._run_dir(run_id), ignore_errors=True)
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM training_runs WHERE id = ?", (run_id,))


def replace_from(modelfile: str, source: str) -> str:
    """Modelfile の先頭のコメントと FROM 行だけを差し替える（テンプレート内の行には触れない）。"""
    lines = modelfile.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("FROM "):
            return "\n".join([f"FROM {source}", *lines[i + 1:]]) + "\n"
    raise TrainingError("元モデルの定義を読み取れませんでした。", "modelfile_invalid")


def _clean_env() -> dict[str, str]:
    # アプリ側の Python 設定が学習プロセスに混ざらないようにする
    return {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV"))}
