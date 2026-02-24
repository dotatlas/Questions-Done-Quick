from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError, RetryError
from dotenv import load_dotenv

DEFAULT_MODEL_NAME = "gemini-2.5-flash"


def initialize_gemini(api_key: str | None = None) -> None:
    load_dotenv()
    resolved_key = api_key or os.getenv("GEMINI_API_KEY")
    if not resolved_key:
        raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env or pass api_key.")
    genai.configure(api_key=resolved_key)


def upload_image(image_path: str | Path) -> Any:
    file_path = Path(image_path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Image file not found: {file_path}")
    return genai.upload_file(path=str(file_path))


def prompt_with_uploaded_image(
    prompt: str,
    image_path: str | Path,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | None = None,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    initialize_gemini(api_key=api_key)
    try:
        uploaded_image = upload_image(image_path)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content([prompt, uploaded_image])
    except (GoogleAPIError, RetryError, OSError, ValueError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    raise RuntimeError("Gemini returned an empty response.")


def prompt_with_uploaded_file(
    prompt: str,
    uploaded_file: Any,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | None = None,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    initialize_gemini(api_key=api_key)
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content([prompt, uploaded_file])
    except (GoogleAPIError, RetryError, OSError, ValueError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc

    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    raise RuntimeError("Gemini returned an empty response.")
