"""SQLite-backed run store: how a student's progress survives closing the page.

The teaching use case is the whole reason this exists. A class plays ten matches
in a lesson, and the report is meant to be read a week later -- by the student,
and in aggregate by the teacher. ``session_state`` cannot do that: it lives
inside one WebSocket connection, so a refresh, a new tab or an idle phone drops
everything.

What is stored is deliberately tiny: the setup (opponent count, turns, seed),
the player's own actions per match, the guesses made for the optional
predict-each-turn exercise, and the tutorial flag. Opponent encodings,
both sides' scores, every per-turn record, the nine measurements and the results
matrix are all *recomputed* from those few fields, because the engine is
deterministic and the same seed replays to the same run. That is the same
property ``_game_payload`` already relies on for URL restore, so there is one
source of truth rather than a stored report that can drift from the decisions
that produced it. Guesses are recorded alongside the decisions but never feed
back into them: the engine resolves a turn from the action alone, so a run with
predictions and the same run without them score identically.

Privacy: the primary key is a random join code the player keeps. No name, no
email, no account, no password, and nothing that identifies a person is accepted
here. The optional class code groups runs for the teacher's board and is a label
the teacher invents, not a roster of students. The challenge code says which
fixed opponent set a run was played against -- it is the key the class ranking
groups by, and it carries nothing about who played.

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
    "join_code", "class_code", "challenge_id", "status", "engine_version",
    "opponent_count", "turns", "seed", "actions", "predictions",
    "tutorial_done", "created_at", "updated_at",
]

CHALLENGE_COLUMNS = [
    "challenge_id", "title", "class_code", "codes", "turns", "seed",
    "note", "created_at",
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
    predictions    TEXT NOT NULL DEFAULT '',
    tutorial_done  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'playing',
    challenge_id   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_class ON runs (class_code);
CREATE INDEX IF NOT EXISTS runs_challenge ON runs (challenge_id);
CREATE TABLE IF NOT EXISTS challenges (
    challenge_id TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    class_code   TEXT NOT NULL DEFAULT '',
    codes        TEXT NOT NULL,
    turns        INTEGER NOT NULL,
    seed         INTEGER NOT NULL,
    note         TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS challenges_class ON challenges (class_code);
"""

#: Rows written before :mod:`dashboard.challenges` existed have no
#: ``challenge_id`` column at all; ``CREATE TABLE IF NOT EXISTS`` cannot add one,
#: so the old file is patched instead of asking the teacher to re-import.
_MIGRATIONS = (
    ("runs", "challenge_id", "TEXT NOT NULL DEFAULT ''"),
    ("runs", "predictions", "TEXT NOT NULL DEFAULT ''"),
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """Open the store, creating ``archive/`` and the schema on first use."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    _migrate(connection)
    return connection


def _migrate(connection: sqlite3.Connection) -> None:
    """Add columns that a database written by an earlier version does not have."""
    for table, column, ddl in _MIGRATIONS:
        # Table names come from _MIGRATIONS, never from user input.
        have = {row["name"] for row in connection.execute(
            "PRAGMA table_info({})".format(table))}
        if column not in have:
            connection.execute(
                "ALTER TABLE {} ADD COLUMN {} {}".format(table, column, ddl))


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
    challenge_id: str = "",
) -> None:
    """Register a run so it can be reloaded before any decision exists."""
    with connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO runs (join_code, class_code, challenge_id,"
            " created_at, updated_at, engine_version, opponent_count, turns,"
            " seed, actions, tutorial_done, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, 'playing')",
            (join_code, class_code.strip(), normalize_code(challenge_id),
             _now(), _now(), engine_version,
             opponent_count, turns, seed, int(bool(tutorial_done))),
        )


def save_progress(
    join_code: str, *, actions: list[str], tutorial_done: bool,
    status: str = "playing", predictions: list[str] | None = None,
) -> None:
    """Write the player's decisions so far. Idempotent and cheap.

    ``actions`` is one string per match in match order, the last one possibly
    shorter than ``turns`` while a match is still in progress.

    ``predictions`` is the same shape, one character per turn of the matching
    entry in ``actions``: the guess the player made for that turn, or ``-`` where
    they skipped it. It is optional to play, so it is written only when given --
    a run that never guessed keeps an empty field rather than a wall of dashes.
    """
    statement = (
        "UPDATE runs SET actions = ?, tutorial_done = ?, status = ?, updated_at = ?"
        + (", predictions = ?" if predictions is not None else "")
        + " WHERE join_code = ?"
    )
    values = [
        ".".join(actions), int(bool(tutorial_done)), status, _now(),
    ]
    if predictions is not None:
        values.append(".".join(predictions))
    values.append(join_code)
    with connect() as connection:
        connection.execute(statement, values)


def load_run(join_code: str) -> dict | None:
    """One stored run by code, or ``None`` if the code is unknown."""
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM runs WHERE join_code = ?", (normalize_code(join_code),)
        ).fetchone()
    return _as_run(row) if row else None


def _as_run(row: sqlite3.Row) -> dict:
    stored = row["predictions"] if "predictions" in row.keys() else ""
    return {
        "join_code": row["join_code"],
        "class_code": row["class_code"],
        "challenge_id": row["challenge_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "engine_version": row["engine_version"],
        "count": row["opponent_count"],
        "turns": row["turns"],
        "seed": row["seed"],
        "actions": [part for part in row["actions"].split(".") if part],
        # Split rather than filtered: the strings are positional against
        # ``actions``, so a match with no guesses still occupies its slot.
        "predictions": stored.split(".") if stored else [],
        "tutorial_done": bool(row["tutorial_done"]),
        "status": row["status"],
    }


def list_runs(class_code: str | None = None,
              challenge_id: str | None = None) -> list[dict]:
    """Every stored run, newest first; the two filters narrow it to one class.

    Only runs under one ``challenge_id`` are ever ranked together: a submission
    against a different opponent set is a different question, and putting the two
    in one list would rank people by luck of the draw.
    """
    query = "SELECT * FROM runs WHERE 1 = 1"
    args: list[str] = []
    if class_code:
        query += " AND class_code = ?"
        args.append(class_code.strip())
    if challenge_id:
        query += " AND challenge_id = ?"
        args.append(normalize_code(challenge_id))
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
                "INSERT OR REPLACE INTO runs (join_code, class_code, challenge_id,"
                " created_at, updated_at, engine_version, opponent_count, turns,"
                " seed, actions, predictions, tutorial_done, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    (record.get("class_code") or "").strip(),
                    normalize_code(record.get("challenge_id") or ""),
                    record.get("created_at") or _now(),
                    record.get("updated_at") or _now(),
                    record.get("engine_version") or "",
                    int(record.get("opponent_count") or 0),
                    int(record.get("turns") or 0),
                    int(record.get("seed") or 0),
                    (record.get("actions") or "").strip(),
                    (record.get("predictions") or "").strip(),
                    int(record.get("tutorial_done") == "1"),
                    record.get("status") or "playing",
                ),
            )
            inserted += 1
    return inserted


# --- Challenges -----------------------------------------------------------
#
# A challenge is the fixed part of a comparison: the same opponent encodings,
# the same number of turns, the same seed. Only runs sharing a ``challenge_id``
# may be ranked against each other, because a score against a different set of
# opponents answers a different question.


def _as_challenge(row: sqlite3.Row) -> dict:
    return {
        "challenge_id": row["challenge_id"],
        "title": row["title"],
        "class_code": row["class_code"],
        "codes": [part for part in row["codes"].split(",") if part],
        "turns": row["turns"],
        "seed": row["seed"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def create_challenge(challenge: dict) -> None:
    """Save a teacher-built challenge."""
    with connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO challenges (challenge_id, title, class_code,"
            " codes, turns, seed, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                normalize_code(challenge["challenge_id"]),
                challenge["title"].strip()[:40],
                (challenge.get("class_code") or "").strip()[:24],
                ",".join(challenge["codes"]),
                int(challenge["turns"]),
                int(challenge["seed"]),
                (challenge.get("note") or "").strip()[:120],
                challenge.get("created_at") or _now(),
            ),
        )


def load_challenge(challenge_id: str) -> dict | None:
    """One saved challenge, or ``None`` (presets are resolved in
    :mod:`dashboard.challenges`, not here)."""
    code = normalize_code(challenge_id)
    if not code:
        return None
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM challenges WHERE challenge_id = ?", (code,)
        ).fetchone()
    return _as_challenge(row) if row else None


def list_challenges(class_code: str | None = None) -> list[dict]:
    """Teacher-built challenges, newest first; ``class_code`` filters to one class."""
    query = "SELECT * FROM challenges"
    args: list[str] = []
    if class_code:
        query += " WHERE class_code = ?"
        args.append(class_code.strip())
    query += " ORDER BY created_at DESC"
    with connect() as connection:
        return [_as_challenge(row) for row in connection.execute(query, args)]


def export_challenges_csv() -> bytes:
    """Teacher challenges as CSV -- the other half of a pre-redeploy backup.

    A restored roster whose challenge rows are missing would leave submissions
    pointing at an unknown ``challenge_id``, so the two files belong together.
    """
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CHALLENGE_COLUMNS)
    writer.writeheader()
    with connect() as connection:
        for row in connection.execute(
                "SELECT * FROM challenges ORDER BY created_at"):
            writer.writerow({name: dict(row)[name] for name in CHALLENGE_COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")


def import_challenges_csv(data: bytes) -> int:
    """Restore challenge rows exported by :func:`export_challenges_csv`."""
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or "challenge_id" not in reader.fieldnames:
        raise ValueError("这份 CSV 缺少 challenge_id 列，不像是本站导出的挑战表。")
    count = 0
    with connect() as connection:
        for record in reader:
            code = normalize_code(record.get("challenge_id") or "")
            codes = [part.strip() for part in (record.get("codes") or "").split(",")
                     if part.strip()]
            if not code or not codes:
                continue
            connection.execute(
                "INSERT OR REPLACE INTO challenges (challenge_id, title,"
                " class_code, codes, turns, seed, note, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    (record.get("title") or code)[:40],
                    (record.get("class_code") or "").strip()[:24],
                    ",".join(codes),
                    int(record.get("turns") or 8),
                    int(record.get("seed") or 0),
                    (record.get("note") or "").strip()[:120],
                    record.get("created_at") or _now(),
                ),
            )
            count += 1
    return count
