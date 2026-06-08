"""이미 알림 보낸 공고 기록 (중복 알림 방지). GitHub Actions가 repo에 커밋해 유지."""
from __future__ import annotations

import json
from pathlib import Path


def load_seen(path: Path) -> set[str]:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)
