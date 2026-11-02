"""ローカル保存データの暗号化。

- マスター鍵はランダム生成し、Windows DPAPI（現在の Windows ユーザーに紐づく）で保護して保存する。
- 機密列は AES-256-GCM で暗号化し、`enc:v1:` 接頭辞付きの文字列として保存する。
"""

from __future__ import annotations

import base64
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "enc:v1:"
KEY_SIZE = 32
NONCE_SIZE = 12
KEY_CHECK_PLAINTEXT = "personal-twin-ai:key-check"


class CryptoError(Exception):
    pass


class DataLocked(CryptoError):
    """鍵が利用できないため、保存データを読み書きできない状態。"""


class Protector(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class DpapiProtector:
    """Windows DPAPI (CryptProtectData) によるマスター鍵の保護。"""

    _ENTROPY = b"PersonalTwinAI.master-key.v1"
    _UI_FORBIDDEN = 0x01

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise CryptoError("鍵の保護には Windows (DPAPI) が必要です。")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_p = ctypes.POINTER(self._Blob)
        for name in ("CryptProtectData", "CryptUnprotectData"):
            fn = getattr(self._crypt32, name)
            fn.argtypes = [blob_p, wintypes.LPCWSTR, blob_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_p]
            fn.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def _blob(self, data: bytes) -> tuple[_Blob, ctypes.Array]:
        buf = ctypes.create_string_buffer(data, len(data))
        return self._Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _call(self, fn, data: bytes) -> bytes:  # noqa: ANN001
        in_blob, _in_buf = self._blob(data)
        ent_blob, _ent_buf = self._blob(self._ENTROPY)
        out = self._Blob()
        if not fn(ctypes.byref(in_blob), None, ctypes.byref(ent_blob), None, None, self._UI_FORBIDDEN, ctypes.byref(out)):
            raise CryptoError(f"DPAPI の処理に失敗しました (WinError {ctypes.get_last_error()})")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            self._kernel32.LocalFree(out.pbData)

    def protect(self, data: bytes) -> bytes:
        return self._call(self._crypt32.CryptProtectData, data)

    def unprotect(self, data: bytes) -> bytes:
        return self._call(self._crypt32.CryptUnprotectData, data)


class FieldCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_SIZE:
            raise CryptoError("鍵の長さが正しくありません。")
        self.key = key
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(NONCE_SIZE)
        token = nonce + self._aead.encrypt(nonce, plaintext.encode("utf-8"), None)
        return PREFIX + base64.urlsafe_b64encode(token).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value.startswith(PREFIX):
            # Phase 1 以前の平文データ（起動時に暗号化し直す）
            return value
        try:
            token = base64.urlsafe_b64decode(value[len(PREFIX):])
            return self._aead.decrypt(token[:NONCE_SIZE], token[NONCE_SIZE:], None).decode("utf-8")
        except (InvalidTag, ValueError) as exc:
            raise CryptoError("保存データを復号できませんでした。") from exc


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)  # type: ignore[union-attr]


class Vault:
    """現在の暗号鍵を保持する。復元時に鍵を差し替えられるよう、各リポジトリはこれを共有する。"""

    def __init__(self) -> None:
        self._cipher: FieldCipher | None = None
        self.locked_reason: str | None = "暗号鍵が読み込まれていません。"

    @property
    def cipher(self) -> FieldCipher:
        if self._cipher is None:
            raise DataLocked(self.locked_reason or "データがロックされています。")
        return self._cipher

    @property
    def locked(self) -> bool:
        return self._cipher is None

    def unlock(self, cipher: FieldCipher) -> None:
        self._cipher = cipher
        self.locked_reason = None

    def lock(self, reason: str) -> None:
        self._cipher = None
        self.locked_reason = reason

    def encrypt(self, plaintext: str) -> str:
        return self.cipher.encrypt(plaintext)

    def decrypt(self, value: str) -> str:
        return self.cipher.decrypt(value)

    def decrypt_opt(self, value: str | None) -> str | None:
        return None if value is None else self.cipher.decrypt(value)


class KeyStore:
    def __init__(self, path: Path, protector: Protector) -> None:
        self.path = path
        self.protector = protector

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> bytes:
        try:
            key = self.protector.unprotect(self.path.read_bytes())
        except (OSError, CryptoError) as exc:
            raise CryptoError("暗号鍵を読み込めませんでした。") from exc
        if len(key) != KEY_SIZE:
            raise CryptoError("暗号鍵が破損しています。")
        return key

    def save(self, key: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self.protector.protect(key))
        os.replace(tmp, self.path)

    def create(self) -> bytes:
        key = AESGCM.generate_key(bit_length=KEY_SIZE * 8)
        self.save(key)
        return key
