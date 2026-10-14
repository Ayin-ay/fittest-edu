"""SQLite-backed run store: how a student's progress survives closing the page.

The teaching use case is the whole reason this exists. A class plays ten matches
in a lesson, and the report is meant to be read a week later -- by the student,
and in aggregate by the teacher. ``session_state`` cannot do that: it lives
inside one WebSocket connection, so a refresh, a new tab or an idle phone drops
everything.

What is stored is deliberately tiny: the setup (opponent count, turns, seed),
the player's own actions per match, and the tutorial flag. Opponent encodings,
both sides' scores, every per-turn record, the nine measurements and the results
matrix are all *recomputed* from those few fields, because the engine is
deterministic and the same seed replays to the same run. That is the same
property ``_game_payload`` already relies on for URL restore, so there is one
source of truth rather than a stored report that can drift from the decisions
that produced it.

Privacy: the primary key is a random join code the player keeps. No name, no
email, no account, no password, and nothing that identifies a person is accepted
here. The optional class code groups runs for the teacher's board and is a label
the teacher invents, not a roster of students.

Deployment: Streamlit Cloud's free tier has an ephemeral filesystem, so this
database is reset on a redeploy. :func:`export_csv` and :func:`import_csv` exist
for exactly that reason -- the teacher downloads the whole table at the end of
the lesson and can put it back. See docs/deployment.md.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import secrets
import sqlite3

from evolution_archive import ARCHIVE_DIR

DB_PATH = ARCHIVE_DIR / "roster.sqlite3"

#: No I/O/0/1: a code read aloud or copied from a printed sheet has to survive
#: being retyped by hand.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

COLUMNS = [
    "join_code", "class_code", "status", "engine_version",
    "opponent_count", "turns", "seed", "actions", "tutorial_done",
    "created_at", "updated_at",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    join_code      TEXT PRIMARY KEY,
    class_code     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    opponent_count INTEGER NOT NULL,
    turns          INTEGER NOT NULL,
    seed           INTEGER NOT NULL,
    actions        TEXT NOT NULL DEFAULT '',
    tutorial_done  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'playing'
);
CREATE INDEX IF NOT EXISTS runs_class ON runs (class_code);
"""


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """Open the store, creating ``archive/`` and the schema on first use."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def normalize_code(value: str) -> str:
    """Upper-case and strip a hand-typed code; hyphens and spaces are ignored."""
    return "".join(ch for ch in value.upper() if ch.isalnum())


def new_join_code() -> str:
    """An unused 8-character join code.

    Codes are the only handle a player has on their own data, so a collision is
    not cosmetic: it would hand one student's run to another. Drawing again on
    collision makes that impossible without needing a lock.
    """
    with connect() as connection:
        for _ in range(20):
            code = "".join(
                secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH)
            )
            taken = connection.execute(
                "SELECT 1 FROM runs WHERE join_code = ?", (code,)
            ).fetchone()
            if taken is None:
                return code
    raise RuntimeError("无法分配加入码：连续 20 次都撞码。")


def create_run(
    join_code: str, *, class_code: str, opponent_count: int, turns: int,
    seed: int, engine_version: str, tutorial_done: bool = False,
) -> None:
    """Register a run so it can be reloaded before any decision exists."""
    with connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO runs (join_code, class_code, created_at,"
            " updated_at, engine_version, opponent_count, turns, seed, actions,"
            " tutorial_done, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'playing')",
            (join_code, class_code.strip(), _now(), _now(), engine_version,
             opponent_count, turns, seed, int(bool(tutorial_done))),
        )


def save_progress(
    join_code: str, *, actions: list[str], tutorial_done: bool,
    status: str = "playing",
) -> None:
    """Write the player's decisions so far. Idempotent and cheap.

    ``actions`` is one string per match in match order, the last one possibly
    shorter than ``turns`` while a match is still in progress.
    """
    with connect() as connection:
        connection.execute(
            "UPDATE runs SET actions = ?, tutorial_done = ?, status = ?,"
            " updated_at = ? WHERE join_code = ?",
            (".".join(actions), int(bool(tutorial_done)), status, _now(), join_code),
        )


def load_run(join_code: str) -> dict | None:
    """One stored run by code, or ``None`` if the code is unknown."""
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE join_code = ?", (normalize_code(join_code),)
        ).fetchone()
    return _as_run(row) if row else None


def _as_run(row: sqlite3.Row) -> dict:
    return {
        "join_code": row["join_code"],
        "class_code": row["class_code"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "engine_version": row["engine_version"],
        "count": row["opponent_count"],
        "turns": row["turns"],
        "seed": row["seed"],
        "actions": [part for part in row["actions"].split(".") if part],
        "tutorial_done": bool(row["tutorial_done"]),
        "status": row["status"],
    }


def list_runs(class_code: str | None = None) -> list[dict]:
    """Every stored run, newest first; ``class_code`` narrows it to one class."""
    query = "SELECT * FROM runs"
    args: tuple = ()
    if class_code:
        query += " WHERE class_code = ?"
        args = (class_code.strip(),)
    query += " ORDER BY updated_at DESC"
    with connect() as connection:
        return [_as_run(row) for row in connection.execute(query, args)]


def export_csv() -> bytes:
    """The whole table as CSV -- the teacher's backup and the class spreadsheet.

    Written with a UTF-8 BOM: these files open in Excel in Chinese classrooms,
    and without it every 班级码 arrives as mojibake.
    """
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    with connect() as connection:
        for row in connection.execute("SELECT * FROM runs ORDER BY created_at"):
            record = dict(row)
            record["tutorial_done"] = "1" if record["tutorial_done"] else "0"
            writer.writerow({name: record[name] for name in COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")


def import_csv(data: bytes) -> int:
    """Restore rows from a CSV made by :func:`export_csv`. Returns the count.

    Re-importing is the recovery path for a redeploy that wiped the file: the
    rows carry seed and actions, so every report rebuilds exactly as before.
    """
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or "join_code" not in reader.fieldnames:
        raise ValueError("这份 CSV 缺少 join_code 列，不像是本站导出的名单。")
    inserted = 0
    with connect() as connection:
        for record in reader:
            code = normalize_code(record.get("join_code") or "")
            if len(code) != CODE_LENGTH:
                continue
            connection.execute(
                "INSERT OR REPLACE INTO runs (join_code, class_code, created_at,"
                " updated_at, engine_version, opponent_count, turns, seed, actions,"
                " tutorial_done, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    (record.get("class_code") or "").strip(),
                    record.get("created_at") or _now(),
                    record.get("updated_at") or _now(),
                    record.get("engine_version") or "",
                    int(record.get("opponent_count") or 0),
                    int(record.get("turns") or 0),
                    int(record.get("seed") or 0),
                    (record.get("actions") or "").strip(),
                    int(record.get("tutorial_done") == "1"),
                    record.get("status") or "playing",
                ),
            )
            inserted += 1
    return inserted
