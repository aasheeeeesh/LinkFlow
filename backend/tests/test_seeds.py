"""Shape of the shipped seed lists (membership in the graph is checked by backend.tools.check_seeds)."""

from __future__ import annotations

import pytest

from backend.domains import normalize_query
from backend.seeds import TOPICS, parse_seed_text, topic_seeds, trusted_seeds


def test_trusted_list_has_200_unique_normalised_domains() -> None:
    seeds = trusted_seeds()
    assert len(seeds) == 200
    assert all(normalize_query(d) == d for d in seeds)


@pytest.mark.parametrize("topic", TOPICS)
def test_topic_lists_have_50_unique_normalised_domains(topic: str) -> None:
    seeds = topic_seeds()[topic]
    assert len(seeds) == 50
    assert all(normalize_query(d) == d for d in seeds)


def test_eight_topics() -> None:
    assert set(topic_seeds()) == {"science", "health", "technology", "finance", "news", "education", "government", "sport"}


def test_parse_seed_text_ignores_comments_blanks_and_duplicates() -> None:
    assert parse_seed_text("# header\nA.com\n\nb.org  # note\na.com\n") == ["a.com", "b.org"]
