"""Download the domain vertex and edge files with a stall watchdog.

    python -m backend.jobs.download_graph [--release ...] [--stall-minutes 10]

Each file is fetched by a child process (``python -m backend.jobs.fetch``). The supervisor
watches the bytes on disk; if they stop growing for ``--stall-minutes`` (for example a
connection or DNS lookup that hangs after the computer wakes from sleep), it kills the child
and starts a new one, which resumes from the bytes already downloaded.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

from backend import config

from .fetch import bytes_on_disk, keep_system_awake, remote_size

log = logging.getLogger("download_graph")

GRAPH_FILES = ("domain-vertices.txt.gz", "domain-edges.txt.gz")
POLL_SECONDS = 30
MAX_ATTEMPTS = 50


def supervise(url: str, dest: Path, stall_seconds: float) -> None:
    """Run the resumable download in a child process, restarting it whenever it stalls or fails."""
    total = remote_size(url)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if dest.exists() and dest.stat().st_size == total:
            log.info("%s complete (%s bytes)", dest.name, f"{total:,}")
            return
        log.info("%s: attempt %d, %s of %s bytes on disk", dest.name, attempt, f"{bytes_on_disk(dest):,}", f"{total:,}")
        child = subprocess.Popen([sys.executable, "-m", "backend.jobs.fetch", url, str(dest)])
        last_size, last_change = bytes_on_disk(dest), time.monotonic()
        while child.poll() is None:
            time.sleep(POLL_SECONDS)
            size = bytes_on_disk(dest)
            if size != last_size:
                last_size, last_change = size, time.monotonic()
            elif time.monotonic() - last_change > stall_seconds:
                log.warning("%s: no progress for %.0f min; restarting the download", dest.name, stall_seconds / 60)
                child.kill()
                child.wait()
                break
        if child.returncode == 0 and dest.exists() and dest.stat().st_size == total:
            log.info("%s complete (%s bytes)", dest.name, f"{total:,}")
            return
        time.sleep(min(300, 10 * attempt))
    raise RuntimeError(f"{dest.name}: gave up after {MAX_ATTEMPTS} attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", default=config.RELEASE)
    parser.add_argument("--stall-minutes", type=float, default=10)
    parser.add_argument("--history", action="store_true",
                        help="download the rank files of config.HISTORY_RELEASES instead of the graph files")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    if args.history:
        for release in config.HISTORY_RELEASES:
            filename = config.ranks_filename(release)
            supervise(config.domain_url(release, filename), config.RAW_DIR / filename, args.stall_minutes * 60)
        log.info("all history rank files downloaded")
        return
    for name in GRAPH_FILES:
        filename = f"{args.release}-{name}"
        supervise(config.domain_url(args.release, filename), config.RAW_DIR / filename, args.stall_minutes * 60)
    log.info("all graph files downloaded")


if __name__ == "__main__":
    main()
