from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.bitrate import bytes_to_mb
from app.core.job_manager import JobManager
from app.core.scanner import scan_videos
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
from app.ffmpeg.ffprobe import FFprobeError, probe_video
from app.geopas.client import GeopasClient, GeopasError
from app.geopas.models import PaketPekerjaan, Wilayah
from app.geopas.wilayah import children_of, filter_paket, split_wilayah
from app.models.job import Job, JobStatus
from app.ui.job_table import JobTable
from app.ui.settings_dialog import SettingsDialog
from app.utils.batch_paths import infer_batch_roots
from app.utils.deps import check_ffmpeg_deps
from app.utils.logger import setup_logging
from app.utils.paths import get_project_root, load_config, save_config


@dataclass
class LockedSource:
    source: str
    paket_id: int | None
    paket_nama: str
    file_count: int


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


class UploadWorker(QObject):
    job_updated = Signal(object)
    status = Signal(str)
    finished = Signal()

    def __init__(self, manager: JobManager, jobs: list[Job]) -> None:
        super().__init__()
        self.manager = manager
        self.jobs = jobs

    @Slot()
    def run(self) -> None:
        self.manager.upload_jobs(
            jobs=self.jobs,
            on_job_update=lambda job: self.job_updated.emit(job),
            on_status=lambda msg: self.status.emit(msg),
        )
        self.finished.emit()


class GeopasConnectWorker(QObject):
    finished = Signal(object, object, object)
    failed = Signal(str)

    def __init__(self, base_url: str, email: str, password: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.email = email
        self.password = password

    @Slot()
    def run(self) -> None:
        try:
            client = GeopasClient(self.base_url, timeout=30.0)
            client.login(self.email, self.password)
            wilayah = client.list_wilayah(parent_kode="null")
            self.finished.emit(client, wilayah, [])
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class GeopasTaskWorker(QObject):
    """Jalankan satu panggilan API Geopas di thread latar."""

    finished = Signal(int, str, object)
    failed = Signal(int, str, str)

    def __init__(self, token: int, kind: str, fn) -> None:
        super().__init__()
        self._token = token
        self._kind = kind
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self._token, self._kind, self._fn())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self._token, self._kind, str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Drone Compressor")
        self.resize(1100, 780)
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)

        self.config = load_config()
        self.db = Database()
        self.manager = JobManager(config=self.config, db=self.db)
        self._thread: QThread | None = None
        self._worker: Worker | UploadWorker | None = None
        self._jobs: list[Job] = []
        self._batch_kind = "compress"
        self._geopas_client: GeopasClient | None = None
        self._wilayah: list[Wilayah] = []
        self._paket: list[PaketPekerjaan] = []
        self._geopas_thread: QThread | None = None
        self._geopas_worker: GeopasConnectWorker | None = None
        self._geopas_watchdog = QTimer(self)
        self._geopas_watchdog.setSingleShot(True)
        self._geopas_watchdog.timeout.connect(self._on_geopas_timeout)
        self._wilayah_token = 0
        self._paket_token = 0
        self._pending_search_query = ""
        self._geopas_tasks: list[tuple[QThread, QObject]] = []
        self._paket_updating = False
        self._paket_search_timer = QTimer(self)
        self._paket_search_timer.setSingleShot(True)
        self._paket_search_timer.setInterval(400)
        self._paket_search_timer.timeout.connect(self._search_paket_from_query)
        self._batches: list[LockedSource] = []

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

    def _field_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("fieldLabel")
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return lab

    def _folder_button(self) -> QPushButton:
        btn = QPushButton("📁")
        btn.setObjectName("iconButton")
        btn.setFixedWidth(40)
        return btn

    def _header_logo(self) -> QLabel:
        label = QLabel()
        label.setObjectName("logoLabel")
        path = get_project_root() / "logo-geopas.png"
        pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
        if pixmap.isNull():
            label.setText("SATGAS PRR")
            label.setObjectName("titleLabel")
            return label
        dpr = self.devicePixelRatio() or 1.0
        scaled = pixmap.scaledToHeight(
            int(56 * dpr), Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(dpr)
        label.setPixmap(scaled)
        label.setFixedHeight(56)
        return label

    def _build_ui(self) -> None:
        content = QWidget()
        content.setMinimumWidth(700)
        root = QVBoxLayout(content)
        root.setSpacing(12)
        root.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 4)
        header.addWidget(self._header_logo(), alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        form_box = QGroupBox("Folders Target")
        form_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        form = QGridLayout(form_box)
        form.setContentsMargins(12, 18, 12, 12)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setColumnStretch(1, 1)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Folder sumber video…")
        src_btn = self._folder_button()
        src_btn.clicked.connect(self.pick_source)
        form.addWidget(self._field_label("SOURCE"), 0, 0)
        form.addWidget(self.source_edit, 0, 1)
        form.addWidget(src_btn, 0, 2)

        self.dest_combo = QComboBox()
        self.dest_combo.addItem("Lokal", "local")
        self.dest_combo.addItem("Geopas Dalrenduk", "geopas")
        dest_mode = str(self.config.get("output_destination", "local"))
        idx = self.dest_combo.findData(dest_mode)
        self.dest_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.dest_combo.currentIndexChanged.connect(self._on_destination_changed)
        form.addWidget(self._field_label("TUJUAN"), 1, 0)
        form.addWidget(self.dest_combo, 1, 1, 1, 2)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Folder output…")
        out_btn = self._folder_button()
        out_btn.clicked.connect(self.pick_output)
        form.addWidget(self._field_label("OUTPUT"), 2, 0)
        form.addWidget(self.output_edit, 2, 1)
        form.addWidget(out_btn, 2, 2)

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
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.setSpacing(8)
        target_row.addWidget(self.target_preset, stretch=2)
        target_row.addWidget(self.target_spin, stretch=1)
        form.addWidget(self._field_label("TARGET"), 3, 0)
        form.addLayout(target_row, 3, 1, 1, 2)

        self.quality_combo = QComboBox()
        for label in profile_labels():
            self.quality_combo.addItem(label)
        profile_key = normalize_profile_key(self.config.get("quality_profile"))
        self.quality_combo.setCurrentText(PROFILES[profile_key].label)
        self.quality_hint = QLabel(PROFILES[profile_key].description)
        self.quality_hint.setObjectName("hintLabel")
        self.quality_hint.setWordWrap(True)
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        form.addWidget(self._field_label("QUALITY"), 4, 0)
        form.addWidget(self.quality_combo, 4, 1, 1, 2)
        form.addWidget(self.quality_hint, 5, 1, 1, 2)

        self.chk_recursive = QCheckBox("Recursive folders")
        self.chk_recursive.setChecked(bool(self.config.get("recursive", True)))
        self.chk_preserve = QCheckBox("Preserve structure")
        self.chk_preserve.setChecked(bool(self.config.get("preserve_structure", True)))
        self.chk_skip = QCheckBox("Skip existing")
        self.chk_skip.setChecked(bool(self.config.get("skip_existing", True)))
        self.chk_retry = QCheckBox("Auto retry")
        self.chk_retry.setChecked(bool(self.config.get("auto_retry", True)))
        opts = QGridLayout()
        opts.setContentsMargins(0, 4, 0, 0)
        opts.setHorizontalSpacing(16)
        opts.setVerticalSpacing(6)
        opts.addWidget(self.chk_recursive, 0, 0)
        opts.addWidget(self.chk_preserve, 0, 1)
        opts.addWidget(self.chk_skip, 1, 0)
        opts.addWidget(self.chk_retry, 1, 1)
        form.addLayout(opts, 6, 1, 1, 2)
        self.lock_source_btn = QPushButton("Kunci & tambah source")
        self.lock_source_btn.setObjectName("lockButton")
        self.lock_source_btn.clicked.connect(self.lock_current_source)
        form.addWidget(self.lock_source_btn, 7, 1, 1, 2)

        self.geopas_box = QGroupBox("Geopas Dalrenduk")
        self.geopas_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.geopas_box.setMinimumWidth(280)
        geopas = QGridLayout(self.geopas_box)
        geopas.setContentsMargins(12, 18, 12, 12)
        geopas.setHorizontalSpacing(10)
        geopas.setVerticalSpacing(8)
        geopas.setColumnStretch(1, 1)

        self.geopas_email = QLineEdit(str(self.config.get("geopas_email", "")))
        self.geopas_email.setPlaceholderText("Email login Geopas")
        self.geopas_password = QLineEdit(str(self.config.get("geopas_password", "")))
        self.geopas_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.geopas_password.setPlaceholderText("Password")
        self.geopas_connect_btn = QPushButton("Hubungkan")
        self.geopas_connect_btn.setMinimumWidth(104)
        self.geopas_connect_btn.clicked.connect(self.connect_geopas)
        geopas.addWidget(self._field_label("AKUN"), 0, 0)
        geopas.addWidget(self.geopas_email, 0, 1, 1, 2)
        pass_row = QHBoxLayout()
        pass_row.setContentsMargins(0, 0, 0, 0)
        pass_row.setSpacing(8)
        pass_row.addWidget(self.geopas_password, stretch=1)
        pass_row.addWidget(self.geopas_connect_btn)
        geopas.addLayout(pass_row, 1, 1, 1, 2)

        self.geopas_status = QLabel("Belum terhubung.")
        self.geopas_status.setObjectName("hintLabel")
        self.geopas_status.setWordWrap(True)
        geopas.addWidget(self.geopas_status, 2, 1, 1, 2)

        self.provinsi_combo = QComboBox()
        self.kabupaten_combo = QComboBox()
        self.kecamatan_combo = QComboBox()
        self.paket_combo = QComboBox()
        self._configure_paket_search()
        for combo in (
            self.provinsi_combo,
            self.kabupaten_combo,
            self.kecamatan_combo,
            self.paket_combo,
        ):
            combo.addItem("— Pilih —", None)
            combo.setEnabled(False)
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(18)
        self.provinsi_combo.currentIndexChanged.connect(self._on_provinsi_changed)
        self.kabupaten_combo.currentIndexChanged.connect(self._on_kabupaten_changed)
        self.kecamatan_combo.currentIndexChanged.connect(self._on_kecamatan_changed)
        geopas.addWidget(self._field_label("PROVINSI"), 3, 0)
        geopas.addWidget(self.provinsi_combo, 3, 1, 1, 2)
        geopas.addWidget(self._field_label("KABUPATEN"), 4, 0)
        geopas.addWidget(self.kabupaten_combo, 4, 1, 1, 2)
        geopas.addWidget(self._field_label("KECAMATAN"), 5, 0)
        geopas.addWidget(self.kecamatan_combo, 5, 1, 1, 2)
        geopas.addWidget(self._field_label("PAKET PEKERJAAN"), 6, 0)
        geopas.addWidget(self.paket_combo, 6, 1, 1, 2)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        cards.addWidget(form_box, stretch=1)
        cards.addWidget(self.geopas_box, stretch=1)
        root.addLayout(cards)

        queue_box = QGroupBox("Antrian source terkunci")
        queue_layout = QVBoxLayout(queue_box)
        queue_layout.setContentsMargins(10, 14, 10, 10)
        self.batch_list = QListWidget()
        self.batch_list.setObjectName("batchList")
        self.batch_list.setMaximumHeight(110)
        queue_layout.addWidget(self.batch_list)
        queue_hint = QLabel(
            "Pilih SOURCE + PAKET, lalu kunci. Ulangi untuk paket lain. "
            "Satu kali START COMPRESSION memproses semua antrian."
        )
        queue_hint.setObjectName("hintLabel")
        queue_hint.setWordWrap(True)
        queue_layout.addWidget(queue_hint)
        queue_btns = QHBoxLayout()
        self.remove_batch_btn = QPushButton("Hapus antrian terpilih")
        self.remove_batch_btn.clicked.connect(self.remove_selected_batch)
        queue_btns.addWidget(self.remove_batch_btn)
        queue_btns.addStretch()
        queue_layout.addLayout(queue_btns)
        root.addWidget(queue_box)

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
        self.send_geopas_btn = QPushButton("Kirim ke Geopas")
        self.send_geopas_btn.clicked.connect(self.send_to_geopas)
        self.open_out_btn = QPushButton("Open Output")
        self.open_out_btn.clicked.connect(self.open_output_folder)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.pause_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.retry_btn)
        actions.addWidget(self.send_geopas_btn)
        actions.addWidget(self.open_out_btn)
        actions.addStretch()
        root.addLayout(actions)
        self._paused = False
        self._on_destination_changed()

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
        self.job_table.setMinimumHeight(180)
        root.addWidget(self.job_table, stretch=1)

        self.summary_label = QLabel("Total: 0 | Done: 0 | Failed: 0 | Remaining: 0")
        root.addWidget(self.summary_label)

        scroll = QScrollArea()
        scroll.setObjectName("mainScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

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

    def _geopas_mode(self) -> bool:
        return self.dest_combo.currentData() == "geopas"

    def _on_destination_changed(self, _index: int = 0) -> None:
        geopas = self._geopas_mode()
        if hasattr(self, "start_btn"):
            self.start_btn.setText("START COMPRESSION")
            if hasattr(self, "send_geopas_btn"):
                self.send_geopas_btn.setVisible(geopas)

    def connect_geopas(self) -> None:
        email = self.geopas_email.text().strip()
        password = self.geopas_password.text()
        base_url = str(
            self.config.get("geopas_base_url") or "https://geopas.satgasprr.go.id/api"
        ).strip()
        if not email or not password:
            QMessageBox.warning(
                self, "Geopas", "Isi email dan password, atau atur di Settings."
            )
            return
        if not base_url:
            QMessageBox.warning(self, "Geopas", "Isi Geopas API URL di Settings.")
            return
        self._sync_config_from_ui()
        self._wilayah_token += 1
        self._paket_token += 1
        self.geopas_connect_btn.setEnabled(False)
        self.geopas_status.setText("Menghubungkan…")
        self._geopas_thread = QThread()
        self._geopas_worker = GeopasConnectWorker(base_url, email, password)
        self._geopas_worker.moveToThread(self._geopas_thread)
        self._geopas_thread.started.connect(self._geopas_worker.run)
        self._geopas_worker.finished.connect(self._on_geopas_connected)
        self._geopas_worker.failed.connect(self._on_geopas_failed)
        self._geopas_worker.finished.connect(self._geopas_thread.quit)
        self._geopas_worker.failed.connect(self._geopas_thread.quit)
        self._geopas_worker.finished.connect(self._geopas_worker.deleteLater)
        self._geopas_worker.failed.connect(self._geopas_worker.deleteLater)
        self._geopas_thread.finished.connect(self._geopas_thread.deleteLater)
        self._geopas_watchdog.start(40000)
        self._geopas_thread.start()

    @Slot(object, object, object)
    def _on_geopas_connected(
        self,
        client: GeopasClient,
        wilayah: list[Wilayah],
        paket: list[PaketPekerjaan],
    ) -> None:
        self._geopas_watchdog.stop()
        self.geopas_connect_btn.setEnabled(True)
        self._geopas_client = client
        self._wilayah = list(wilayah)
        self._paket = list(paket)
        grouped = split_wilayah(self._wilayah)
        if grouped["provinsi"]:
            self._fill_combo(self.provinsi_combo, grouped["provinsi"], lambda w: w.nama)
            self.provinsi_combo.setEnabled(True)
            self._reset_combo(self.kabupaten_combo)
            self._reset_combo(self.kecamatan_combo)
            self._reset_combo(self.paket_combo)
        else:
            self._fill_combo(
                self.paket_combo,
                self._paket,
                lambda p: f"{p.nama} (#{p.id})",
            )
        self.geopas_status.setText(
            f"Terhubung. {len(grouped['provinsi'])} provinsi. "
            "Pilih wilayah untuk memuat paket."
        )
        self.geopas_status.setStyleSheet("color: #7dcea0;")
        self._enable_paket_search_field()

    @Slot(str)
    def _on_geopas_failed(self, message: str) -> None:
        self._geopas_watchdog.stop()
        self.geopas_connect_btn.setEnabled(True)
        self._geopas_client = None
        self.geopas_status.setText(f"Gagal terhubung: {message}")
        self.geopas_status.setStyleSheet("color: #e57373;")

    def _on_geopas_timeout(self) -> None:
        self.geopas_connect_btn.setEnabled(True)
        self.geopas_status.setText(
            "Koneksi terlalu lama. Tombol Hubungkan aktif lagi — coba ulang."
        )
        self.geopas_status.setStyleSheet("color: #e57373;")

    def _configure_paket_search(self) -> None:
        self.paket_combo.setEditable(True)
        self.paket_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.paket_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.paket_combo.setMinimumContentsLength(24)
        line = self.paket_combo.lineEdit()
        if line is not None:
            line.setPlaceholderText("Ketik nama paket untuk mencari…")
            line.textEdited.connect(self._on_paket_text_edited)
        completer = self.paket_combo.completer()
        if completer is None:
            completer = QCompleter(self.paket_combo)
            self.paket_combo.setCompleter(completer)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCompletionRole(Qt.ItemDataRole.DisplayRole)

    def _enable_paket_search_field(self) -> None:
        self.paket_combo.setEnabled(True)
        self.paket_combo.setEditable(True)
        line = self.paket_combo.lineEdit()
        if line is not None:
            line.setPlaceholderText("Ketik nama paket untuk mencari…")

    def _on_paket_text_edited(self, _text: str) -> None:
        if self._paket_updating:
            return
        self._paket_search_timer.start()

    def _search_paket_from_query(self) -> None:
        if self._geopas_client is None or self._paket_updating:
            return
        query = self.paket_combo.currentText().strip()
        if len(query) < 2 or query.startswith("—") or query.startswith("Tidak ada"):
            return
        kabupaten = self.kabupaten_combo.currentData()
        provinsi = self.provinsi_combo.currentData()
        client = self._geopas_client
        kab_id = kabupaten.id if kabupaten is not None else None
        prov_id = (
            None
            if kabupaten is not None
            else (provinsi.id if provinsi is not None else None)
        )
        self._pending_search_query = query
        self._paket_token += 1
        token = self._paket_token

        def _fn() -> list[PaketPekerjaan]:
            return client.list_paket_pekerjaan(
                nama=query,
                kabupaten_id=kab_id,
                provinsi_id=prov_id,
            )

        self._run_geopas_task(token, "search", _fn)

    def _fill_paket_combo(
        self,
        rows: list[PaketPekerjaan],
        keep_text: str | None = None,
    ) -> None:
        self._paket = rows
        self._paket_updating = True
        try:
            self._fill_combo(
                self.paket_combo,
                rows,
                lambda p: f"{p.nama} (#{p.id})",
            )
            self._enable_paket_search_field()
            completer = self.paket_combo.completer()
            if completer is not None:
                completer.setFilterMode(Qt.MatchFlag.MatchContains)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            if keep_text:
                self.paket_combo.setEditText(keep_text)
            elif not rows:
                self.paket_combo.setItemText(0, "Tidak ada paket — ketik nama untuk cari")
                self.paket_combo.setEditText("")
        finally:
            self._paket_updating = False

    def _selected_paket(self) -> PaketPekerjaan | None:
        paket = self.paket_combo.currentData()
        if paket is not None:
            return paket
        text = self.paket_combo.currentText().strip().lower()
        if not text:
            return None
        for i in range(self.paket_combo.count()):
            item = self.paket_combo.itemData(i)
            label = self.paket_combo.itemText(i).lower()
            if item is not None and (text == label or text in label):
                return item
        for p in self._paket:
            if text in p.nama.lower() or text == str(p.id):
                return p
        return None

    def _reset_combo(self, combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— Pilih —", None)
        combo.setEnabled(False)
        combo.blockSignals(False)

    def _fill_combo(self, combo: QComboBox, items: list, label_fn) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— Pilih —", None)
        for item in items:
            combo.addItem(label_fn(item), item)
        combo.setEnabled(True)
        combo.blockSignals(False)

    def _merge_wilayah(self, items: list[Wilayah]) -> None:
        known = {w.id for w in self._wilayah}
        for item in items:
            if item.id not in known:
                self._wilayah.append(item)
                known.add(item.id)

    def _run_geopas_task(self, token: int, kind: str, fn) -> None:
        worker = GeopasTaskWorker(token, kind, fn)
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_geopas_task_finished)
        worker.failed.connect(self._on_geopas_task_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._forget_finished_geopas_tasks)
        self._geopas_tasks.append((thread, worker))
        thread.start()

    @Slot()
    def _forget_finished_geopas_tasks(self) -> None:
        alive: list[tuple[QThread, QObject]] = []
        for thread, worker in self._geopas_tasks:
            try:
                if thread.isRunning():
                    alive.append((thread, worker))
            except RuntimeError:
                continue
        self._geopas_tasks = alive

    @Slot(int, str, object)
    def _on_geopas_task_finished(
        self, token: int, kind: str, result: object
    ) -> None:
        if kind in ("kabupaten", "kecamatan"):
            if token != self._wilayah_token:
                return
            kids = (
                [item for item in result if isinstance(item, Wilayah)]
                if isinstance(result, list)
                else []
            )
            self._apply_wilayah_children(kind, kids)
            self.geopas_status.setStyleSheet("")
            self.geopas_status.setText(
                "Wilayah dimuat. Pilih kecamatan, atau ketik nama paket."
            )
            return
        if kind not in ("paket", "search"):
            return
        if token != self._paket_token:
            return
        rows = (
            [item for item in result if isinstance(item, PaketPekerjaan)]
            if isinstance(result, list)
            else []
        )
        keep: str | None = None
        if kind == "search":
            keep = self._pending_search_query
            if not rows and keep:
                needle = keep.lower()
                rows = [
                    p
                    for p in self._paket
                    if needle in p.nama.lower() or keep in str(p.id)
                ]
        self._fill_paket_combo(rows, keep_text=keep)
        self.geopas_status.setStyleSheet("")
        count = len(rows)
        if kind == "search":
            self.geopas_status.setText(
                f"{count} paket ditemukan. Ketik nama untuk mencari lagi."
            )
        else:
            self.geopas_status.setText(
                f"{count} paket dimuat. Ketik nama untuk mencari."
            )

    @Slot(int, str, str)
    def _on_geopas_task_failed(self, token: int, kind: str, message: str) -> None:
        if kind in ("kabupaten", "kecamatan"):
            if token != self._wilayah_token:
                return
            self.geopas_status.setText(f"Gagal memuat wilayah: {message}")
            self.geopas_status.setStyleSheet("color: #e57373;")
            QMessageBox.warning(self, "Geopas", message)
            return
        if kind != "paket" or token != self._paket_token:
            return
        self._enable_paket_search_field()
        self._reset_combo(self.paket_combo)
        self._enable_paket_search_field()
        self.paket_combo.setItemText(0, f"Gagal memuat paket: {message}")
        self.geopas_status.setText(f"Gagal memuat paket: {message}")
        self.geopas_status.setStyleSheet("color: #e57373;")

    def _apply_wilayah_children(self, kind: str, kids: list[Wilayah]) -> None:
        self._merge_wilayah(kids)
        if kind == "kabupaten":
            self._fill_combo(self.kabupaten_combo, kids, lambda w: w.nama)
        else:
            self._fill_combo(self.kecamatan_combo, kids, lambda w: w.nama)

    def _load_wilayah_children(self, parent: Wilayah, kind: str) -> None:
        cached = children_of(parent, self._wilayah)
        if cached:
            self._apply_wilayah_children(kind, cached)
            return
        if self._geopas_client is None:
            return
        client = self._geopas_client
        kode = parent.kode
        token = self._wilayah_token
        self.geopas_status.setStyleSheet("")
        self.geopas_status.setText(
            "Memuat kabupaten…" if kind == "kabupaten" else "Memuat kecamatan…"
        )

        def _fn() -> list[Wilayah]:
            return client.list_wilayah(parent_kode=kode)

        self._run_geopas_task(token, kind, _fn)

    def _on_provinsi_changed(self, _index: int = 0) -> None:
        provinsi = self.provinsi_combo.currentData()
        self._reset_combo(self.kabupaten_combo)
        self._reset_combo(self.kecamatan_combo)
        self._wilayah_token += 1
        self._paket_token += 1
        if provinsi is None:
            self._reset_combo(self.paket_combo)
            return
        self._load_wilayah_children(provinsi, "kabupaten")
        self._refresh_paket_combo()

    def _on_kabupaten_changed(self, _index: int = 0) -> None:
        kabupaten = self.kabupaten_combo.currentData()
        self._reset_combo(self.kecamatan_combo)
        self._wilayah_token += 1
        if kabupaten is not None:
            self._load_wilayah_children(kabupaten, "kecamatan")
        self._refresh_paket_combo()

    def _on_kecamatan_changed(self, _index: int = 0) -> None:
        self._refresh_paket_combo()

    def _refresh_paket_combo(self) -> None:
        kecamatan = self.kecamatan_combo.currentData()
        kabupaten = self.kabupaten_combo.currentData()
        provinsi = self.provinsi_combo.currentData()
        self._paket_token += 1
        if self._geopas_client is not None and (
            kabupaten is not None or provinsi is not None
        ):
            client = self._geopas_client
            kab_id = kabupaten.id if kabupaten is not None else None
            prov_id = provinsi.id if provinsi is not None else None
            token = self._paket_token
            self.geopas_status.setStyleSheet("")
            self.geopas_status.setText("Memuat paket pekerjaan…")

            def _fn() -> list[PaketPekerjaan]:
                if kab_id is not None:
                    return client.list_paket_pekerjaan(kabupaten_id=kab_id)
                return client.list_paket_pekerjaan(provinsi_id=prov_id)

            self._run_geopas_task(token, "paket", _fn)
            return
        rows = filter_paket(
            self._paket,
            provinsi=provinsi,
            kabupaten=kabupaten,
            kecamatan=kecamatan,
        )
        self._fill_paket_combo(rows)

    def _sync_config_from_ui(self) -> None:
        self.config["target_size_mb"] = self.target_spin.value()
        self.config["recursive"] = self.chk_recursive.isChecked()
        self.config["preserve_structure"] = self.chk_preserve.isChecked()
        self.config["skip_existing"] = self.chk_skip.isChecked()
        self.config["auto_retry"] = self.chk_retry.isChecked()
        self.config["output_destination"] = self.dest_combo.currentData() or "local"
        self.config["geopas_email"] = self.geopas_email.text().strip()
        self.config["geopas_password"] = self.geopas_password.text()
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
            self._rebuild_batches_from_jobs(jobs)
            self._refresh_summary()
            if jobs:
                src_root, out_root = infer_batch_roots(
                    [j.source_path for j in jobs],
                    [j.output_path for j in jobs],
                )
                if src_root and not self._batches:
                    self.source_edit.setText(src_root)
                if out_root:
                    self.output_edit.setText(out_root)
        else:
            self.db.clear_jobs()
            self._batches = []
            self._refresh_batch_list()

    def pick_source(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pilih Source Folder")
        if path:
            self.source_edit.setText(path)
            if not self.output_edit.text():
                self.output_edit.setText(f"{path.rstrip('/')}_COMPRESSED")

    def _refresh_batch_list(self) -> None:
        self.batch_list.clear()
        for batch in self._batches:
            folder = Path(batch.source).name
            if batch.paket_id is not None:
                text = (
                    f"🔒 {batch.paket_nama} (#{batch.paket_id})  ·  "
                    f"{batch.file_count} video  ·  {folder}"
                )
            else:
                text = f"🔒 {folder}  ·  {batch.file_count} video"
            self.batch_list.addItem(QListWidgetItem(text))

    def _rebuild_batches_from_jobs(self, jobs: list[Job]) -> None:
        grouped: dict[tuple[str, int | None], LockedSource] = {}
        for job in jobs:
            source = job.batch_source or str(Path(job.source_path).parent)
            key = (source, job.geopas_paket_id)
            item = grouped.get(key)
            if item is None:
                grouped[key] = LockedSource(
                    source=source,
                    paket_id=job.geopas_paket_id,
                    paket_nama=job.geopas_paket_nama,
                    file_count=1,
                )
            else:
                item.file_count += 1
        self._batches = list(grouped.values())
        self._refresh_batch_list()

    def _reset_paket_after_lock(self) -> None:
        self._paket_updating = True
        try:
            if self.paket_combo.count() > 0:
                self.paket_combo.setCurrentIndex(0)
            line = self.paket_combo.lineEdit()
            if line is not None:
                line.setText("")
        finally:
            self._paket_updating = False

    def lock_current_source(self) -> bool:
        source = Path(self.source_edit.text().strip())
        output = Path(self.output_edit.text().strip())
        if not source.exists():
            QMessageBox.warning(self, "Error", "Source folder tidak valid.")
            return False
        if not str(output):
            QMessageBox.warning(self, "Error", "Output folder wajib diisi.")
            return False

        geopas = self._geopas_mode()
        paket_id: int | None = None
        paket_nama = ""
        if geopas:
            if self._geopas_client is None:
                QMessageBox.warning(self, "Geopas", "Hubungkan ke Geopas dulu.")
                return False
            paket = self._selected_paket()
            if paket is None:
                QMessageBox.warning(
                    self,
                    "Geopas",
                    "Pilih paket pekerjaan dulu, lalu kunci source.",
                )
                return False
            paket_id = paket.id
            paket_nama = paket.nama
            if any(b.paket_id == paket_id for b in self._batches):
                QMessageBox.warning(
                    self,
                    "Geopas",
                    f"Paket {paket_nama} (#{paket_id}) sudah dikunci. "
                    "Pilih paket lain agar video tidak tertukar.",
                )
                return False

        source_key = str(source.resolve())
        if any(b.source == source_key for b in self._batches):
            QMessageBox.warning(self, "Error", "Source ini sudah ada di antrian terkunci.")
            return False

        self._sync_config_from_ui()
        found = scan_videos(source, recursive=self.chk_recursive.isChecked())
        if not found:
            QMessageBox.information(self, "Info", "Tidak ada video di folder source ini.")
            return False
        readable: list[Path] = []
        broken: list[str] = []
        for video in found:
            try:
                probe_video(video)
                readable.append(video)
            except FFprobeError as exc:
                broken.append(str(exc))
        if broken:
            preview = "\n".join(broken[:8])
            more = f"\n…dan {len(broken) - 8} file lain." if len(broken) > 8 else ""
            if not readable:
                QMessageBox.critical(
                    self,
                    "File sumber rusak",
                    "Semua video di folder ini tidak utuh, jadi tidak bisa dikompres "
                    "atau dikirim ke Geopas.\n\n"
                    f"{preview}{more}\n\n"
                    "Salin ulang dari drone/kartu SD. Uji dulu di QuickTime: "
                    "kalau tidak bisa diputar, file-nya masih rusak.",
                )
                return False
            reply = QMessageBox.warning(
                self,
                "Sebagian file rusak",
                f"{len(broken)} file rusak dilewati, {len(readable)} file utuh akan dikunci.\n\n"
                f"{preview}{more}\n\nLanjutkan dengan file yang utuh?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        label = paket_nama if paket_nama else source.name
        try:
            jobs = self.manager.scan_and_create_jobs(
                source,
                output,
                clear_previous=len(self._batches) == 0,
                geopas_paket_id=paket_id,
                geopas_paket_nama=paket_nama,
                batch_source=source_key,
                batch_label=label,
                videos=readable,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Scan gagal", str(exc))
            return False
        if not jobs:
            QMessageBox.information(self, "Info", "Tidak ada video di folder source ini.")
            return False

        extra = ""
        if geopas and len(jobs) > 1:
            extra = (
                f"\n\nCatatan: Geopas hanya menampilkan 1 video per paket. "
                f"{len(jobs)} file akan diunggah; yang terakhir yang tampil."
            )
        self._batches.append(
            LockedSource(
                source=source_key,
                paket_id=paket_id,
                paket_nama=paket_nama,
                file_count=len(jobs),
            )
        )
        self._refresh_batch_list()
        self._jobs = self.db.list_jobs()
        self.job_table.load_jobs(self._jobs)
        self._refresh_summary()
        self.source_edit.clear()
        if geopas:
            self._reset_paket_after_lock()
        self.summary_label.setText(
            f"Terkunci: {len(jobs)} video"
            + (f" → {paket_nama} (#{paket_id})" if paket_id else "")
            + f". Total antrian {sum(b.file_count for b in self._batches)} file."
            + extra.replace("\n\n", " ")
        )
        return True

    def remove_selected_batch(self) -> None:
        row = self.batch_list.currentRow()
        if row < 0 or row >= len(self._batches):
            QMessageBox.information(self, "Info", "Pilih antrian yang akan dihapus.")
            return
        batch = self._batches.pop(row)
        self.db.delete_jobs_for_batch(batch.source, batch.paket_id)
        self._refresh_batch_list()
        self._jobs = self.db.list_jobs()
        self.job_table.load_jobs(self._jobs)
        self._refresh_summary()

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
            self.geopas_email.setText(str(self.config.get("geopas_email", "")))
            self.geopas_password.setText(str(self.config.get("geopas_password", "")))
            self.manager.config = self.config
            save_config(self.config)

    def open_output_folder(self) -> None:
        out = self.output_edit.text().strip()
        if out and Path(out).exists():
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl.fromLocalFile(out))

    def start_compression(self) -> None:
        output = Path(self.output_edit.text().strip())
        source_text = self.source_edit.text().strip()
        geopas_mode = self._geopas_mode()
        self.manager.geopas_client = self._geopas_client if geopas_mode else None
        self.manager.geopas_paket_id = None
        if geopas_mode and self._geopas_client is None:
            QMessageBox.warning(
                self,
                "Geopas",
                "Hubungkan ke Geopas dulu. Compress tetap ke folder lokal; "
                "unggah dilakukan setelah selesai, setelah konfirmasi.",
            )
            return

        self._sync_config_from_ui()

        if source_text:
            src_path = Path(source_text)
            already = False
            if src_path.exists():
                already = any(b.source == str(src_path.resolve()) for b in self._batches)
            if not already:
                locked = self.lock_current_source()
                if not locked and not self._batches:
                    return

        if self._batches:
            jobs = self.db.list_jobs()
        else:
            source = Path(source_text)
            if not source.exists():
                QMessageBox.warning(
                    self,
                    "Error",
                    "Kunci source dulu, atau pilih folder SOURCE.",
                )
                return
            if not str(output):
                QMessageBox.warning(self, "Error", "Output folder wajib diisi.")
                return
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
        self.send_geopas_btn.setEnabled(False)

        self._batch_kind = "compress"
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

    def send_to_geopas(self) -> None:
        self._offer_geopas_upload(force=True)

    def _jobs_ready_to_send(self) -> list[Job]:
        return self.manager.jobs_ready_to_upload(self.db.list_jobs())

    def _offer_geopas_upload(self, force: bool = False) -> None:
        if not self._geopas_mode():
            if force:
                QMessageBox.information(
                    self, "Geopas", "Pilih tujuan Geopas Dalrenduk dulu."
                )
            return
        if self._geopas_client is None:
            QMessageBox.warning(self, "Geopas", "Hubungkan ke Geopas dulu.")
            return
        ready = self._jobs_ready_to_send()
        if not ready:
            QMessageBox.information(
                self,
                "Geopas",
                "Tidak ada file hasil compress di folder output untuk dikirim.",
            )
            return
        missing = [j for j in ready if not j.geopas_paket_id]
        mapped = [j for j in ready if j.geopas_paket_id]
        if missing and not mapped:
            QMessageBox.warning(
                self,
                "Geopas",
                "Job belum terkunci ke paket. Kunci SOURCE + PAKET dulu, "
                "lalu kompres ulang.",
            )
            return
        if missing:
            QMessageBox.warning(
                self,
                "Geopas",
                f"{len(missing)} file tanpa paket terkunci dilewati. "
                "Hanya file yang sudah dikunci ke paket yang dikirim.",
            )
        by_paket: dict[tuple[int, str], list[Job]] = defaultdict(list)
        for job in mapped:
            assert job.geopas_paket_id is not None
            nama = job.geopas_paket_nama or f"#{job.geopas_paket_id}"
            by_paket[(job.geopas_paket_id, nama)].append(job)
        lines = []
        for (pid, nama), group in by_paket.items():
            note = ""
            if len(group) > 1:
                note = " — Geopas hanya menampilkan 1 video (unggahan terakhir)"
            lines.append(f"• {nama} (#{pid}) — {len(group)} video{note}")
        reply = QMessageBox.question(
            self,
            "Kirim ke server?",
            f"Kirim {len(mapped)} video ke {len(by_paket)} paket pekerjaan?\n\n"
            + "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_geopas_upload(mapped)

    def _start_geopas_upload(self, jobs: list[Job], paket_id: int | None = None) -> None:
        self.manager.geopas_client = self._geopas_client
        self.manager.geopas_paket_id = paket_id
        self.start_btn.setEnabled(False)
        self.send_geopas_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Pause")
        self._paused = False
        self.cancel_btn.setEnabled(True)
        self._batch_kind = "upload"
        self._thread = QThread()
        self._worker = UploadWorker(self.manager, jobs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.job_updated.connect(self.on_job_updated)
        self._worker.status.connect(self.summary_label.setText)
        self._worker.finished.connect(self.on_batch_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(object)
    def on_job_updated(self, job: Job) -> None:
        self.job_table.upsert_job(job)
        paket = f" → {job.geopas_paket_nama}" if job.geopas_paket_nama else ""
        self.current_label.setText(f"{Path(job.source_path).name}{paket}")
        self.progress.setValue(int(job.progress))
        orig = bytes_to_mb(job.original_size)
        out = bytes_to_mb(job.output_size) if job.output_size else 0
        red = job.reduction_percent
        self.stats_label.setText(
            f"Original: {orig:.1f} MB | Output: {out:.1f} MB | Reduction: {red:.1f}%"
        )
        self._refresh_summary()

    def on_batch_finished(self) -> None:
        kind = self._batch_kind
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("Pause")
        self._paused = False
        self.cancel_btn.setEnabled(False)
        self.retry_btn.setEnabled(True)
        self.send_geopas_btn.setEnabled(True)
        self._refresh_summary()
        self.progress.setValue(100)
        self._jobs = self.db.list_jobs()
        if kind == "upload":
            failed = sum(
                1 for j in self._jobs if j.status == JobStatus.UPLOAD_FAILED
            )
            if failed:
                QMessageBox.warning(
                    self,
                    "Unggah selesai",
                    f"{failed} file gagal diunggah. File hasil compress tetap ada di folder output.",
                )
            else:
                QMessageBox.information(
                    self, "Selesai", "Unggah ke Geopas selesai."
                )
            return
        if self._geopas_mode():
            self._offer_geopas_upload()
            return
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
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Drone Compressor")
    window = MainWindow()
    window.show()
    return app.exec()
