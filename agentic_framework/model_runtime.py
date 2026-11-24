import os
from pathlib import Path
from urllib import response
import json
import re

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

from contextlib import contextmanager
from contextvars import ContextVar

import logging
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from huggingface_hub.errors import HfHubHTTPError


logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_PROVIDER_ATTEMPTS = 3
MAX_RETRY_DELAY = 30.0


class ModelUnavailableError(RuntimeError):
    """The provider remained unavailable within our retry policy."""



# 1. Load environment variables from this module's .env
load_dotenv(Path(__file__).with_name(".env"))

# 2. Retrieve configuration
token = os.environ["HF_TOKEN"]
model = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-9B")
fallback_model = os.getenv("FALLBACK_MODEL_NAME", "").strip()

# 3. Initialize the Hugging Face inference client
client = InferenceClient(
    api_key=token,
    provider="deepinfra", 
)



def _retry_after_seconds(response) -> float | None:
    """Read the provider's minimum waiting time, if valid."""
    value = response.headers.get("Retry-After")

    if value is None:
        return None

    value = value.strip()

    if value.isascii() and value.isdigit():
        return float(value)

    try:
        retry_at = parsedate_to_datetime(value)

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)

        return max(
            0.0,
            (
                retry_at - datetime.now(timezone.utc)
            ).total_seconds(),
        )
    except (TypeError, ValueError, OverflowError):
        return None


_active_model: ContextVar[str | None] = ContextVar(
    "active_analysis_model",
    default=None,
)


@contextmanager
def model_session():
    """Keep model selection within one analytical question."""
    token = _active_model.set(model)
    try:
        yield
    finally:
        _active_model.reset(token)


def _create_completion_with_retries(**kwargs):
    """Retry temporary HTTP failures for one model request."""
    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        try:
            return client.chat.completions.create(**kwargs)

        except HfHubHTTPError as exc:
            response = exc.response
            status = (
                response.status_code
                if response is not None
                else None
            )

            # Authentication, billing and invalid requests need
            # correction, rather than repeated identical requests.
            if status not in RETRYABLE_STATUSES:
                raise

            if attempt == MAX_PROVIDER_ATTEMPTS:
                raise ModelUnavailableError(
                    f"Model request failed after {attempt} attempts "
                    f"(HTTP {status})."
                ) from exc

            # Approximately 2 seconds, then 4 seconds.
            delay = (
                2 ** attempt / 4
                + random.uniform(0.0, 1.0)
            )

            retry_after = _retry_after_seconds(response)

            if retry_after is not None:
                if retry_after > MAX_RETRY_DELAY:
                    raise ModelUnavailableError(
                        "Provider requested a wait longer than "
                        "our retry policy allows."
                    ) from exc

                delay = max(delay, retry_after)

            logger.warning(
                "Model request returned HTTP %s; "
                "retrying in %.2fs (next attempt %s/%s).",
                status,
                delay,
                attempt + 1,
                MAX_PROVIDER_ATTEMPTS,
            )

            time.sleep(delay)


def _request_for_model(kwargs, selected_model):
    """Copy request options and apply model-specific settings."""
    request = dict(kwargs)
    request["model"] = selected_model

    if selected_model == "Qwen/Qwen3-235B-A22B-Instruct-2507":
        extra = dict(request.get("extra_body") or {})
        extra.pop("chat_template_kwargs", None)
        extra.pop("enable_thinking", None)
        extra.pop("reasoning", None)

        if extra:
            request["extra_body"] = extra
        else:
            request.pop("extra_body", None)

    return request


def create_completion(**kwargs):
    """Switch early, then retain the fallback within this question."""
    # Standalone calls, such as the CLI smoke test, get a short session.
    if _active_model.get() is None:
        with model_session():
            return create_completion(**kwargs)

    selected_model = _active_model.get()
    request = _request_for_model(kwargs, selected_model)

    can_switch = (
        selected_model == model
        and bool(fallback_model)
        and fallback_model != model
    )

    # Already using the fallback, or no distinct fallback configured.
    if not can_switch:
        return _create_completion_with_retries(**request)

    # One primary attempt before considering the fallback.
    try:
        return client.chat.completions.create(**request)

    except HfHubHTTPError as exc:
        response = exc.response
        status = (
            response.status_code
            if response is not None
            else None
        )

        if status not in RETRYABLE_STATUSES:
            raise

        # Both models use the same provider/account. Respect its wait.
        delay = (
            _retry_after_seconds(response)
            if response is not None
            else None
        )

        if delay is not None and delay > MAX_RETRY_DELAY:
            raise ModelUnavailableError(
                "Provider requested a wait longer than "
                "our retry policy allows."
            ) from exc

        if delay is not None and delay > 0:
            time.sleep(delay)

        logger.warning(
            "Model %s returned HTTP %s; trying fallback %s.",
            selected_model,
            status,
            fallback_model,
        )

        fallback_request = _request_for_model(
            kwargs,
            fallback_model,
        )
        result = _create_completion_with_retries(
            **fallback_request
        )

        # Persist the choice only after the provider call succeeds.
        _active_model.set(fallback_model)

        logger.info(
            "Using %s for the remaining calls in this question.",
            fallback_model,
        )
        return result