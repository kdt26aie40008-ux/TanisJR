"""学習データの管理・学習の実行（手動）・評価・切り替え・蒸留。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.deps import Services, get_services
from app.errors import AppError
from app.llm.ollama import OllamaError
from app.schemas import ID_PATTERN
from app.services.persona import build_system_prompt
from app.training.data import ExampleInput, ExampleUpdate, TrainingExample
from app.training.runner import TrainingError, TrainingParams, TrainingRun

router = APIRouter(prefix="/api/training", tags=["training"])

def _id() -> object:
    return Path(pattern=ID_PATTERN)


def _system_prompt(services: Services) -> str:
    settings = services.settings.get()
    return build_system_prompt(
        settings.ai_name, services.profile.list(), language=settings.language, ai_reading=settings.wake_reading
    )


def _error(exc: TrainingError) -> AppError:
    return AppError(exc.status, exc.code, exc.message)


def _not_found() -> AppError:
    return AppError(404, "not_found", "指定されたデータが見つかりません。")


# ---------- 学習データ ----------


@router.get("/examples")
def list_examples(
    status: Literal["pending", "approved", "rejected"] | None = None, services: Services = Depends(get_services)
) -> dict:
    return {"examples": services.training_data.list(status), "counts": services.training_data.counts()}


@router.post("/examples")
def add_example(body: ExampleInput, services: Services = Depends(get_services)) -> TrainingExample:
    example = services.training_data.add(body.user_text, body.assistant_text, "manual")
    if example is None:
        raise AppError(409, "duplicate", "同じ内容の学習データがすでにあります。")
    return example


class FromConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = Field(pattern=ID_PATTERN)


@router.post("/examples/from-conversation")
def from_conversation(body: FromConversation, services: Services = Depends(get_services)) -> dict:
    """保存を許可した会話から、学習データの候補（承認待ち）を作る。"""
    try:
        created = services.training_data.add_from_conversation(body.conversation_id)
    except KeyError as exc:
        raise AppError(404, "conversation_not_found", "指定された会話が見つかりません。") from exc
    return {"created": len(created)}


@router.put("/examples/{example_id}")
def update_example(body: ExampleUpdate, example_id: str = _id(), services: Services = Depends(get_services)) -> TrainingExample:
    example = services.training_data.update(example_id, body)
    if example is None:
        raise _not_found()
    return example


@router.post("/examples/{example_id}/{decision}")
def decide(
    decision: Literal["approve", "reject", "pending"], example_id: str = _id(), services: Services = Depends(get_services)
) -> TrainingExample:
    status = {"approve": "approved", "reject": "rejected", "pending": "pending"}[decision]
    example = services.training_data.set_status(example_id, status)  # type: ignore[arg-type]
    if example is None:
        raise _not_found()
    return example


@router.delete("/examples/{example_id}")
def delete_example(example_id: str = _id(), services: Services = Depends(get_services)) -> dict:
    if not services.training_data.delete(example_id):
        raise _not_found()
    return {"deleted": True}


@router.post("/examples/dedupe")
def dedupe(services: Services = Depends(get_services)) -> dict:
    return {"removed": services.training_data.dedupe()}


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # エクスポートしたファイルは暗号化されないことを確認した
    confirmed: bool


@router.post("/examples/export")
def export(body: ExportRequest, services: Services = Depends(get_services)) -> Response:
    if not body.confirmed:
        raise AppError(400, "confirmation_required", "エクスポートしたファイルは暗号化されません。確認してから実行してください。")
    content = services.training_data.export_jsonl(_system_prompt(services))
    return Response(
        content=content.encode("utf-8"),
        media_type="application/jsonl",
        headers={"Content-Disposition": 'attachment; filename="twin-training-data.jsonl"', "Cache-Control": "no-store"},
    )


class DistillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=20)


@router.post("/distill")
async def distill(body: DistillRequest, services: Services = Depends(get_services)) -> dict:
    """蒸留: 承認済みデータの質問に教師モデル（会話用モデル）が答え、その回答を承認待ちの学習データにする。"""
    if services.training.running:
        raise AppError(503, "training_running", "追加学習を実行中のため、蒸留データは作れません。")
    settings = services.settings.get()
    teacher = services.settings.get_raw("model_before_adapter") if settings.model.startswith("twin-") else settings.model
    teacher = teacher or "qwen3:8b"
    system = _system_prompt(services)
    prompts = list(dict.fromkeys(user for user, _ in services.training_data.approved_pairs()))[: body.limit]
    if not prompts:
        raise AppError(400, "no_prompts", "承認済みの学習データがありません。先に学習データを承認してください。")
    created = 0
    for prompt in prompts:
        try:
            answer = await services.ollama.chat_once(
                teacher,
                [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                {"temperature": 0.7, "num_ctx": 4096},
            )
        except OllamaError as exc:
            raise AppError(502, exc.code, exc.message) from exc
        answer = answer.split("</think>")[-1].strip()
        if answer and services.training_data.add(prompt, answer[:4000], "distill"):
            created += 1
    return {"created": created, "teacher": teacher}


# ---------- 学習の実行 ----------


@router.get("/environment")
def environment(services: Services = Depends(get_services)) -> dict:
    return services.training.environment()


@router.post("/runs")
async def start(body: TrainingParams, services: Services = Depends(get_services)) -> TrainingRun:
    """学習を開始する（必ず手動。実行前の確認に同意している必要がある）。"""
    try:
        return await services.training.start(body, _system_prompt(services))
    except TrainingError as exc:
        raise _error(exc) from exc


@router.get("/runs")
def runs(services: Services = Depends(get_services)) -> dict:
    return {"runs": services.training.list(), "model": services.settings.get().model}


@router.get("/runs/{run_id}/log")
def run_log(run_id: str = _id(), lines: int = Query(default=80, ge=1, le=500), services: Services = Depends(get_services)) -> dict:
    return {"log": services.training.log_tail(run_id, lines)}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str = _id(), services: Services = Depends(get_services)) -> TrainingRun:
    try:
        return services.training.cancel(run_id)
    except TrainingError as exc:
        raise _error(exc) from exc


@router.post("/runs/{run_id}/activate")
def activate(run_id: str = _id(), services: Services = Depends(get_services)) -> TrainingRun:
    try:
        return services.training.activate(run_id)
    except TrainingError as exc:
        raise _error(exc) from exc


@router.post("/revert")
def revert(services: Services = Depends(get_services)) -> dict:
    return {"model": services.training.revert()}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str = _id(), services: Services = Depends(get_services)) -> dict:
    try:
        await services.training.delete(run_id)
    except TrainingError as exc:
        raise _error(exc) from exc
    return {"deleted": True}
