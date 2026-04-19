"""Tests for schema_gen.structured_output_with_retries."""

import pytest
from pydantic import BaseModel, ValidationError

from schema_gen.structured_output_with_retries import structured_output_with_retries


class SampleSchema(BaseModel):
    """Minimal Pydantic schema used by these tests."""

    name: str
    count: int


def test_success_returns_validation_callable_result(patch_instructor):
    """On first-attempt success, the helper returns validation_callable's return value."""
    client = patch_instructor([{"name": "foo", "count": 1}])

    result = structured_output_with_retries(
        schema=SampleSchema,
        messages=[{"role": "user", "content": "hi"}],
        validation_callable=lambda s: {"upper_name": s.name.upper(), "count": s.count},
        max_attempts=3,
    )

    assert result == {"upper_name": "FOO", "count": 1}
    assert client.completions.calls == 1
    # Sanity-check the args that reached the fake client.
    assert client.completions.last_kwargs["model"]  # whatever default
    assert client.completions.last_kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_retry_on_validation_error_then_success(patch_instructor):
    """ValidationError on attempt 1 triggers a retry; attempt 2 succeeds."""
    client = patch_instructor(
        [
            # count=str triggers Pydantic ValidationError
            {"name": "foo", "count": "not-an-int"},
            {"name": "bar", "count": 2},
        ]
    )

    result = structured_output_with_retries(
        schema=SampleSchema,
        messages=[{"role": "user", "content": "hi"}],
        validation_callable=lambda s: s.model_dump(),
        max_attempts=3,
    )

    assert result == {"name": "bar", "count": 2}
    assert client.completions.calls == 2


def test_retry_on_callable_value_error(patch_instructor):
    """ValueError raised by validation_callable retries under the default retry_exceptions.

    Pydantic v2 wraps any ValueError raised from `model_post_init` into a
    ValidationError, which is in the default retry_exceptions, so the retry
    fires without the caller needing to add ValueError explicitly.
    """
    callable_calls = {"n": 0}

    def rejects_first(s):
        callable_calls["n"] += 1
        if callable_calls["n"] == 1:
            raise ValueError("first payload is semantically wrong")
        return s.model_dump()

    client = patch_instructor(
        [
            {"name": "foo", "count": 1},
            {"name": "bar", "count": 2},
        ]
    )

    result = structured_output_with_retries(
        schema=SampleSchema,
        messages=[{"role": "user", "content": "hi"}],
        validation_callable=rejects_first,
        max_attempts=3,
    )

    assert result == {"name": "bar", "count": 2}
    assert client.completions.calls == 2
    assert callable_calls["n"] == 2


def test_exhausts_retries_raises_runtime_error(patch_instructor):
    """After max_attempts failed attempts, RuntimeError wraps the final exception."""
    client = patch_instructor(
        [
            {"name": "foo", "count": "bad1"},
            {"name": "foo", "count": "bad2"},
            {"name": "foo", "count": "bad3"},
        ]
    )

    with pytest.raises(RuntimeError) as exc_info:
        structured_output_with_retries(
            schema=SampleSchema,
            messages=[{"role": "user", "content": "hi"}],
            validation_callable=lambda s: s.model_dump(),
            max_attempts=3,
        )

    assert "failed after 3 attempts" in str(exc_info.value)
    assert client.completions.calls == 3
    # The underlying ValidationError should be chained.
    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_callable_exception_not_in_retry_exceptions_is_not_retried(patch_instructor):
    """Exceptions not matching retry_exceptions bypass the retry loop and propagate.

    Uses a custom exception class (not ValueError/TypeError/AssertionError) so
    Pydantic's model_post_init doesn't wrap it into a ValidationError. The
    default retry_exceptions=(ValidationError,) should then leave this
    exception untouched.
    """

    class _NonRetryable(Exception):
        pass

    call_count = {"n": 0}

    def always_raises(s):
        call_count["n"] += 1
        raise _NonRetryable("no good")

    client = patch_instructor(
        [
            {"name": "foo", "count": 1},
            {"name": "bar", "count": 2},  # never reached
        ]
    )

    with pytest.raises(_NonRetryable, match="no good"):
        structured_output_with_retries(
            schema=SampleSchema,
            messages=[{"role": "user", "content": "hi"}],
            validation_callable=always_raises,
            max_attempts=3,
        )

    # Only one attempt — custom exception isn't in default retry_exceptions.
    assert client.completions.calls == 1
    assert call_count["n"] == 1
