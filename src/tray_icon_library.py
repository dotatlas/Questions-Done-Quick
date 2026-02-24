from __future__ import annotations

import string
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


class PredefinedTrayIcons:
    """Small icon library for system tray usage."""

    def __init__(self, size: int = 64) -> None:
        self.size = size

    def available_names(self) -> list[str]:
        return ["loading", "question", "pencil", *[f"letter_{letter}" for letter in string.ascii_uppercase]]

    def generate(self, name: str) -> Image.Image:
        normalized = name.strip().lower()

        if normalized == "loading":
            return self.loading_wheel_icon()
        if normalized == "question":
            return self.question_mark_icon()
        if normalized == "pencil":
            return self.pencil_icon()
        if normalized.startswith("letter_") and len(normalized) == len("letter_x"):
            return self.letter_icon(normalized[-1].upper())

        raise ValueError(f"Unknown icon name: {name}")

    def loading_wheel_icon(self) -> Image.Image:
        image = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        center = self.size // 2
        outer = self.size - 10
        inner = self.size - 24

        draw.ellipse(
            (
                center - outer // 2,
                center - outer // 2,
                center + outer // 2,
                center + outer // 2,
            ),
            outline=(80, 80, 80, 255),
            width=6,
        )
        draw.arc(
            (
                center - outer // 2,
                center - outer // 2,
                center + outer // 2,
                center + outer // 2,
            ),
            start=290,
            end=30,
            fill=(80, 170, 255, 255),
            width=7,
        )
        draw.ellipse(
            (
                center - inner // 2,
                center - inner // 2,
                center + inner // 2,
                center + inner // 2,
            ),
            fill=(32, 32, 32, 255),
        )
        return image

    def question_mark_icon(self) -> Image.Image:
        image = Image.new("RGBA", (self.size, self.size), (30, 70, 150, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=34)

        bbox = draw.textbbox((0, 0), "?", font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self.size - text_width) // 2
        y = (self.size - text_height) // 2 - 2

        draw.text((x, y), "?", font=font, fill=(255, 255, 255, 255))
        return image

    def letter_icon(self, letter: str) -> Image.Image:
        if letter.upper() not in string.ascii_uppercase:
            raise ValueError("Letter must be A-Z")

        image = Image.new("RGBA", (self.size, self.size), (20, 20, 20, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=34)
        content = letter.upper()

        bbox = draw.textbbox((0, 0), content, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self.size - text_width) // 2
        y = (self.size - text_height) // 2 - 2

        draw.rounded_rectangle((4, 4, self.size - 4, self.size - 4), radius=10, fill=(45, 45, 45, 255))
        draw.text((x, y), content, font=font, fill=(120, 230, 120, 255))
        return image

    def pencil_icon(self) -> Image.Image:
        image = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((6, 6, self.size - 6, self.size - 6), radius=10, fill=(36, 36, 36, 255))
        draw.polygon(
            [
                (16, self.size - 18),
                (22, self.size - 12),
                (self.size - 14, 20),
                (self.size - 20, 14),
            ],
            fill=(244, 193, 84, 255),
        )
        draw.polygon(
            [
                (self.size - 14, 20),
                (self.size - 9, 15),
                (self.size - 15, 9),
                (self.size - 20, 14),
            ],
            fill=(232, 125, 92, 255),
        )
        draw.polygon(
            [
                (16, self.size - 18),
                (12, self.size - 9),
                (22, self.size - 12),
            ],
            fill=(226, 226, 226, 255),
        )

        return image

    def all_letter_icons(self) -> dict[str, Image.Image]:
        return {letter: self.letter_icon(letter) for letter in string.ascii_uppercase}


def get_default_icon_names() -> Iterable[str]:
    return PredefinedTrayIcons().available_names()