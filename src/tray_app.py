from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import json
from pathlib import Path
import re
import string
import subprocess
import threading
import time
from typing import Any, List

from PIL import Image, ImageDraw
import pystray

from gemini_client import prompt_with_uploaded_image
from screenshot_snippet import capture_and_save
from tray_icon_library import PredefinedTrayIcons

SUPPORTED_ICON_EXTENSIONS = {".ico", ".png", ".jpg", ".jpeg", ".bmp"}
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
HOTKEY_ID_TOP_LEFT = 1
HOTKEY_ID_BOTTOM_RIGHT = 2
VK_LEFT = 0x25
VK_RIGHT = 0x27
GEMINI_MODEL_NAME = "gemini-2.5-flash"
GEMINI_IMAGE_PROMPT = (
    "You are solving a multiple-choice quiz from the screenshot. "
    "Return valid JSON only (no markdown) using this schema: "
    '{"question_type":"multiple_choice|free_response","explanation":"string","verification":"string","answer":"A or final response","free_response_answer":"string"}. '
    "Set question_type to free_response if the question requires a typed/open response. "
    "The explanation must briefly explain the choice. "
    "The verification must briefly verify why alternatives are less likely. "
    "For multiple_choice, answer must be a single uppercase letter only. "
    "For free_response, put the final written response in free_response_answer."
)
GEMINI_NOTIFICATION_MAX_LENGTH = 240
IMAGE_READY_TIMEOUT_SECONDS = 2.0
IMAGE_READY_POLL_SECONDS = 0.05


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class TrayScreenshotApp:
    def __init__(
        self,
        top_left: tuple[int, int] = (100, 100),
        bottom_right: tuple[int, int] = (700, 500),
        icon_directory: str | Path = "icons",
    ) -> None:
        self.top_left = top_left
        self.bottom_right = bottom_right
        self.icon_directory = Path(icon_directory)
        self.icon_paths: List[Path] = []
        self.icon_index = 0
        self.predefined_icons = PredefinedTrayIcons(size=64)
        self.predefined_icon_names = [
            "loading",
            "question",
            *[f"letter_{letter}" for letter in string.ascii_uppercase],
        ]
        self.predefined_icon_index = 0
        self.output_directory = Path("snips")
        self.logs_directory = Path("logs")
        self.gemini_error_log_file = self.logs_directory / "gemini_errors.txt"
        self.gemini_output_log_file = self.logs_directory / "gemini_output.txt"
        self.free_response_answer_file = self.logs_directory / "free_response_answer.txt"
        self.gemini_model_name = GEMINI_MODEL_NAME
        self.gemini_prompt_text = GEMINI_IMAGE_PROMPT
        self._status_icons = {
            0: self._create_status_icon((210, 70, 70, 255)),
            1: self._create_status_icon((230, 190, 70, 255)),
            2: self._create_status_icon((70, 190, 95, 255)),
        }
        self._state_lock = threading.Lock()
        self._top_left_revision = 0
        self._bottom_right_revision = 0
        self._captured_top_left_revision = 0
        self._captured_bottom_right_revision = 0
        self._gemini_request_in_flight = False
        self._answer_letter_icon: str | None = None
        self._free_response_answer_text: str | None = None
        self._hotkey_thread: threading.Thread | None = None
        self._hotkey_thread_id: int | None = None
        self._stop_hotkey_event = threading.Event()

        self.icon = pystray.Icon(
            name="screen-snippet",
            title="Screen Snippet",
            icon=self._create_fallback_icon(),
            menu=pystray.Menu(
                pystray.MenuItem("Open Free Response", self._on_open_free_response, default=True, visible=self._free_response_available),
                pystray.MenuItem("Capture Screenshot", self._on_capture),
                pystray.MenuItem("Next Icon", self._on_next_icon),
                pystray.MenuItem("Next Built-in Icon", self._on_next_predefined_icon),
                pystray.MenuItem("Reload Icons", self._on_reload_icons),
                pystray.MenuItem("Quit", self._on_quit),
            ),
        )

        self.change_icons_from_directory(self.icon_directory)
        self._sync_coordinate_status_icon()

    def _create_status_icon(self, fill_color: tuple[int, int, int, int]) -> Image.Image:
        size = self.predefined_icons.size
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        padding = max(4, size // 8)
        draw.ellipse(
            (padding, padding, size - padding, size - padding),
            fill=fill_color,
            outline=(35, 35, 35, 255),
            width=max(2, size // 16),
        )
        return image

    def _updated_corner_count(self) -> int:
        with self._state_lock:
            top_left_updated = self._top_left_revision > self._captured_top_left_revision
            bottom_right_updated = self._bottom_right_revision > self._captured_bottom_right_revision
        return int(top_left_updated) + int(bottom_right_updated)

    def _sync_coordinate_status_icon(self) -> None:
        with self._state_lock:
            request_in_flight = self._gemini_request_in_flight
            answer_letter_icon = self._answer_letter_icon
            free_response_answer_text = self._free_response_answer_text
        if request_in_flight:
            self._set_loading_icon()
            return
        if free_response_answer_text is not None:
            self.icon.icon = self.predefined_icons.generate("pencil")
            return
        if answer_letter_icon is not None:
            self.icon.icon = self.predefined_icons.generate(f"letter_{answer_letter_icon}")
            return
        updated_count = self._updated_corner_count()
        self.icon.icon = self._status_icons[updated_count]

    def _is_capture_blocked(self) -> bool:
        with self._state_lock:
            return self._gemini_request_in_flight

    def _set_capture_blocked(self, blocked: bool) -> None:
        with self._state_lock:
            self._gemini_request_in_flight = blocked

    def _clear_answer_letter_icon(self) -> None:
        with self._state_lock:
            self._answer_letter_icon = None
            self._free_response_answer_text = None

    def _set_answer_letter_icon(self, answer_letter: str) -> None:
        normalized = answer_letter.upper()
        if normalized not in string.ascii_uppercase:
            raise ValueError("Answer letter must be A-Z")
        with self._state_lock:
            self._answer_letter_icon = normalized
            self._free_response_answer_text = None

    def _set_free_response_answer(self, answer_text: str) -> None:
        cleaned = answer_text.strip()
        if not cleaned:
            raise ValueError("Free response answer cannot be empty")
        with self._state_lock:
            self._free_response_answer_text = cleaned
            self._answer_letter_icon = None

    def _free_response_available(self, _item: Any) -> bool:
        with self._state_lock:
            return self._free_response_answer_text is not None

    def _write_free_response_file(self, answer_text: str) -> Path:
        self.logs_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with self.free_response_answer_file.open("w", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}]\n")
            handle.write(f"{answer_text.strip()}\n")
        return self.free_response_answer_file

    def _open_free_response_in_notepad(self) -> None:
        with self._state_lock:
            answer_text = self._free_response_answer_text
        if answer_text is None:
            return
        answer_file = self._write_free_response_file(answer_text)
        try:
            subprocess.Popen(["notepad.exe", str(answer_file)])
        except OSError:
            return

    def _on_open_free_response(self, _icon: Any, _item: Any) -> None:
        self._open_free_response_in_notepad()

    def _extract_gemini_json(self, response_text: str) -> dict[str, Any] | None:
        compact = response_text.strip()

        if compact.startswith("```"):
            code_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", compact, re.IGNORECASE | re.DOTALL)
            if code_match:
                compact = code_match.group(1).strip()

        try:
            candidate = json.loads(compact)
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            object_match = re.search(r"\{.*\}", compact, re.DOTALL)
            if object_match:
                try:
                    candidate = json.loads(object_match.group(0))
                    if isinstance(candidate, dict):
                        return candidate
                except json.JSONDecodeError:
                    return None

        return None

    def _extract_answer_letter(self, response_text: str) -> str | None:
        compact = response_text.strip()

        parsed_json = self._extract_gemini_json(compact)

        if parsed_json is not None:
            answer_value = parsed_json.get("answer")
            if isinstance(answer_value, str):
                answer_letter = answer_value.strip().upper()
                if re.fullmatch(r"[A-Z]", answer_letter):
                    return answer_letter

        normalized = compact.upper()
        answer_pattern = re.search(
            r"\b(?:ANSWER|CORRECT\s+ANSWER|OPTION|CHOICE)\b\s*[:\-]?\s*\(?\s*([A-Z])\s*\)?",
            normalized,
        )
        if answer_pattern:
            return answer_pattern.group(1)

        standalone_letter = re.search(r"\b([A-Z])\b", normalized)
        if standalone_letter:
            return standalone_letter.group(1)

        return None

    def _extract_free_response_answer(self, response_text: str) -> str | None:
        parsed_json = self._extract_gemini_json(response_text)
        if parsed_json is None:
            return None

        question_type = parsed_json.get("question_type")
        is_free_response = isinstance(question_type, str) and question_type.strip().lower() == "free_response"
        if not is_free_response:
            return None

        free_response_answer = parsed_json.get("free_response_answer")
        if isinstance(free_response_answer, str) and free_response_answer.strip():
            return free_response_answer.strip()

        fallback_answer = parsed_json.get("answer")
        if isinstance(fallback_answer, str) and fallback_answer.strip():
            return fallback_answer.strip()

        return None

    def _read_mouse_position(self) -> tuple[int, int]:
        point = POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("Unable to read mouse cursor position.")
        return int(point.x), int(point.y)

    def _set_top_left_from_mouse(self) -> bool:
        position = self._read_mouse_position()
        with self._state_lock:
            if position == self.top_left:
                return False
            self.top_left = position
            self._top_left_revision += 1
            return True

    def _set_bottom_right_from_mouse(self) -> bool:
        position = self._read_mouse_position()
        with self._state_lock:
            if position == self.bottom_right:
                return False
            self.bottom_right = position
            self._bottom_right_revision += 1
            return True

    def _set_loading_icon(self) -> None:
        self.icon.icon = self.predefined_icons.generate("loading")

    def _notify_gemini_response(self, response_text: str) -> None:
        _ = response_text

    def _log_gemini_error(self, image_path: Path, error_message: str) -> Path:
        self.logs_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with self.gemini_error_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] image={image_path}\n")
            handle.write(f"error={error_message}\n\n")
        return self.gemini_error_log_file

    def _log_gemini_output(self, image_path: Path, response_text: str) -> Path:
        self.logs_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with self.gemini_output_log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] image={image_path}\n")
            handle.write("response=\n")
            handle.write(f"{response_text.strip()}\n\n")
        return self.gemini_output_log_file

    def _wait_for_image_ready(self, image_path: Path) -> None:
        deadline = time.monotonic() + IMAGE_READY_TIMEOUT_SECONDS
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                if image_path.exists() and image_path.is_file() and image_path.stat().st_size > 0:
                    with Image.open(image_path) as image:
                        image.load()
                        width, height = image.size
                        if width > 0 and height > 0:
                            return
            except (OSError, ValueError) as exc:
                last_error = exc

            time.sleep(IMAGE_READY_POLL_SECONDS)

        if last_error is not None:
            raise RuntimeError(f"Screenshot file not ready: {last_error}") from last_error
        raise RuntimeError("Screenshot file not ready before Gemini upload timeout.")

    def _analyze_with_gemini(self, image_path: Path) -> None:
        try:
            response_text = prompt_with_uploaded_image(
                prompt=self.gemini_prompt_text,
                image_path=image_path,
                model_name=self.gemini_model_name,
            )
            self._log_gemini_output(image_path=image_path, response_text=response_text)
            free_response_answer = self._extract_free_response_answer(response_text)
            if free_response_answer is not None:
                self._set_free_response_answer(free_response_answer)
            else:
                answer_letter = self._extract_answer_letter(response_text)
                if answer_letter is not None:
                    self._set_answer_letter_icon(answer_letter)
            self._notify_gemini_response(response_text)
        except RuntimeError as exc:  # pragma: no cover
            log_file = self._log_gemini_error(image_path=image_path, error_message=str(exc))
            _ = log_file
        finally:
            self._set_capture_blocked(False)
            self._sync_coordinate_status_icon()

    def _start_gemini_analysis(self, image_path: Path) -> None:
        threading.Thread(
            target=self._analyze_with_gemini,
            args=(image_path,),
            name="gemini-image-analysis",
            daemon=True,
        ).start()

    def _capture_and_process(self, top_left: tuple[int, int], bottom_right: tuple[int, int]) -> Path:
        if self._is_capture_blocked():
            raise RuntimeError("Gemini is still processing the previous screenshot.")

        self._set_capture_blocked(True)
        self._set_loading_icon()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_directory / f"snippet_{timestamp}.png"
        try:
            saved_path = capture_and_save(top_left, bottom_right, output_file)
            self._wait_for_image_ready(saved_path)
            self._start_gemini_analysis(saved_path)
            return saved_path
        except (OSError, ValueError, RuntimeError):
            self._set_capture_blocked(False)
            self._sync_coordinate_status_icon()
            raise

    def _try_capture_after_corner_updates(self) -> None:
        if self._is_capture_blocked():
            return

        with self._state_lock:
            both_updated = (
                self._top_left_revision > self._captured_top_left_revision
                and self._bottom_right_revision > self._captured_bottom_right_revision
            )
            if not both_updated:
                return
            top_left = self.top_left
            bottom_right = self.bottom_right
            top_left_revision = self._top_left_revision
            bottom_right_revision = self._bottom_right_revision

        try:
            self._set_loading_icon()
            self._capture_and_process(top_left, bottom_right)
            with self._state_lock:
                self._captured_top_left_revision = top_left_revision
                self._captured_bottom_right_revision = bottom_right_revision
        except (OSError, ValueError, RuntimeError) as exc:  # pragma: no cover
            _ = exc
        finally:
            self._sync_coordinate_status_icon()

    def _on_hotkey(self, hotkey_id: int) -> None:
        self._clear_answer_letter_icon()
        if hotkey_id == HOTKEY_ID_TOP_LEFT:
            self._set_top_left_from_mouse()
            self._sync_coordinate_status_icon()
            self._try_capture_after_corner_updates()
        elif hotkey_id == HOTKEY_ID_BOTTOM_RIGHT:
            self._set_bottom_right_from_mouse()
            self._sync_coordinate_status_icon()
            self._try_capture_after_corner_updates()

    def _hotkey_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._hotkey_thread_id = int(kernel32.GetCurrentThreadId())
        register_top_left = bool(user32.RegisterHotKey(None, HOTKEY_ID_TOP_LEFT, MOD_NOREPEAT, VK_LEFT))
        register_bottom_right = bool(
            user32.RegisterHotKey(None, HOTKEY_ID_BOTTOM_RIGHT, MOD_NOREPEAT, VK_RIGHT)
        )

        if not register_top_left or not register_bottom_right:
            if register_top_left:
                user32.UnregisterHotKey(None, HOTKEY_ID_TOP_LEFT)
            if register_bottom_right:
                user32.UnregisterHotKey(None, HOTKEY_ID_BOTTOM_RIGHT)
            self._hotkey_thread_id = None
            return

        msg = wintypes.MSG()
        while not self._stop_hotkey_event.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self._on_hotkey(int(msg.wParam))

        user32.UnregisterHotKey(None, HOTKEY_ID_TOP_LEFT)
        user32.UnregisterHotKey(None, HOTKEY_ID_BOTTOM_RIGHT)
        self._hotkey_thread_id = None

    def _start_hotkey_listener(self) -> None:
        if self._hotkey_thread is not None:
            return
        self._stop_hotkey_event.clear()
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, name="tray-hotkey-listener", daemon=True)
        self._hotkey_thread.start()

    def _stop_hotkey_listener(self) -> None:
        if self._hotkey_thread is None:
            return
        self._stop_hotkey_event.set()
        if self._hotkey_thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, WM_QUIT, 0, 0)
        self._hotkey_thread.join(timeout=1.0)
        self._hotkey_thread = None

    def _load_icon_image(self, icon_path: Path) -> Image.Image:
        with Image.open(icon_path) as image:
            return image.copy()

    def _create_fallback_icon(self) -> Image.Image:
        return self.predefined_icons.generate("loading")

    def _list_icon_files(self, img_directory: str | Path) -> list[Path]:
        directory = Path(img_directory)
        if not directory.exists() or not directory.is_dir():
            return []

        return sorted(
            [
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_ICON_EXTENSIONS
            ]
        )

    def change_icons_from_directory(self, img_directory: str | Path) -> int:
        """Load icons from a directory and apply the first icon.

        Returns:
            Number of icon files loaded.
        """
        self.icon_directory = Path(img_directory)
        self.icon_paths = self._list_icon_files(self.icon_directory)
        self.icon_index = 0

        if self.icon_paths:
            self.icon.icon = self._load_icon_image(self.icon_paths[0])
        else:
            self.predefined_icon_index = 0
            self.icon.icon = self.predefined_icons.generate(self.predefined_icon_names[0])

        return len(self.icon_paths)

    def _set_next_icon(self) -> None:
        if not self.icon_paths:
            self._set_next_predefined_icon()
            return

        self.icon_index = (self.icon_index + 1) % len(self.icon_paths)
        self.icon.icon = self._load_icon_image(self.icon_paths[self.icon_index])

    def _set_next_predefined_icon(self) -> None:
        self.predefined_icon_index = (self.predefined_icon_index + 1) % len(self.predefined_icon_names)
        name = self.predefined_icon_names[self.predefined_icon_index]
        self.icon.icon = self.predefined_icons.generate(name)

    def _capture_now(self) -> Path:
        return self._capture_and_process(self.top_left, self.bottom_right)

    def _on_capture(self, _icon: Any, _item: Any) -> None:
        if self._is_capture_blocked():
            return

        try:
            self._capture_now()
        except (OSError, ValueError, RuntimeError) as exc:  # pragma: no cover
            _ = exc

    def _on_next_icon(self, _icon: Any, _item: Any) -> None:
        self._set_next_icon()

    def _on_next_predefined_icon(
        self,
        _icon: Any,
        _item: Any,
    ) -> None:
        self._set_next_predefined_icon()

    def _on_reload_icons(self, _icon: Any, _item: Any) -> None:
        self.change_icons_from_directory(self.icon_directory)

    def _on_quit(self, _icon: Any, _item: Any) -> None:
        self._stop_hotkey_listener()
        self.icon.stop()

    def run(self) -> None:
        self._start_hotkey_listener()
        self.icon.run()


def run_tray_app(
    top_left: tuple[int, int] = (100, 100),
    bottom_right: tuple[int, int] = (700, 500),
    icon_directory: str | Path = "icons",
) -> None:
    app = TrayScreenshotApp(
        top_left=top_left,
        bottom_right=bottom_right,
        icon_directory=icon_directory,
    )
    app.run()
