"""llama.cpp の GGUF 変換スクリプト（convert_hf_to_gguf.py と依存する Python ファイル）だけを取得する。

使い方: training\\.venv\\Scripts\\python training\\fetch_llama_cpp.py
取得先: training/llama.cpp/（Git の管理対象外。llama.cpp は MIT ライセンス）
"""

from __future__ import annotations

import json
import pathlib
import urllib.request

API = "https://api.github.com/repos/ggml-org/llama.cpp"
DEST = pathlib.Path(__file__).resolve().parent / "llama.cpp"


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "personal-twin-ai"})) as r:
        return r.read()


def wanted(path: str) -> bool:
    if path in ("convert_hf_to_gguf.py", "convert_lora_to_gguf.py", "LICENSE", "gguf-py/LICENSE"):
        return True
    return path.startswith(("gguf-py/gguf/", "conversion/")) and path.endswith((".py", ".json"))


def main() -> None:
    tag = json.loads(get(f"{API}/releases/latest"))["tag_name"]
    tree = json.loads(get(f"{API}/git/trees/{tag}?recursive=1"))["tree"]
    files = [t["path"] for t in tree if t["type"] == "blob" and wanted(t["path"])]
    for path in files:
        out = DEST / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(get(f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{tag}/{path}"))
    (DEST / "VERSION.txt").write_text(tag)
    print(f"llama.cpp {tag}: {len(files)} files -> {DEST}")


if __name__ == "__main__":
    main()
