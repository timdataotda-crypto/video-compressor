from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from app.core.bitrate import bytes_to_mb
from app.models.job import Job, JobStatus


class JobTable(QTableWidget):
    COLUMNS = ("File", "Paket", "Status", "Progress", "Original", "Output", "Error")

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.COLUMNS), parent)
        self.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.setAlternatingRowColors(True)
        self._row_by_id: dict[int, int] = {}

    def load_jobs(self, jobs: list[Job]) -> None:
        self.setRowCount(0)
        self._row_by_id.clear()
        for job in jobs:
            self.upsert_job(job)

    def upsert_job(self, job: Job) -> None:
        row = self._row_by_id.get(job.id) if job.id is not None else None
        if row is None:
            row = self.rowCount()
            self.insertRow(row)
            if job.id is not None:
                self._row_by_id[job.id] = row

        paket = job.geopas_paket_nama or (
            f"#{job.geopas_paket_id}" if job.geopas_paket_id else "—"
        )
        values = [
            Path(job.source_path).name,
            paket,
            job.status.value,
            f"{job.progress:.0f}%",
            f"{bytes_to_mb(job.original_size):.1f} MB" if job.original_size else "—",
            f"{bytes_to_mb(job.output_size):.1f} MB" if job.output_size else "—",
            job.error or "",
        ]
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            if col in (3, 4, 5):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if job.status == JobStatus.FAILED:
                item.setForeground(Qt.GlobalColor.red)
            elif job.status == JobStatus.COMPLETED:
                item.setForeground(Qt.GlobalColor.green)
            elif job.status == JobStatus.UPLOADING:
                item.setForeground(Qt.GlobalColor.cyan)
            elif job.status == JobStatus.UPLOAD_FAILED:
                item.setForeground(Qt.GlobalColor.red)
            self.setItem(row, col, item)
