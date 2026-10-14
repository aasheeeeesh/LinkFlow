"""Print the header and first lines of a remote gzipped Common Crawl file.

Reads only the first few MB, so it is safe to run on multi-GB files before writing a parser.

    python -m backend.jobs.inspect_file <url> [--lines 21] [--megabytes 4]
"""

from __future__ import annotations

import argparse

from .fetch import head_lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--lines", type=int, default=21, help="lines to print (header + 20 rows)")
    parser.add_argument("--megabytes", type=int, default=4, help="bytes of the file to fetch, in MiB")
    args = parser.parse_args()
    for line in head_lines(args.url, n_lines=args.lines, n_bytes=args.megabytes << 20):
        print(line.replace("\t", " <TAB> "))


if __name__ == "__main__":
    main()
