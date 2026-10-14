"""Seed lists: the default trusted list and the topic lists for topic-sensitive PageRank."""

from __future__ import annotations

from pathlib import Path

SEEDS_DIR = Path(__file__).absolute().parent
TRUSTED_FILE = SEEDS_DIR / "trusted.txt"
TOPICS_DIR = SEEDS_DIR / "topics"
TOPICS = ("science", "health", "technology", "finance", "news", "education", "government", "sport")


def parse_seed_text(text: str) -> list[str]:
    """Domains from a seed list: one per line, blank lines and ``#`` comments ignored, order kept."""
    seen: dict[str, None] = {}
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip().lower()
        if entry:
            seen.setdefault(entry, None)
    return list(seen)


def load_seed_file(path: Path) -> list[str]:
    return parse_seed_text(path.read_text(encoding="utf-8"))


def trusted_seeds() -> list[str]:
    return load_seed_file(TRUSTED_FILE)


def topic_seeds() -> dict[str, list[str]]:
    return {topic: load_seed_file(TOPICS_DIR / f"{topic}.txt") for topic in TOPICS}
