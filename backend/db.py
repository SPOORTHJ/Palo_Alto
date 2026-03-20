import json
from pathlib import Path
from typing import List
from models import SafetyCard

DB_PATH = Path("data/digest.json")


def _ensure_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        DB_PATH.write_text("[]")


def load_all() -> List[SafetyCard]:
    _ensure_db()
    raw = json.loads(DB_PATH.read_text())
    return [SafetyCard(**item) for item in raw]


def save_card(card: SafetyCard) -> None:
    _ensure_db()
    cards = load_all()
    cards.append(card)
    cards = cards[-100:]          # cap storage at 100 entries
    DB_PATH.write_text(json.dumps([c.model_dump() for c in cards], indent=2))


def clear_all() -> int:
    _ensure_db()
    count = len(load_all())
    DB_PATH.write_text("[]")
    return count
