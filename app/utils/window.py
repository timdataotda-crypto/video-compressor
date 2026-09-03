from __future__ import annotations

from PySide6.QtCore import QRect


def clamp_window_to_screen(frame: QRect, available: QRect) -> QRect:
    """Keep a window frame on the given screen.

    Recenter when the frame is off-screen, only barely overlapping, or too small
    to use. macOS often restores Qt windows onto a disconnected display, which
    leaves the process running with no visible UI.
    """
    if available.width() <= 0 or available.height() <= 0:
        return QRect(frame)

    overlap = available.intersected(frame)
    usable = (
        overlap.width() >= 80
        and overlap.height() >= 80
        and frame.width() >= 200
        and frame.height() >= 200
    )
    if usable:
        return QRect(frame)

    width = min(max(frame.width(), 720), available.width())
    height = min(max(frame.height(), 520), available.height())
    x = available.x() + max(0, (available.width() - width) // 2)
    y = available.y() + max(0, (available.height() - height) // 2)
    return QRect(x, y, width, height)
