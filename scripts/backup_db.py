"""Database backup helper (WAL-safe online backup)."""
import datetime
import sqlite3
from pathlib import Path


def backup_db(src_path: str = "data/unlockaid.db", dst_dir: str = "data/backups") -> Path:
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"Source database does not exist: {src}")
    dst_folder = Path(dst_dir)
    dst_folder.mkdir(parents=True, exist_ok=True)
    dst = dst_folder / f"{datetime.date.today().isoformat()}.db"
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    return dst


if __name__ == "__main__":
    out = backup_db()
    print(f"backup written: {out}")
