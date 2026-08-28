from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.bitrate import bytes_to_mb
from app.core.job_manager import JobManager
from app.core.profiles import (
    PROFILES,
    TARGET_PRESETS_MB,
    apply_quality_profile,
    match_target_preset,
    normalize_profile_key,
    profile_key_from_label,
    profile_labels,
)
from app.database.database import Database
from app.models.job import Job, JobStatus
from app.ui.job_table import JobTable
from app.ui.settings_dialog import SettingsDialog
from app.utils.batch_paths import infer_batch_roots
from app.utils.deps import check_ffmpeg_deps
from app.utils.logger import setup_logging
from app.utils.paths import get_project_root, load_config, save_config


class Worker(QObject):
    job_updated = Signal(object)
    status = Signal(str)
    finished = Signal()

    def __init__(self, manager: JobManager, jobs: list[Job]) -> None:
        super().__init__()
        self.manager = manager
        self.jobs = jobs

    @Slot()
    def run(self) -> None:
        self.manager.run_batch(
            jobs=self.jobs,
            on_job_update=lambda job: self.job_updated.emit(job),
            on_status=lambda msg: self.status.emit(msg),
        )
        self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Drone Compressor")
        self.resize(960, 720)
        self.setAcceptDrops(True)

        self.config = load_config()
        self.db = Database()
        self.manager = JobManager(config=self.config, db=self.db)
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._jobs: list[Job] = []

        self._build_ui()
        self._load_styles()
        self._check_dependencies()
        self._maybe_offer_resume()

    def _check_dependencies(self) -> None:
        status = check_ffmpeg_deps()
        if status.ok:
            self.summary_label.setText(status.ffmpeg_version)
            return
        QMessageBox.critical(self, "FFmpeg tidak ditemukan", status.message)
        self.start_btn.setEnabled(False)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(12)
        root.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("DRONE COMPRESSOR")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        header.addStretch()
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        form_box = QGroupBox("Folders & Target")
        form = QFormLayout(form_box)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Folder sumber video…")
        src_row = QHBoxLayout()
        src_row.addWidget(self.source_edit)
        src_btn = QPushButton("📁")
        src_btn.clicked.connect(self.pick_source)
        src_row.addWidget(src_btn)
        form.addRow("SOURCE", src_row)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Folder output…")
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit)
        out_btn = QPushButton("📁")
        out_btn.clicked.connect(self.pick_output)
        out_row.addWidget(out_btn)
        form.addRow("OUTPUT", out_row)

        self.target_preset = QComboBox()
        for mb in TARGET_PRESETS_MB:
            self.target_preset.addItem(f"{mb} MB", mb)
        self.target_preset.addItem("Custom", None)
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(1, 500)
        self.target_spin.setSuffix(" MB")
        self.target_spin.setDecimals(1)
        initial_target = float(self.config.get("target_size_mb", 19))
        self.target_spin.setValue(initial_target)
        self._syncing_target = False
        preset_label = match_target_preset(initial_target)
        idx = self.target_preset.findText(preset_label)
        if idx >= 0:
            self.target_preset.setCurrentIndex(idx)
        self.target_spin.setEnabled(preset_label == "Custom")
        self.target_preset.currentIndexChanged.connect(self._on_target_preset_changed)
        self.target_spin.valueChanged.connect(self._on_target_spin_changed)

        target_row = QHBoxLayout()
        target_row.addWidget(self.target_preset, stretch=2)
        target_row.addWidget(self.target_spin, stretch=1)
        form.addRow("TARGET", target_row)

        self.quality_combo = QComboBox()
        for label in profile_labels():
            self.quality_combo.addItem(label)
        profile_key = normalize_profile_key(self.config.get("quality_profile"))
        self.quality_combo.setCurrentText(PROFILES[profile_key].label)
        self.quality_hint = QLabel(PROFILES[profile_key].description)
        self.quality_hint.setStyleSheet("color: #9aa3b2;")
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        quality_row = QVBoxLayout()
        quality_row.addWidget(self.quality_combo)
        quality_row.addWidget(self.quality_hint)
        form.addRow("QUALITY", quality_row)

        opts = QHBoxLayout()
        self.chk_recursive = QCheckBox("Recursive folders")
        self.chk_recursive.setChecked(bool(self.config.get("recursive", True)))
        self.chk_preserve = QCheckBox("Preserve structure")
        self.chk_preserve.setChecked(bool(self.config.get("preserve_structure", True)))
        self.chk_skip = QCheckBox("Skip existing")
        self.chk_skip.setChecked(bool(self.config.get("skip_existing", True)))
        self.chk_retry = QCheckBox("Auto retry")
        self.chk_retry.setChecked(bool(self.config.get("auto_retry", True)))
        for w in (self.chk_recursive, self.chk_preserve, self.chk_skip, self.chk_retry):
            opts.addWidget(w)
        form.addRow("", opts)
        root.addWidget(form_box)

        actions = QHBoxLayout()
        self.start_btn = QPushButton("START COMPRESSION")
        self.start_btn.setObjectName("startButton")
        self.start_btn.clicked.connect(self.start_compression)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_compression)
        self.retry_btn = QPushButton("Retry Failed")
        self.retry_btn.clicked.connect(self.retry_failed)
        self.open_out_btn = QPushButton("Open Output")
        self.open_out_btn.clicked.connect(self.open_output_folder)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.pause_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.retry_btn)
        actions.addWidget(self.open_out_btn)
        actions.addStretch()
        root.addLayout(actions)
        self._paused = False

        current = QGroupBox("Current Job")
        cur_layout = QVBoxLayout(current)
        self.current_label = QLabel("—")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.stats_label = QLabel("Original: — | Output: — | Reduction: —")
        cur_layout.addWidget(self.current_label)
        cur_layout.addWidget(self.progress)
        cur_layout.addWidget(self.stats_label)
        root.addWidget(current)

        self.job_table = JobTable()
        root.addWidget(self.job_table, stretch=1)

        self.summary_label = QLabel("Total: 0 | Done: 0 | Failed: 0 | Remaining: 0")
        root.addWidget(self.summary_label)

    def _load_styles(self) -> None:
        qss = get_project_root() / "app" / "ui" / "styles.qss"
        if qss.exists():
            self.setStyleSheet(qss.read_text(encoding="utf-8"))

    def _on_target_preset_changed(self, _index: int = 0) -> None:
        if self._syncing_target:
            return
        self._syncing_target = True
        try:
            data = self.target_preset.currentData()
            if data is None:
                self.target_spin.setEnabled(True)
            else:
                self.target_spin.setEnabled(False)
                self.target_spin.setValue(float(data))
        finally:
            self._syncing_target = False

    def _on_target_spin_changed(self, value: float) -> None:
        if self._syncing_target:
            return
        self._syncing_target = True
        try:
            label = match_target_preset(value)
            idx = self.target_preset.findText(label)
            if idx >= 0:
                self.target_preset.setCurrentIndex(idx)
            self.target_spin.setEnabled(label == "Custom")
        finally:
            self._syncing_target = False

    def _on_quality_changed(self, label: str) -> None:
        key = profile_key_from_label(label)
        profile = PROFILES[key]
        self.quality_hint.setText(profile.description)
        self.config = apply_quality_profile(self.config, key)

    def _sync_config_from_ui(self) -> None:
        self.config["target_size_mb"] = self.target_spin.value()
        self.config["recursive"] = self.chk_recursive.isChecked()
        self.config["preserve_structure"] = self.chk_preserve.isChecked()
        self.config["skip_existing"] = self.chk_skip.isChecked()
        self.config["auto_retry"] = self.chk_retry.isChecked()
        self.config = apply_quality_profile(
            self.config, profile_key_from_label(self.quality_combo.currentText())
        )
        self.manager.config = self.config
        save_config(self.config)

    def _maybe_offer_resume(self) -> None:
        self.db.reset_interrupted_jobs()
        incomplete = self.db.count_incomplete()
        if incomplete <= 0:
            return
        reply = QMessageBox.question(
            self,
            "Resume",
            f"Ada {incomplete} job belum selesai. Resume previous job?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            jobs = self.db.list_jobs()
            self._jobs = jobs
            self.job_table.load_jobs(jobs)
            self._refresh_summary()
            if jobs:
                src_root, out_root = infer_batch_roots(
                    [j.source_path for j in jobs],
                    [j.output_path for j in jobs],
                )
                if src_root:
                    self.source_edit.setText(src_root)
                if out_root:
                    self.output_edit.setText(out_root)
        else:
            self.db.clear_jobs()

    def pick_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pilih Source Folder")
        if path:
            self.source_edit.setText(path)
            if not self.output_edit.text():
                self.output_edit.setText(f"{path.rstrip('/')}_COMPRESSED")

    def pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pilih Output Folder")
        if path:
            self.output_edit.setText(path)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self.config = apply_quality_profile(dlg.result_config())
            target = float(self.config["target_size_mb"])
            self._syncing_target = True
            try:
                self.target_spin.setValue(target)
                label = match_target_preset(target)
                idx = self.target_preset.findText(label)
                if idx >= 0:
                    self.target_preset.setCurrentIndex(idx)
                self.target_spin.setEnabled(label == "Custom")
            finally:
                self._syncing_target = False
            key = normalize_profile_key(self.config.get("quality_profile"))
            self.quality_combo.setCurrentText(PROFILES[key].label)
            self.quality_hint.setText(PROFILES[key].description)
            self.chk_retry.setChecked(bool(self.config["auto_retry"]))
            self.manager.config = self.config
            save_config(self.config)

    def open_output_folder(self) -> None:
        out = self.output_edit.text().strip()
        if out and Path(out).exists():
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def start_compression(self) -> None:
        source = Path(self.source_edit.text().strip())
        output = Path(self.output_edit.text().strip())
        if not source.exists():
            QMessageBox.warning(self, "Error", "Source folder tidak valid.")
            return
        if not output:
            QMessageBox.warning(self, "Error", "Output folder wajib diisi.")
            return

        self._sync_config_from_ui()

        # Resume incomplete without rescanning if table already loaded from resume
        resume_jobs = [
            j
            for j in self._jobs
            if j.status
            in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        if resume_jobs and self.db.count_incomplete() > 0:
            jobs = self.db.list_jobs()
        else:
            try:
                jobs = self.manager.scan_and_create_jobs(source, output)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Scan gagal", str(exc))
                return

        self._jobs = jobs
        self.job_table.load_jobs(jobs)
        self._refresh_summary()

        pending = sum(
            1
            for j in jobs
            if j.status
            in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)
        )
        if pending == 0:
            QMessageBox.information(self, "Info", "Tidak ada video yang perlu diproses.")
            return

        warnings = self.manager.collect_target_warnings(jobs)
        if warnings:
            preview = "\n\n".join(warnings[:5])
            extra = (
                f"\n\n…dan {len(warnings) - 5} peringatan lain."
                if len(warnings) > 5
                else ""
            )
            reply = QMessageBox.warning(
                self,
                "Target mungkin tidak realistis",
                f"{preview}{extra}\n\nLanjutkan tetap dengan target ini?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        ok, free, needed = self.manager.check_disk_space(output, pending)
        if not ok:
            reply = QMessageBox.warning(
                self,
                "Disk space",
                f"Free ~{free:.1f} GB, estimasi butuh ~{needed:.1f} GB.\nLanjutkan?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Pause")
        self._paused = False
        self.cancel_btn.setEnabled(True)
        self.retry_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = Worker(self.manager, jobs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.job_updated.connect(self.on_job_updated)
        self._worker.status.connect(self.summary_label.setText)
        self._worker.finished.connect(self.on_batch_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def toggle_pause(self) -> None:
        if not self._paused:
            self.manager.pause()
            self._paused = True
            self.pause_btn.setText("Resume")
            self.summary_label.setText("Paused…")
        else:
            self.manager.resume()
            self._paused = False
            self.pause_btn.setText("Pause")

    def cancel_compression(self) -> None:
        if self._paused:
            self.manager.resume()
            self._paused = False
        self.manager.cancel()
        self.cancel_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)

    def retry_failed(self) -> None:
        failed = [j for j in self.db.list_jobs() if j.status == JobStatus.FAILED]
        if not failed:
            QMessageBox.information(self, "Info", "Tidak ada job failed.")
            return
        for job in failed:
            job.status = JobStatus.PENDING
            job.progress = 0.0
            job.error = ""
            job.attempt = 0
            self.db.update_job(job)
        self._jobs = self.db.list_jobs()
        self.job_table.load_jobs(self._jobs)
        self._refresh_summary()
        self.start_compression()

    @Slot(object)
    def on_job_updated(self, job: Job) -> None:
        self.job_table.upsert_job(job)
        self.current_label.setText(Path(job.source_path).name)
        self.progress.setValue(int(job.progress))
        orig = bytes_to_mb(job.original_size)
        out = bytes_to_mb(job.output_size) if job.output_size else 0
        red = job.reduction_percent
        self.stats_label.setText(
            f"Original: {orig:.1f} MB | Output: {out:.1f} MB | Reduction: {red:.1f}%"
        )
        self._refresh_summary()

    def on_batch_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self._paused = False
        self.cancel_btn.setEnabled(False)
        self.retry_btn.setEnabled(True)
        self._refresh_summary()
        self.progress.setValue(100)
        QMessageBox.information(self, "Selesai", "Batch compression selesai.")

    def _refresh_summary(self) -> None:
        s = self.manager.get_summary()
        self.summary_label.setText(
            f"Total: {s['total']} | Done: {s['done']} | "
            f"Failed: {s['failed']} | Remaining: {s['remaining']}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        if path.is_dir():
            self.source_edit.setText(str(path))
            if not self.output_edit.text():
                self.output_edit.setText(f"{path}_COMPRESSED")
        elif path.is_file():
            self.source_edit.setText(str(path.parent))
            if not self.output_edit.text():
                self.output_edit.setText(f"{path.parent}_COMPRESSED")


def run_gui() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Drone Compressor")
    window = MainWindow()
    window.show()
    return app.exec()
