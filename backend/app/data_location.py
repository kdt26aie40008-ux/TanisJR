"""個人データの保存先の管理（PC・Windows ユーザーごと。アカウントの仕組みは使わない）。

- 以前のバージョンはプロジェクトフォルダー内の data/ に保存していた。起動時、それが **このPC・このユーザーの**
  データ（暗号鍵をこのユーザーの DPAPI で読める）なら、新しい保存先へ移す。
  別の PC・別のユーザーのデータ（鍵を読めない）は使わず、そのまま残す（新しい人は空の状態から始まる）。
- データがロックされていて復元もできない場合は、「新しく始める」で既存データを別名フォルダーへ退避して
  空の状態から始め直せる（データは削除しない）。
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

from app.crypto import CryptoError, KeyStore, Protector

logger = logging.getLogger(__name__)

RESET_FLAG = ".start-fresh-requested"


def _has_data(directory: Path) -> bool:
    return (directory / "twin.db").exists()


def _move_contents(source: Path, target: Path) -> None:
    """source の中身を target へ移す。同名のフォルダーは中身を合わせ、同名のファイルは新しい保存先を優先する。"""
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        dest = target / item.name
        if item.is_dir() and dest.is_dir():
            _move_contents(item, dest)
        elif not dest.exists():
            shutil.move(str(item), str(dest))


def migrate_legacy_data(legacy: Path, target: Path, protector: Protector) -> str:
    """以前の保存先のデータを、このユーザーのものなら新しい保存先へ移す。結果を表す文字列を返す。"""
    if not _has_data(legacy):
        return "no-legacy-data"
    if _has_data(target):
        return "target-has-data"
    key_file = legacy / "keys" / "master.key"
    try:
        KeyStore(key_file, protector).load()
    except CryptoError:
        # 別の PC・別の Windows ユーザーのデータ。読めないので使わず、そのまま残す
        logger.info("Legacy data belongs to another PC or user; starting with empty data")
        return "other-user-data"
    _move_contents(legacy, target)
    shutil.rmtree(legacy, ignore_errors=True)
    logger.info("Moved this user's data to the per-user data folder")
    return "moved"


def request_start_fresh(data_dir: Path) -> None:
    """次の起動時に、今のデータを退避して空の状態から始める（開いているファイルは動かせないため起動時に行う）。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / RESET_FLAG).write_text(datetime.now().isoformat(), encoding="utf-8")


def apply_start_fresh(data_dir: Path) -> Path | None:
    """「新しく始める」が要求されていれば、データを別名フォルダーへ退避する（削除はしない）。"""
    if not (data_dir / RESET_FLAG).exists():
        return None
    archive = data_dir.with_name(f"{data_dir.name}-archived-{datetime.now():%Y%m%d-%H%M%S}")
    # 直前まで使っていたプロセスがファイルを手放すまで、少し待ちながら試す
    for attempt in range(10):
        try:
            data_dir.rename(archive)
            break
        except OSError:
            if attempt == 9:
                # 退避できなくても起動は続ける（ロック画面のまま。要求は残すので次回の起動で再試行する）
                logger.warning("Could not archive the data folder; it may be in use")
                return None
            time.sleep(1)
    (archive / RESET_FLAG).unlink(missing_ok=True)
    data_dir.mkdir(parents=True)
    logger.info("Archived previous data to %s and started fresh", archive.name)
    return archive
