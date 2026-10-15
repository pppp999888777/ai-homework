"""SQLite 持久化：作业提交记录与批改结果。"""
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import List

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "homework.db"
UPLOAD_DIR = DATA_DIR / "uploads"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  TEXT NOT NULL,
            homework_id TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            score       INTEGER NOT NULL,
            image_path  TEXT,
            result_json TEXT NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sub_student ON submissions(student_id, created_at)")
    return conn


def save_submission(student_id: str, homework_id: str, image: bytes, ext: str, result: dict) -> int:
    conn = connect()
    now = datetime.now()
    safe_id = "".join(c for c in homework_id if c.isalnum() or c in "-_")
    image_path = UPLOAD_DIR / f"{now:%Y%m%d-%H%M%S}_{safe_id}.{ext}"
    image_path.write_bytes(image)
    with closing(conn), conn:
        cur = conn.execute(
            "INSERT INTO submissions (student_id, homework_id, created_at, score, image_path, result_json) VALUES (?,?,?,?,?,?)",
            (student_id, homework_id, now.isoformat(timespec="seconds"), result["total_score"],
             str(image_path.relative_to(DATA_DIR)), json.dumps(result, ensure_ascii=False)),
        )
        return cur.lastrowid


def list_submissions(student_id: str, limit: int = 50) -> List[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT id, homework_id, created_at, score, result_json FROM submissions WHERE student_id=? ORDER BY id DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    return [{**{k: r[k] for k in ("id", "homework_id", "created_at", "score")}, "result": json.loads(r["result_json"])} for r in rows]
