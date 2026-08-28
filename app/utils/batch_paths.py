from __future__ import annotations

from pathlib import Path


def common_path(paths: list[Path]) -> Path | None:
    """Return longest common ancestor directory for a list of paths."""
    if not paths:
        return None
    resolved = [Path(p).resolve() for p in paths]
    try:
        import os

        common_str = os.path.commonpath([str(p) for p in resolved])
        common = Path(common_str)
    except ValueError:
        return None

    if common.is_file():
        return common.parent
    return common


def infer_batch_roots(
    source_paths: list[str],
    output_paths: list[str],
) -> tuple[str, str]:
    """
    Infer source/output folder roots from job paths for resume UI.

    Prefer the common parent of all files. Fall back to parent of first file.
    """
    src_files = [Path(p) for p in source_paths if p]
    out_files = [Path(p) for p in output_paths if p]

    src_root = common_path(src_files)
    out_root = common_path(out_files)

    if src_root is None and src_files:
        src_root = src_files[0].parent
    if out_root is None and out_files:
        out_root = out_files[0].parent

    # If common path is a file's parent that still contains the leaf folder
    # shared by all (e.g. .../DRONE), keep it. If commonpath equals a file
    # somehow, parent already handled above.
    return (
        str(src_root) if src_root else "",
        str(out_root) if out_root else "",
    )
