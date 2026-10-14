"""Run the Phase 2 jobs in order once their inputs and enough memory are available.

    python -m backend.jobs.phase2_pipeline [--top 1000000]

1. Wait until both graph files are fully downloaded (download_graph runs separately).
2. Before each heavy step, wait until the machine has at least MIN_FREE_RAM_GB of free RAM and
   MIN_FREE_COMMIT_GB of commit headroom. It never forces a start on a starved machine.
3. Run build_subgraph, then compute_all, each as a child process with its own log
   (data/build_subgraph.log, data/compute_all.log). Stop at the first failure.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time

from backend import config

from .fetch import keep_system_awake, remote_size

log = logging.getLogger("phase2_pipeline")

MIN_FREE_RAM_GB = 3.0
MIN_FREE_COMMIT_GB = 5.0
POLL_SECONDS = 60


def free_memory_gb() -> tuple[float, float]:
    """(free physical RAM, free commit) in GB; (inf, inf) where it cannot be measured."""
    if sys.platform != "win32":
        return float("inf"), float("inf")
    import ctypes
    from ctypes import wintypes

    class Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    s = Status()
    s.dwLength = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
    return s.ullAvailPhys / 1e9, s.ullAvailPageFile / 1e9


def wait_for_downloads(release: str) -> None:
    for name in ("domain-vertices.txt.gz", "domain-edges.txt.gz"):
        filename = f"{release}-{name}"
        path = config.RAW_DIR / filename
        total = remote_size(config.domain_url(release, filename))
        while not (path.exists() and path.stat().st_size == total):
            time.sleep(POLL_SECONDS)
        log.info("%s is complete", filename)


def wait_for_memory(step: str) -> None:
    announced = 0.0
    while True:
        ram, commit = free_memory_gb()
        if ram >= MIN_FREE_RAM_GB and commit >= MIN_FREE_COMMIT_GB:
            log.info("%s: %.1f GB RAM and %.1f GB commit free; starting", step, ram, commit)
            return
        if time.monotonic() - announced > 300:
            log.warning("%s waits for memory: %.1f GB RAM free (need %.0f), %.1f GB commit free (need %.0f)",
                        step, ram, MIN_FREE_RAM_GB, commit, MIN_FREE_COMMIT_GB)
            announced = time.monotonic()
        time.sleep(POLL_SECONDS)


def run_step(step: str, args: list[str]) -> None:
    wait_for_memory(step)
    log_path = config.DATA_DIR / f"{step}.log"
    with log_path.open("a", encoding="utf-8") as out:
        code = subprocess.call([sys.executable, "-u", "-m", f"backend.jobs.{step}", *args], stdout=out, stderr=subprocess.STDOUT)
    if code != 0:
        log.error("%s failed with exit code %d; see %s. Stopping the pipeline.", step, code, log_path.name)
        raise SystemExit(code)
    log.info("%s finished", step)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=1_000_000)
    parser.add_argument("--release", default=config.RELEASE)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    wait_for_downloads(args.release)
    run_step("build_subgraph", ["--top", str(args.top), "--release", args.release])
    run_step("compute_all", ["--top", str(args.top), "--release", args.release])
    log.info("Phase 2 pipeline complete")


if __name__ == "__main__":
    main()
