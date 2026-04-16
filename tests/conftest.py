"""Shared test fixtures for schema_gen tests."""

from typing import Any, List

import pytest


class _FakeCompletions:
    """Stand-in for `instructor_client.chat.completions`."""

    def __init__(self, script: List[Any]):
        self._script = list(script)
        self.calls = 0
        self.last_kwargs: dict | None = None

    def create(self, *, model, response_model, messages, max_retries, **_kwargs):
        self.last_kwargs = {
            "model": model,
            "response_model": response_model,
            "messages": messages,
        }

        def _attempt():
            self.calls += 1
            if not self._script:
                raise RuntimeError("test script exhausted before max_attempts reached")
            step = self._script.pop(0)
            if isinstance(step, BaseException):
                raise step
            # step is a kwargs dict — construct the response_model.
            # Invalid payloads will raise ValidationError here; valid payloads
            # will also invoke WrappedSchema.model_post_init, which runs the
            # validation_callable and may raise whatever it likes.
            return response_model(**step)

        # `max_retries` is the tenacity.Retrying instance passed in by the
        # caller. Invoking it runs _attempt under the retry policy.
        return max_retries(_attempt)


class FakeInstructorClient:
    """Drop-in replacement for `instructor.from_litellm(completion)` return value.

    The `script` is a list of either:
      - dict: kwargs passed to `response_model(**kwargs)`; invalid data raises
              ValidationError, valid data triggers the validation_callable.
      - Exception instance: raised directly in place of calling the model.
    """

    def __init__(self, script: List[Any]):
        self.completions = _FakeCompletions(script)
        # instructor exposes `client.chat.completions.create(...)`
        self.chat = type("_FakeChat", (), {"completions": self.completions})()


@pytest.fixture
def patch_instructor(monkeypatch):
    """Install a scripted fake instructor client.

    Usage in a test:
        client = patch_instructor([{"name": "ok", "count": 1}])
        ...
        assert client.completions.calls == 1
    """

    def install(script: List[Any]) -> FakeInstructorClient:
        client = FakeInstructorClient(script)
        monkeypatch.setattr(
            "schema_gen.structured_output_with_retries.instructor.from_litellm",
            lambda _completion: client,
        )
        return client

    return install
