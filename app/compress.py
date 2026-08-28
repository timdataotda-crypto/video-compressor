"""CLI entry: python -m app.compress /source /output"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.cli import run_cli


def main() -> int:
    parser = argparse.ArgumentParser(description="Drone Compressor CLI")
    parser.add_argument("source", type=Path, help="Source folder")
    parser.add_argument("output", type=Path, help="Output folder")
    parser.add_argument("--target", type=float, default=None, help="Target size MB")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    return run_cli(args.source, args.output, args.target, args.workers)


if __name__ == "__main__":
    sys.exit(main())
