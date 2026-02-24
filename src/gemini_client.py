from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError, RetryError
from dotenv import load_dotenv

DEFAULT_MODEL_NAME = "gemini-3.1-pro-preview"
TEST_MODE_API_KEY = "test"
TEST_FREE_RESPONSE_JSON = (
    '{"question_type":"free_response","explanation":"Test mode response with intentionally long text to simulate notification overflow behavior.",'
    '"verification":"Test mode bypassed Gemini and returned a stress-test payload with long free-response content.",'
    '"answer":"This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays. This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays. This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays. This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays.",'
    '"free_response_answer":"This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays. This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays. This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays. This is a predefined free response answer for testing. This sentence is repeated to create a very long message that is likely to exceed notification limits in some system trays."}'
)
MODEL_FALLBACK_PRIORITY = [
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash-lite",
]


def _resolve_api_key(api_key: str | None = None) -> str | None:
    load_dotenv()
    return api_key or os.getenv("GEMINI_API_KEY")


def _resolve_api_key_candidates(api_key: str | None = None) -> list[str]:
    load_dotenv()
    if api_key:
        return [api_key]

    candidates: list[str] = []
    env_var_names = (
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_SECOND",
        "GEMINI_API_KEY_THIRD",
        "GEMINI_API_KEY_FOURTH",
    )
    for env_var_name in env_var_names:
        raw_value = os.getenv(env_var_name)
        if raw_value is None:
            continue
        cleaned_value = raw_value.strip()
        if not cleaned_value or cleaned_value in candidates:
            continue
        candidates.append(cleaned_value)
    return candidates


def _describe_key_for_log(api_key_value: str) -> str:
    cleaned = api_key_value.strip()
    if not cleaned:
        return "<empty>"
    if len(cleaned) <= 8:
        return cleaned
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _is_test_mode(api_key: str | None = None) -> bool:
    resolved_key = _resolve_api_key(api_key)
    if resolved_key is None:
        return False
    return resolved_key.strip().lower() == TEST_MODE_API_KEY


def initialize_gemini(api_key: str | None = None) -> None:
    resolved_key = _resolve_api_key(api_key)
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


def _generate_with_api_key_fallback(
    prompt: str,
    content_part: Any,
    model_name: str,
    api_key: str | None = None,
) -> str:
    api_key_candidates = _resolve_api_key_candidates(api_key=api_key)
    if not api_key_candidates:
        raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env or pass api_key.")

    last_error: Exception | None = None
    for index, candidate_key in enumerate(api_key_candidates):
        key_label = f"key #{index + 1}"
        print(f"[Gemini] Using {key_label}: {_describe_key_for_log(candidate_key)}")
        try:
            initialize_gemini(api_key=candidate_key)
            return _generate_with_model_fallback(
                prompt=prompt,
                content_part=content_part,
                primary_model=model_name,
            )
        except (GoogleAPIError, RetryError, OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            has_another_key = index < len(api_key_candidates) - 1
            if has_another_key:
                print(f"[Gemini] {key_label} failed; retrying with next key. Error: {exc}")
                continue
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    if last_error is not None:
        raise RuntimeError(f"Gemini request failed after API key fallback: {last_error}") from last_error
    raise RuntimeError("Gemini request failed after API key fallback.")


def _generate_from_image_with_api_key_fallback(
    prompt: str,
    image_path: str | Path,
    model_name: str,
    api_key: str | None = None,
) -> str:
    api_key_candidates = _resolve_api_key_candidates(api_key=api_key)
    if not api_key_candidates:
        raise ValueError("Missing Gemini API key. Set GEMINI_API_KEY in .env or pass api_key.")

    last_error: Exception | None = None
    for index, candidate_key in enumerate(api_key_candidates):
        key_label = f"key #{index + 1}"
        print(f"[Gemini] Using {key_label}: {_describe_key_for_log(candidate_key)}")
        try:
            initialize_gemini(api_key=candidate_key)
            uploaded_image = upload_image(image_path)
            return _generate_with_model_fallback(
                prompt=prompt,
                content_part=uploaded_image,
                primary_model=model_name,
            )
        except (GoogleAPIError, RetryError, OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            has_another_key = index < len(api_key_candidates) - 1
            if has_another_key:
                print(f"[Gemini] {key_label} failed; retrying with next key. Error: {exc}")
                continue
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    if last_error is not None:
        raise RuntimeError(f"Gemini request failed after API key fallback: {last_error}") from last_error
    raise RuntimeError("Gemini request failed after API key fallback.")


def prompt_with_uploaded_image(
    prompt: str,
    image_path: str | Path,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | None = None,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    if _is_test_mode(api_key=api_key):
        return TEST_FREE_RESPONSE_JSON

    try:
        return _generate_from_image_with_api_key_fallback(
            prompt=prompt,
            image_path=image_path,
            model_name=model_name,
            api_key=api_key,
        )
    except (GoogleAPIError, RetryError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc


def prompt_with_uploaded_file(
    prompt: str,
    uploaded_file: Any,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | None = None,
) -> str:
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")

    if _is_test_mode(api_key=api_key):
        return TEST_FREE_RESPONSE_JSON

    try:
        return _generate_with_api_key_fallback(
            prompt=prompt,
            content_part=uploaded_file,
            model_name=model_name,
            api_key=api_key,
        )
    except (GoogleAPIError, RetryError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Gemini request failed: {exc}") from exc
