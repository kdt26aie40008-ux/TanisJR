"""LoRA / QLoRA 学習スクリプト（アプリとは別の venv で実行する）。

使い方: python train_lora.py --run-dir <data/training/runs/<id>>
  入力: config.json（設定）, train.jsonl（承認済みデータ。終了後にアプリが削除する）
  出力: status.json（進捗）, metrics.json（評価結果）, adapter/（LoRA アダプター）

本文はログに出力しない（損失などの数値のみ）。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import traceback
from pathlib import Path


def write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class Status:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "status.json"
        self.data: dict = {"state": "starting", "phase": "準備中", "step": 0, "total_steps": 0, "loss": None, "eta_seconds": None}

    def update(self, **values: object) -> None:
        self.data.update(values, updated_at=time.time())
        write_json(self.path, self.data)


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    run_dir = Path(parser.parse_args().run_dir)
    status = Status(run_dir)
    try:
        return train(run_dir, status)
    except Exception as exc:  # noqa: BLE001
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            message = "GPUメモリが不足しました。系列長を短くするか、より小さいモデルで学習してください。"
        else:
            message = f"学習中にエラーが発生しました（{type(exc).__name__}）。ログを確認してください。"
        log("ERROR " + type(exc).__name__)
        traceback.print_exc()
        status.update(state="failed", phase="失敗", error=message)
        return 1


def train(run_dir: Path, status: Status) -> int:
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, get_cosine_schedule_with_warmup

    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    random.seed(cfg.get("seed", 42))
    torch.manual_seed(cfg.get("seed", 42))
    if not torch.cuda.is_available():
        status.update(state="failed", phase="失敗", error="CUDA が使えません。GPU ドライバーを確認してください。")
        return 1

    status.update(state="running", phase="モデルを読み込み中")
    log(f"base={cfg['base_path']} qlora={cfg['quantize_4bit']} device={torch.cuda.get_device_name(0)}")
    tokenizer = AutoTokenizer.from_pretrained(cfg["base_path"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant = None
    if cfg["quantize_4bit"]:
        quant = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True
        )
    model = AutoModelForCausalLM.from_pretrained(
        cfg["base_path"], dtype=torch.bfloat16, quantization_config=quant, device_map={"": 0}
    )
    model.config.use_cache = False
    if quant is not None:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    else:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()

    # ---------- データ ----------
    examples = [json.loads(line) for line in (run_dir / "train.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    random.shuffle(examples)
    n_eval = max(1, len(examples) // 10) if len(examples) >= 5 else 0
    eval_set, train_set = examples[:n_eval], examples[n_eval:]
    max_len = int(cfg["max_seq_len"])

    def encode(messages: list[dict]) -> dict | None:
        # 応答部分だけを学習対象にする（システム・ユーザー発言は損失に含めない）
        prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        full = tokenizer.apply_chat_template(messages, tokenize=False, enable_thinking=False)
        prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        full_ids = tokenizer(full, add_special_tokens=False)["input_ids"][:max_len]
        if len(prompt_ids) >= len(full_ids):
            return None  # 切り詰めで応答が残らない
        labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
        return {"input_ids": full_ids, "labels": labels[: len(full_ids)]}

    train_items = [x for x in (encode(e["messages"]) for e in train_set) if x]
    eval_items = [x for x in (encode(e["messages"]) for e in eval_set) if x]
    if not train_items:
        status.update(state="failed", phase="失敗", error="学習できるデータがありません（すべて長すぎる可能性があります）。")
        return 1
    log(f"train={len(train_items)} eval={len(eval_items)} max_len={max_len}")

    def to_batch(item: dict) -> dict:
        ids = torch.tensor([item["input_ids"]], device=model.device)
        return {"input_ids": ids, "attention_mask": torch.ones_like(ids), "labels": torch.tensor([item["labels"]], device=model.device)}

    @torch.no_grad()
    def eval_loss(m) -> float | None:  # noqa: ANN001
        if not eval_items:
            return None
        m.eval()
        losses = [m(**to_batch(it)).loss.item() for it in eval_items]
        m.train()
        return sum(losses) / len(losses)

    @torch.no_grad()
    def samples(m) -> list[str]:  # noqa: ANN001
        outputs = []
        m.eval()
        for prompt in cfg.get("eval_prompts", [])[:3]:
            messages = [{"role": "system", "content": cfg["system_prompt"]}, {"role": "user", "content": prompt}]
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
            ids = tokenizer(text, return_tensors="pt").to(m.device)
            out = m.generate(**ids, max_new_tokens=160, do_sample=False, use_cache=True)
            outputs.append(tokenizer.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip())
        m.train()
        return outputs

    status.update(phase="学習前の評価")
    model.config.use_cache = True
    before_loss = eval_loss(model)
    before_samples = samples(model)
    model.config.use_cache = False

    # ---------- LoRA ----------
    lora = LoraConfig(
        r=int(cfg["lora_r"]),
        lora_alpha=int(cfg["lora_alpha"]),
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"trainable_params={trainable}")

    epochs = int(cfg["epochs"])
    accum = int(cfg["grad_accum"])
    total_steps = math.ceil(len(train_items) * epochs / accum)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=float(cfg["learning_rate"]))
    scheduler = get_cosine_schedule_with_warmup(optimizer, max(1, total_steps // 10), total_steps)
    status.update(phase="学習中", total_steps=total_steps)

    model.train()
    step, started, running = 0, time.time(), []
    for epoch in range(epochs):
        random.shuffle(train_items)
        for i, item in enumerate(train_items):
            loss = model(**to_batch(item)).loss / accum
            loss.backward()
            running.append(loss.item() * accum)
            if (i + 1) % accum == 0 or i == len(train_items) - 1:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                elapsed = time.time() - started
                avg = sum(running[-20:]) / len(running[-20:])
                status.update(
                    step=step, epoch=epoch + 1, loss=round(avg, 4),
                    eta_seconds=int(elapsed / step * (total_steps - step)),
                    gpu_memory_gb=round(torch.cuda.max_memory_allocated() / 1024**3, 2),
                )
                if step % 5 == 0 or step == total_steps:
                    log(f"step {step}/{total_steps} loss={avg:.4f}")

    status.update(phase="学習後の評価")
    model.config.use_cache = True
    after_loss = eval_loss(model)
    after_samples = samples(model)

    status.update(phase="保存中")
    model.save_pretrained(run_dir / "adapter")
    peak_gb = round(torch.cuda.max_memory_allocated() / 1024**3, 2)

    # Ollama は LoRA アダプター単体を読み込めないため、元モデルに統合した完全なモデルを書き出す（CPU で実行）
    status.update(phase="モデルに統合中")
    from peft import PeftModel

    del model, optimizer
    torch.cuda.empty_cache()
    base_cpu = AutoModelForCausalLM.from_pretrained(cfg["base_path"], dtype=torch.bfloat16, device_map={"": "cpu"})
    merged = PeftModel.from_pretrained(base_cpu, str(run_dir / "adapter")).merge_and_unload()
    merged.save_pretrained(run_dir / "merged", safe_serialization=True)
    tokenizer.save_pretrained(run_dir / "merged")
    log("merged model saved")
    write_json(
        run_dir / "metrics.json",
        {
            "eval_loss_before": before_loss,
            "eval_loss_after": after_loss,
            "train_examples": len(train_items),
            "eval_examples": len(eval_items),
            "train_seconds": int(time.time() - started),
            "peak_gpu_memory_gb": peak_gb,
            "samples": [
                {"prompt": p, "before": b, "after": a}
                for p, b, a in zip(cfg.get("eval_prompts", [])[:3], before_samples, after_samples)
            ],
        },
    )
    status.update(state="succeeded", phase="完了")
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
