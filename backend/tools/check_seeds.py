"""Check that every seed domain exists in the loaded Common Crawl domain graph.

    python -m backend.tools.check_seeds

Prints, per list, how many seeds were found and the rank of each missing or weak one.
Exits with status 1 if any seed is missing.
"""

from __future__ import annotations

import sys

import duckdb

from backend import config
from backend.seeds import topic_seeds, trusted_seeds


def main() -> int:
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    lists = {"trusted": trusted_seeds(), **topic_seeds()}
    all_domains = sorted({d for seeds in lists.values() for d in seeds})
    placeholders = ", ".join("?" for _ in all_domains)
    rows = con.execute(
        f"SELECT domain, hc_rank, pr_rank FROM domain_ranks WHERE release = ? AND domain IN ({placeholders})",
        [config.RELEASE, *all_domains],
    ).fetchall()
    found = {d: (hc, pr) for d, hc, pr in rows}
    missing_any = False
    for name, seeds in lists.items():
        missing = [d for d in seeds if d not in found]
        worst = sorted((found[d][0], d) for d in seeds if d in found)[-3:]
        print(f"{name:11s} {len(seeds) - len(missing):3d}/{len(seeds)} found; lowest harmonic ranks: "
              + ", ".join(f"{d} #{hc:,}" for hc, d in reversed(worst)))
        for d in missing:
            print(f"    MISSING: {d}")
        missing_any |= bool(missing)
    return 1 if missing_any else 0


if __name__ == "__main__":
    sys.exit(main())
