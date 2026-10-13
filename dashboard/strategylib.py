"""Strategy library: persist reusable strategy encodings.

Strategies saved here can be recalled in the "自定义" initial population setup
and in the manual injection panel.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

LIB_FILE = Path(__file__).resolve().parents[1] / "saved_strategies.json"


def load_strategies() -> list[dict]:
    if not LIB_FILE.is_file():
        return []
    try:
        data = json.loads(LIB_FILE.read_text(encoding="utf-8"))
        return data.get("strategies", [])
    except Exception:  # noqa: BLE001 - return empty on corrupt file
        return []


def save_strategy(encoding: str, name: str = "") -> bool:
    """Add a strategy to the library. Returns False if it already exists."""
    library = load_strategies()
    if any(item["encoding"] == encoding for item in library):
        return False
    library.append(
        {
            "encoding": encoding,
            "name": name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    LIB_FILE.write_text(
        json.dumps({"strategies": library}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def delete_strategy(encoding: str) -> None:
    library = [item for item in load_strategies() if item["encoding"] != encoding]
    LIB_FILE.write_text(
        json.dumps({"strategies": library}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )