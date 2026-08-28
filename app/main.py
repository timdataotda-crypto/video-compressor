from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drone Compressor — batch compress videos to a target size"
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in CLI mode instead of GUI",
    )
    parser.add_argument("source", nargs="?", help="Source folder")
    parser.add_argument("output", nargs="?", help="Output folder")
    parser.add_argument(
        "--target",
        type=float,
        default=None,
        help="Target size in MB (default from config)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers",
    )
    args = parser.parse_args()

    if args.cli or (args.source and args.output):
        from app.cli import run_cli

        if not args.source or not args.output:
            parser.error("CLI mode requires source and output paths")
        return run_cli(
            source=Path(args.source),
            output=Path(args.output),
            target_mb=args.target,
            workers=args.workers,
        )

    from app.ui.main_window import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
