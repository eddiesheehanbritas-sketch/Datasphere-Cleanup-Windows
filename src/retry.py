import asyncio
import functools
from typing import Optional, List
from src.logging_setup import get_logger

try:
    # Playwright's base error type covers TimeoutError and navigation/target-closed errors.
    from playwright.async_api import Error as _PlaywrightError
except Exception:  # pragma: no cover - playwright always present in this project
    _PlaywrightError = ()

logger = get_logger("retry")

# Only these are retried. They are transient/environmental: Playwright timeouts and
# navigation/target errors (_PlaywrightError), asyncio timeouts, and the code's own
# RuntimeError signals for "not settled yet" conditions (e.g. "tile not visible at
# deletion time"). Deterministic programming bugs — KeyError, AttributeError, TypeError,
# ValueError — are NOT retried: retrying them just burns len(backoff)+1 attempts with long
# sleeps per item (minutes across a Stage 2 run) before the same error re-raises. Those
# re-raise immediately so a systemic breakage surfaces fast instead of looping silently.
_RETRYABLE = (_PlaywrightError, asyncio.TimeoutError, RuntimeError) if _PlaywrightError else (asyncio.TimeoutError, RuntimeError)


def backoff_from_cfg(cfg: dict) -> List[float]:
    """Extract retry backoff schedule from config, falling back to default."""
    try:
        return list(cfg["retry"]["backoff_seconds"])
    except (KeyError, TypeError):
        return [5, 15, 60]


def with_retry(backoff_seconds: Optional[List[float]] = None):
    """
    Async retry decorator with backoff. Total attempts = len(backoff_seconds) + 1.
    Waits backoff_seconds[i] after attempt i before retrying.

    Only transient exceptions (see _RETRYABLE) are retried; deterministic errors
    (KeyError/AttributeError/TypeError/ValueError, etc.) re-raise immediately so a
    real bug is not masked behind minutes of retry/sleep.
    """
    if backoff_seconds is None:
        backoff_seconds = [5, 15, 60]

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt, wait in enumerate(backoff_seconds, start=1):
                try:
                    return await func(*args, **kwargs)
                except _RETRYABLE as exc:
                    logger.warning(
                        f"{func.__name__} attempt {attempt} failed: {exc} — retrying in {wait}s"
                    )
                    await asyncio.sleep(wait)
                except Exception as exc:
                    logger.error(
                        f"{func.__name__} failed with non-retryable {type(exc).__name__}: {exc} — not retrying"
                    )
                    raise
            # Final attempt — let any exception propagate
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                logger.error(f"{func.__name__} failed after {len(backoff_seconds) + 1} attempt(s): {exc}")
                raise
        return wrapper
    return decorator
