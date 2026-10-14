"""Domain-name handling: Common Crawl's reversed notation and user-query normalisation."""

from __future__ import annotations

import re
from collections.abc import Sequence

_VALID = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")


def flip(name: str) -> str:
    """Reverse the dot-separated labels: ``com.example`` <-> ``example.com``."""
    return ".".join(reversed(name.split(".")))


_COMMON_TLDS = frozenset(
    "com org net edu gov mil int info biz xyz top online site app dev io co ai me tv us uk de jp fr "
    "ru br it nl pl au in cn es ca ch se no fi dk be at cz eu ir kr gr pt hu ro ua tr mx ar za nz "
    "sk vn id tw hk sg my il cl be by kz lt lv ee si hr rs bg".split()
)


def detect_reversed(keys: Sequence[str]) -> bool:
    """Decide whether a sample of domain keys is in reversed notation (``com.example``).

    Primary signal: whether common TLDs appear more often as the first label or as the
    last label. Tie-breaker: in normal notation last labels repeat heavily and first labels
    are diverse, and the other way round when reversed.
    """
    multi = [k for k in keys if "." in k]
    if not multi:
        raise ValueError("cannot detect notation: no multi-label names in sample")
    first_labels = [k.split(".", 1)[0] for k in multi]
    last_labels = [k.rsplit(".", 1)[1] for k in multi]
    first_tld = sum(label in _COMMON_TLDS for label in first_labels)
    last_tld = sum(label in _COMMON_TLDS for label in last_labels)
    if first_tld != last_tld:
        return first_tld > last_tld
    return len(set(first_labels)) < len(set(last_labels))


class InvalidDomain(ValueError):
    """Raised when a user query cannot be turned into a domain name."""


def normalize_query(raw: str) -> str:
    """Turn user input (a domain, host or URL) into a lowercase ASCII domain name.

    Strips scheme, credentials, port, path, query, fragment and trailing dot, and converts
    internationalised names to punycode (``bücher.de`` -> ``xn--bcher-kva.de``).
    """
    s = raw.strip().lower()
    s = _SCHEME.sub("", s)
    s = re.split(r"[/?#]", s, maxsplit=1)[0]
    s = s.rsplit("@", 1)[-1]
    s = s.split(":", 1)[0]
    s = s.strip(".")
    if not s:
        raise InvalidDomain("Enter a domain name such as example.com")
    try:
        s = ".".join(label.encode("idna").decode("ascii") if not label.isascii() else label for label in s.split("."))
    except UnicodeError as exc:
        raise InvalidDomain(f"'{raw.strip()}' is not a valid domain name") from exc
    if len(s) > 253 or not _VALID.match(s):
        raise InvalidDomain(f"'{raw.strip()}' is not a valid domain name")
    return s


def lookup_candidates(domain: str) -> list[str]:
    """Names to try for a query, most specific first: the name itself, then without ``www.``."""
    candidates = [domain]
    if domain.startswith("www.") and domain.count(".") >= 2:
        candidates.append(domain[4:])
    return candidates


def parent_domains(domain: str) -> list[str]:
    """Parent names with at least two labels: ``a.b.example.co.uk`` -> ``b.example.co.uk``, ...

    Used to suggest the registered domain when a host name was entered; Common Crawl's
    domain graph aggregates hosts to registered domains.
    """
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(1, len(labels) - 1)]
