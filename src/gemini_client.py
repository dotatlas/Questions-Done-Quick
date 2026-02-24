from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError, RetryError
from dotenv import load_dotenv

DEFAULT_MODEL_NAME = "gemini-3.1-pro-preview"
MODEL_FALLBACK_PRIORITY = [
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
]


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


def _is_daily_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    has_quota_signal = any(
        token in message
        for token in (
            "quota",
            "quota exceeded",
            "exceeded your current quota",
            "generate_content_free_tier_requests",
            "generaterequestsperdayperprojectpermodel-freetier",
            "resource_exhausted",
            "429",
        )
    )
    has_scope_signal = any(
        token in message
        for token in (
            "daily",
            "per day",
            "perday",
            "free_tier",
            "freetier",
        )
    )
    return has_quota_signal and has_scope_signal


def _model_fallback_order(primary_model: str) -> list[str]:
    ordered_models = list(MODEL_FALLBACK_PRIORITY)
    if primary_model in ordered_models:
        ordered_models = [primary_model, *[name for name in ordered_models if name != primary_model]]
        return ordered_models

    ordered_models.insert(0, primary_model)
    for model_name in MODEL_FALLBACK_PRIORITY:
        if model_name not in ordered_models:
            ordered_models.append(model_name)
    return ordered_models


def _generate_with_model_fallback(prompt: str, content_part: Any, primary_model: str) -> str:
    last_error: Exception | None = None
    for model_name in _model_fallback_order(primary_model):
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, content_part])
            text = getattr(response, "text", None)
            if isinstance(text, str) and text.strip():
                return text
            raise RuntimeError("Gemini returned an empty response.")
        except (GoogleAPIError, RetryError, OSError, ValueError) as exc:
            last_error = exc
            if _is_daily_quota_error(exc):
                continue
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    if last_error is not None:
        raise RuntimeError(f"Gemini request failed after model fallback: {last_error}") from last_error
    raise RuntimeError("Gemini request failed after model fallback.")


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
        return _generate_with_model_fallback(prompt=prompt, content_part=uploaded_image, primary_model=model_name)
    except (GoogleAPIError, RetryError, OSError, ValueError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


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
        return _generate_with_model_fallback(prompt=prompt, content_part=uploaded_file, primary_model=model_name)
    except (GoogleAPIError, RetryError, OSError, ValueError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc
