from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Tuple

import mss
import mss.tools

Point = Tuple[int, int]


def _enable_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_enable_windows_dpi_awareness()


def _build_monitor_region(top_left: Point, bottom_right: Point) -> dict[str, int]:
    """Build an MSS monitor dictionary from two corner points.

    Coordinates are in absolute screen pixels.
    """
    first_x, first_y = top_left
    second_x, second_y = bottom_right
    left = min(first_x, second_x)
    right = max(first_x, second_x)
    top = min(first_y, second_y)
    bottom = max(first_y, second_y)

    if right == left or bottom == top:
        raise ValueError(
            "Invalid rectangle: capture area must have non-zero width and height."
        )

    return {
        "left": left,
        "top": top,
        "width": right - left,
        "height": bottom - top,
    }


def _clamp_region_to_virtual_desktop(region: dict[str, int]) -> dict[str, int]:
    with mss.mss() as sct:
        virtual_monitor = sct.monitors[0]

    virtual_left = int(virtual_monitor["left"])
    virtual_top = int(virtual_monitor["top"])
    virtual_right = virtual_left + int(virtual_monitor["width"])
    virtual_bottom = virtual_top + int(virtual_monitor["height"])

    requested_left = int(region["left"])
    requested_top = int(region["top"])
    requested_right = requested_left + int(region["width"])
    requested_bottom = requested_top + int(region["height"])

    clamped_left = max(requested_left, virtual_left)
    clamped_top = max(requested_top, virtual_top)
    clamped_right = min(requested_right, virtual_right)
    clamped_bottom = min(requested_bottom, virtual_bottom)

    if clamped_right <= clamped_left or clamped_bottom <= clamped_top:
        raise ValueError("Capture area is outside the visible virtual desktop.")

    return {
        "left": clamped_left,
        "top": clamped_top,
        "width": clamped_right - clamped_left,
        "height": clamped_bottom - clamped_top,
    }


def capture_screenshot(top_left: Point, bottom_right: Point) -> mss.screenshot.ScreenShot:
    """Capture a rectangular screenshot region.

    Args:
        top_left: (x, y) for the top-left corner.
        bottom_right: (x, y) for the bottom-right corner.

    Returns:
        An MSS ScreenShot object containing raw BGRA pixel data.
    """
    monitor_region = _build_monitor_region(top_left, bottom_right)
    monitor_region = _clamp_region_to_virtual_desktop(monitor_region)

    with mss.mss() as sct:
        return sct.grab(monitor_region)


def save_screenshot(image: mss.screenshot.ScreenShot, output_path: str | Path) -> Path:
    """Save an MSS screenshot image to disk as PNG."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    mss.tools.to_png(image.rgb, image.size, output=str(destination))
    return destination


def capture_and_save(
    top_left: Point,
    bottom_right: Point,
    output_path: str | Path,
) -> Path:
    """Capture a rectangular screenshot and save it to disk as PNG."""
    screenshot = capture_screenshot(top_left, bottom_right)
    return save_screenshot(screenshot, output_path)


if __name__ == "__main__":
    # Example usage (coordinates in pixels):
    # captures a rectangle from (100, 100) to (700, 500)
    saved_file = capture_and_save((100, 100), (700, 500), "snips/example.png")
    print(f"Saved screenshot to: {saved_file}")
