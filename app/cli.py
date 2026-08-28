from __future__ import annotations

from pathlib import Path

from app.core.job_manager import JobManager
from app.utils.deps import check_ffmpeg_deps
from app.utils.logger import setup_logging
from app.utils.paths import load_config


def run_cli(
    source: Path,
    output: Path,
    target_mb: float | None = None,
    workers: int | None = None,
) -> int:
    setup_logging()

    deps = check_ffmpeg_deps()
    if not deps.ok:
        print(deps.message)
        return 2
    print(deps.ffmpeg_version)

    config = load_config()
    if target_mb is not None:
        config["target_size_mb"] = target_mb
    if workers is not None:
        config["workers"] = workers

    manager = JobManager(config=config)
    print(f"Scanning: {source}")
    jobs = manager.scan_and_create_jobs(source, output)
    summary = manager.get_summary()
    print(
        f"Found {summary['total']} videos "
        f"(skip={summary['skipped']}, pending={summary['pending']})"
    )

    warnings = manager.collect_target_warnings(jobs)
    for w in warnings[:10]:
        print(f"WARNING: {w}")
    if len(warnings) > 10:
        print(f"WARNING: …dan {len(warnings) - 10} peringatan lain")

    ok, free, needed = manager.check_disk_space(output, summary["pending"])
    if not ok:
        print(
            f"WARNING: free disk ~{free:.1f} GB, estimated need ~{needed:.1f} GB"
        )

    def on_update(job) -> None:
        name = Path(job.source_path).name
        print(
            f"[{job.status.value}] {name} "
            f"{job.progress:.0f}% "
            f"{'(err: ' + job.error + ')' if job.error else ''}"
        )

    manager.run_batch(jobs=jobs, on_job_update=on_update)
    final = manager.get_summary()
    print(
        f"Done. total={final['total']} completed={final['done']} "
        f"failed={final['failed']} skipped={final['skipped']}"
    )
    return 0 if final["failed"] == 0 else 1
