from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    COMPRESSING = "COMPRESSING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


@dataclass
class Job:
    id: Optional[int] = None
    source_path: str = ""
    output_path: str = ""
    duration: float = 0.0
    original_size: int = 0
    output_size: int = 0
    video_bitrate: int = 0
    resolution: str = ""
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    attempt: int = 0
    error: str = ""
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def mark_started(self) -> None:
        self.started_at = datetime.now().isoformat(timespec="seconds")

    def mark_completed(self) -> None:
        self.completed_at = datetime.now().isoformat(timespec="seconds")
        self.progress = 100.0
        self.status = JobStatus.COMPLETED

    @property
    def reduction_percent(self) -> float:
        if self.original_size <= 0 or self.output_size <= 0:
            return 0.0
        return (1 - self.output_size / self.original_size) * 100
