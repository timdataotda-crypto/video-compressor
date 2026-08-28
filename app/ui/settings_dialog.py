from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from app.core.profiles import (
    PROFILES,
    apply_quality_profile,
    normalize_profile_key,
    profile_key_from_label,
    profile_labels,
)


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self._config = dict(config)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.target = QDoubleSpinBox()
        self.target.setRange(1, 500)
        self.target.setSuffix(" MB")
        self.target.setValue(float(config.get("target_size_mb", 19)))

        self.audio = QSpinBox()
        self.audio.setRange(32, 320)
        self.audio.setSuffix(" kbps")
        self.audio.setValue(int(config.get("audio_bitrate_kbps", 96)))

        self.preset = QComboBox()
        self.preset.addItems(["ultrafast", "fast", "medium", "slow", "veryslow"])
        self.preset.setCurrentText(str(config.get("preset", "medium")))

        self.resolution = QComboBox()
        self.resolution.addItems(["auto", "original", "1080p", "720p", "540p"])
        self.resolution.setCurrentText(str(config.get("resolution_mode", "auto")))

        self.workers = QSpinBox()
        self.workers.setRange(1, 8)
        self.workers.setValue(int(config.get("workers", 2)))

        self.retries = QSpinBox()
        self.retries.setRange(1, 10)
        self.retries.setValue(int(config.get("max_retries", 4)))

        self.safety = QDoubleSpinBox()
        self.safety.setRange(0.5, 1.0)
        self.safety.setSingleStep(0.01)
        self.safety.setValue(float(config.get("safety_margin", 0.94)))

        self.hw = QComboBox()
        self.hw.addItems(["auto", "cpu", "apple", "nvidia", "intel"])
        self.hw.setCurrentText(str(config.get("hardware_acceleration", "auto")))

        self.profile = QComboBox()
        self.profile.addItems(profile_labels())
        key = normalize_profile_key(config.get("quality_profile"))
        self.profile.setCurrentText(PROFILES[key].label)
        self.profile.currentTextChanged.connect(self._on_profile_changed)

        self.auto_retry = QCheckBox("Auto retry jika melebihi target")
        self.auto_retry.setChecked(bool(config.get("auto_retry", True)))

        form.addRow("Target size", self.target)
        form.addRow("Audio bitrate", self.audio)
        form.addRow("Quality profile", self.profile)
        form.addRow("FFmpeg preset", self.preset)
        form.addRow("Resolution", self.resolution)
        form.addRow("Workers", self.workers)
        form.addRow("Max retries", self.retries)
        form.addRow("Safety margin", self.safety)
        form.addRow("Hardware", self.hw)
        form.addRow("", self.auto_retry)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_profile_changed(self, label: str) -> None:
        key = profile_key_from_label(label)
        profile = PROFILES[key]
        self.preset.setCurrentText(profile.ffmpeg_preset)
        self.resolution.setCurrentText(profile.resolution_mode)

    def result_config(self) -> dict:
        cfg = dict(self._config)
        cfg.update(
            {
                "target_size_mb": self.target.value(),
                "audio_bitrate_kbps": self.audio.value(),
                "preset": self.preset.currentText(),
                "resolution_mode": self.resolution.currentText(),
                "workers": self.workers.value(),
                "max_retries": self.retries.value(),
                "safety_margin": self.safety.value(),
                "hardware_acceleration": self.hw.currentText(),
                "quality_profile": profile_key_from_label(self.profile.currentText()),
                "auto_retry": self.auto_retry.isChecked(),
            }
        )
        return apply_quality_profile(cfg)
