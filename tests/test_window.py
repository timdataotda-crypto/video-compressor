from __future__ import annotations

from PySide6.QtCore import QRect

from app.utils.window import clamp_window_to_screen


def test_clamp_keeps_visible_window() -> None:
    frame = QRect(100, 80, 800, 600)
    screen = QRect(0, 0, 1440, 900)
    assert clamp_window_to_screen(frame, screen) == frame


def test_clamp_recenters_off_screen_window() -> None:
    frame = QRect(5000, 4000, 800, 600)
    screen = QRect(0, 0, 1440, 900)
    result = clamp_window_to_screen(frame, screen)
    assert screen.contains(result)
    assert result.width() == 800
    assert result.height() == 600


def test_clamp_recenters_tiny_overlap() -> None:
    frame = QRect(-790, 0, 800, 600)
    screen = QRect(0, 0, 1440, 900)
    result = clamp_window_to_screen(frame, screen)
    assert result.x() >= 0
    assert screen.intersects(result)


def test_clamp_grows_tiny_restored_size() -> None:
    frame = QRect(10, 10, 40, 30)
    screen = QRect(0, 0, 1440, 900)
    result = clamp_window_to_screen(frame, screen)
    assert result.width() >= 720
    assert result.height() >= 520
