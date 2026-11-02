"""暗号鍵の読み込み（ロック判定）と、バックアップからの復元。"""

from __future__ import annotations

import asyncio
import logging

from app.backup import BackupContents, BackupError, read_backup, restore_database, snapshot_setting
from app.crypto import KEY_CHECK_PLAINTEXT, CryptoError, FieldCipher, KeyStore, Vault
from app.db import LATEST_VERSION
from app.repositories.profile import ProfileRepository
from app.repositories.settings import SettingsRepository

logger = logging.getLogger(__name__)

KEY_CHECK_SETTING = "key_check"

LOCKED_KEY_UNREADABLE = (
    "このPC・Windowsユーザーでは暗号鍵を読み込めません。別のPCやWindowsの再インストール後の場合は、"
    "バックアップファイルから復元してください。"
)
LOCKED_KEY_MISSING = "暗号鍵ファイルが見つかりません。バックアップファイルから復元してください。"
LOCKED_KEY_MISMATCH = "暗号鍵が保存データと一致しません。バックアップファイルから復元してください。"


def _verify(cipher: FieldCipher, check: str) -> bool:
    try:
        return cipher.decrypt(check) == KEY_CHECK_PLAINTEXT
    except CryptoError:
        return False


def unlock(vault: Vault, keystore: KeyStore, settings: SettingsRepository, profile: ProfileRepository) -> None:
    """鍵を読み込む。初回は鍵を作成する。読み込めない場合はロック状態にする（データは消さない）。"""
    check = settings.get_raw(KEY_CHECK_SETTING)
    if keystore.exists():
        try:
            cipher = FieldCipher(keystore.load())
        except CryptoError:
            vault.lock(LOCKED_KEY_UNREADABLE)
            return
        if check and not _verify(cipher, check):
            vault.lock(LOCKED_KEY_MISMATCH)
            return
    elif check:
        vault.lock(LOCKED_KEY_MISSING)
        return
    else:
        cipher = FieldCipher(keystore.create())
    if not check:
        settings.set_raw(KEY_CHECK_SETTING, cipher.encrypt(KEY_CHECK_PLAINTEXT))
    vault.unlock(cipher)
    migrated = profile.encrypt_legacy_rows()
    if migrated:
        logger.info("Encrypted %d legacy profile entries", migrated)


async def restore(services, blob: bytes, passphrase: str) -> BackupContents:  # noqa: ANN001
    contents = await asyncio.to_thread(read_backup, blob, passphrase)
    if contents.schema_version > LATEST_VERSION:
        raise BackupError("新しいバージョンのアプリで作成されたバックアップのため復元できません。アプリを更新してください。")
    cipher = FieldCipher(contents.master_key)
    # 現在のデータを上書きする前に、鍵とデータの組み合わせを検証する
    check = snapshot_setting(contents.database, KEY_CHECK_SETTING)
    if check and not _verify(cipher, check):
        raise BackupError("バックアップ内の鍵とデータが一致しません。ファイルが破損している可能性があります。")
    await asyncio.to_thread(restore_database, services.db.path, contents.database)
    services.db.migrate()
    services.keystore.save(contents.master_key)
    unlock(services.vault, services.keystore, services.settings, services.profile)
    # 索引はバックアップに含めないため作り直す
    services.index.drop_all()
    services.memories.clear_index_marks()
    await services.memory.reconcile()
    return contents
