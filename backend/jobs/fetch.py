"""Resumable streaming downloads from data.commoncrawl.org, plus peak-memory reporting.

Common Crawl's S3 front end answers bursts with ``503 SlowDown``; downloads back off
exponentially and resume from the bytes already on disk via HTTP Range requests.
"""

from __future__ import annotations

import gzip
import io
import logging
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

USER_AGENT = "LinkflowLab/0.1 (research; link-analysis demo)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
CHUNK = 1 << 20


def _request(url: str, method: str = "GET", start: int = 0, end: int | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if start or end is not None:
        headers["Range"] = f"bytes={start}-{'' if end is None else end}"
    return urllib.request.Request(url, method=method, headers=headers)


def _backoff(attempt: int) -> float:
    return min(300.0, 5.0 * 2**attempt)


def remote_size(url: str, retries: int = 8) -> int:
    """Content-Length of ``url`` via HEAD, retrying on throttling and network errors."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(_request(url, "HEAD"), timeout=60) as resp:
                return int(resp.headers["Content-Length"])
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS:
                raise
            log.warning("HEAD %s -> HTTP %s, retrying in %.0fs", url, exc.code, _backoff(attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            log.warning("HEAD %s failed (%s), retrying in %.0fs", url, exc, _backoff(attempt))
        time.sleep(_backoff(attempt))
    raise RuntimeError(f"could not reach {url} after {retries} attempts")


class _Progress:
    """Thread-safe byte counter that logs every 5%."""

    def __init__(self, name: str, total: int, done: int) -> None:
        self.name, self.total, self.done = name, total, done
        self.next_report = (done / total // 0.05 + 1) * 0.05
        self.lock = threading.Lock()

    def add(self, n: int) -> None:
        with self.lock:
            self.done += n
            if self.done / self.total >= self.next_report:
                log.info("%s: %.0f%% (%s / %s bytes)", self.name, 100 * self.done / self.total, f"{self.done:,}", f"{self.total:,}")
                self.next_report += 0.05


def _fetch_range(url: str, part: Path, start: int, end: int, progress: _Progress, retries: int) -> None:
    """Download bytes [start, end] of ``url`` into ``part``, resuming from its current size."""
    attempt = 0
    while True:
        have = part.stat().st_size if part.exists() else 0
        if start + have > end:
            return
        try:
            with urllib.request.urlopen(_request(url, start=start + have, end=end), timeout=120) as resp:
                if resp.status != 206:
                    raise RuntimeError(f"server ignored Range request (HTTP {resp.status})")
                with part.open("ab") as out:
                    while chunk := resp.read(CHUNK):
                        out.write(chunk)
                        progress.add(len(chunk))
            attempt = 0
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt >= retries:
                raise
            log.warning("%s: HTTP %s; retrying in %.0fs", part.name, exc.code, _backoff(attempt))
            time.sleep(_backoff(attempt))
            attempt += 1
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt >= retries:
                raise
            log.warning("%s: interrupted (%s); retrying in %.0fs", part.name, exc, _backoff(attempt))
            time.sleep(_backoff(attempt))
            attempt += 1


def download(url: str, dest: Path, connections: int = 4, retries: int = 20) -> Path:
    """Download ``url`` to ``dest`` with parallel HTTP Range segments, resuming partial work.

    Common Crawl throttles individual long-lived connections, so the missing byte range is
    split into ``connections`` segments fetched concurrently into ``<dest>.parts/``; they are
    appended to ``dest`` in order when all are complete. Bytes already in ``dest`` (for example
    from an interrupted single-stream download) are kept. Raises if the final size differs
    from Content-Length.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = remote_size(url)
    have = dest.stat().st_size if dest.exists() else 0
    if have == total:
        log.info("%s already complete (%s bytes)", dest.name, f"{total:,}")
        return dest
    if have > total:
        log.warning("%s is larger than the remote file; restarting", dest.name)
        dest.unlink()
        have = 0

    parts_dir = dest.with_name(dest.name + ".parts")
    parts_dir.mkdir(exist_ok=True)
    plan_file = parts_dir / "plan.txt"
    if plan_file.exists():
        bounds = [tuple(map(int, line.split())) for line in plan_file.read_text().split("\n") if line]
    else:
        edges = [have + (total - have) * i // connections for i in range(connections + 1)]
        bounds = [(edges[i], edges[i + 1] - 1) for i in range(connections) if edges[i + 1] > edges[i]]
        plan_file.write_text("\n".join(f"{a} {b}" for a, b in bounds) + "\n")
    if bounds[0][0] != have:
        raise RuntimeError(f"{parts_dir} was planned from byte {bounds[0][0]:,} but {dest.name} has {have:,}")

    parts = [parts_dir / f"part{i:03d}" for i in range(len(bounds))]
    done = have + sum(p.stat().st_size for p in parts if p.exists())
    progress = _Progress(dest.name, total, done)
    log.info("%s: fetching %s bytes in %d parallel segments", dest.name, f"{total - done:,}", len(bounds))
    with ThreadPoolExecutor(max_workers=len(bounds)) as pool:
        futures = [pool.submit(_fetch_range, url, p, a, b, progress, retries) for p, (a, b) in zip(parts, bounds)]
        for f in futures:
            f.result()

    with dest.open("ab") as out:
        for p, (a, b) in zip(parts, bounds):
            if p.stat().st_size != b - a + 1:
                raise RuntimeError(f"{p.name}: has {p.stat().st_size:,} bytes, expected {b - a + 1:,}")
            with p.open("rb") as src:
                shutil.copyfileobj(src, out, CHUNK)
    final = dest.stat().st_size
    if final != total:
        raise RuntimeError(f"{dest.name}: got {final:,} bytes, expected {total:,}")
    shutil.rmtree(parts_dir)
    return dest


def head_lines(url: str, n_lines: int = 21, n_bytes: int = 4 << 20) -> list[str]:
    """First lines of a remote gzipped text file, reading only its first ``n_bytes``.

    Retries throttling (503 Slow Down) and timeouts with the same backoff as the downloader.
    """
    for attempt in range(8):
        try:
            with urllib.request.urlopen(_request(url, end=n_bytes - 1), timeout=120) as resp:
                prefix = resp.read()
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == 7:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 7:
                raise
            log.warning("head of %s failed (%s)", url, exc)
        time.sleep(_backoff(attempt))
    lines: list[str] = []
    with gzip.GzipFile(fileobj=io.BytesIO(prefix)) as gz:
        reader = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        try:
            for line in reader:
                lines.append(line.rstrip("\n"))
                if len(lines) >= n_lines:
                    break
        except EOFError:
            pass  # the prefix ends mid-stream; we only need the first lines
    return lines


def keep_system_awake() -> None:
    """Ask Windows not to idle-sleep while this process runs (released when it exits).

    Uses SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED), the same per-process
    request media players make; it changes no settings and lets the display turn off.
    A closed lid or a manual Sleep still sleeps. No-op on other systems.
    """
    if sys.platform == "win32":
        import ctypes

        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def bytes_on_disk(dest: Path) -> int:
    """Bytes downloaded so far for ``dest``: the file itself plus any parallel segments."""
    total = dest.stat().st_size if dest.exists() else 0
    parts = dest.with_name(dest.name + ".parts")
    if parts.is_dir():
        total += sum(p.stat().st_size for p in parts.glob("part*"))
    return total


def peak_rss_bytes() -> int:
    """Peak resident memory of this process (working set on Windows)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_info(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return int(counters.PeakWorkingSetSize)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def main() -> None:
    """``python -m backend.jobs.fetch <url> <dest>``: one resumable download (used by supervisors)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    keep_system_awake()
    download(sys.argv[1], Path(sys.argv[2]))


if __name__ == "__main__":
    main()
