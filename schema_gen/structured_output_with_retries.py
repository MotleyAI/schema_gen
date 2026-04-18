import importlib
import re
import sys
import types
from typing import Any, Callable, Type, TypeVar

import tenacity
from pydantic import BaseModel, ValidationError


# ---------------------------------------------------------------------------
# Import-time shim for `instructor`.
#
# instructor >=1.10 eagerly imports every provider shim (openai, anthropic,
# mistralai, bedrock, cohere, …) from `instructor.providers.__init__`. When
# an optional provider's top-level symbol isn't available at the expected
# path — e.g. mistralai 2.x split its package and no longer exposes a
# top-level `Mistral` class — `import instructor` raises ImportError even
# though we never touch that provider. See 567-labs/instructor#2205 (open)
# and PR #2206 (closed, not merged).
#
# We only need `instructor.from_litellm`, so we retry the import and, on
# each failure, install a dummy stub for whatever name or module is missing,
# then try again. As long as the shimmed provider is never actually called,
# this is safe.
# ---------------------------------------------------------------------------

_CANNOT_IMPORT_NAME_RE = re.compile(r"cannot import name '([^']+)' from '([^']+)'")
_NO_MODULE_RE = re.compile(r"No module named '([^']+)'")


def _import_instructor_with_stubs(max_shims: int = 20):
    """Import instructor, stubbing missing provider symbols discovered at runtime."""
    for _ in range(max_shims):
        # Drop any partial instructor state so each retry is a clean import.
        for name in [n for n in sys.modules if n == "instructor" or n.startswith("instructor.")]:
            del sys.modules[name]
        try:
            return importlib.import_module("instructor")
        except ImportError as exc:
            msg = str(exc)
            m = _CANNOT_IMPORT_NAME_RE.search(msg)
            if m:
                attr_name, module_name = m.group(1), m.group(2)
                try:
                    target = importlib.import_module(module_name)
                except ImportError:
                    target = types.ModuleType(module_name)
                    sys.modules[module_name] = target
                setattr(target, attr_name, type(attr_name, (), {}))
                continue
            m = _NO_MODULE_RE.search(msg)
            if m:
                module_name = m.group(1)
                sys.modules[module_name] = types.ModuleType(module_name)
                continue
            # Unknown ImportError shape — don't silently mask it.
            raise
    raise RuntimeError(
        f"Could not import `instructor` after {max_shims} shim attempts — "
        "unexpected ImportError pattern."
    )


instructor = _import_instructor_with_stubs()

from litellm import completion  # noqa: E402  (after the instructor shim)

T = TypeVar("T")


def structured_output_with_retries(
    schema: Type[T],
    messages: list[dict],
    validation_callable: Callable[[T], Any],
    model: str = "openai/gpt-4.1-mini",
    max_attempts: int = 3,
    retry_exceptions: tuple[Type[Exception], ...] = (ValidationError,),
) -> Any:
    """
    Feed messages to an LLM, forcing it to return a valid instance of `schema`.
    On each attempt, the result is passed to `validation_callable`.
    If it raises, the exception text is appended to the conversation and the LLM retries.
    Returns the return value of `validation_callable` on success.

    Args:
        schema:               Pydantic model class defining the expected output shape.
        messages:             OpenAI-style message list, e.g. [{"role": "user", "content": "..."}].
                              May include image content blocks for vision models.
        validation_callable:  Called with the validated Pydantic instance. Its return value
                              is returned on success; any exception triggers a retry.
        model:                LiteLLM model string (supports all providers).
        max_attempts:         Maximum number of LLM calls before giving up.
        retry_exceptions:     Exception types that trigger a retry. Defaults to ValidationError
                              (covers Pydantic field/model validators). Add your own custom
                              exception classes to catch business-rule failures too.
    """
    client = instructor.from_litellm(completion)

    # Wrap the Pydantic schema to also run the validation callable,
    # so its exceptions are caught by Instructor's retry loop.
    class WrappedSchema(schema):  # type: ignore[valid-type]
        _validation_result: Any = None

        def model_post_init(self, __context: Any) -> None:
            # Store the callable's return value so we can retrieve it after .create()
            object.__setattr__(self, "_validation_result", validation_callable(self))

    try:
        result: WrappedSchema = client.chat.completions.create(
            model=model,
            response_model=WrappedSchema,
            messages=messages,
            max_retries=tenacity.Retrying(
                stop=tenacity.stop_after_attempt(max_attempts),
                retry=tenacity.retry_if_exception_type(retry_exceptions),
                # NOTE: no reraise=True — we want tenacity to raise RetryError
                # on exhaustion (with __cause__ set to the last exception) so
                # we can wrap it in our own RuntimeError below. With reraise,
                # the original exception would bypass our handler.
            ),
        )
        return result._validation_result

    except tenacity.RetryError as e:
        raise RuntimeError(
            f"structured_output_with_retries failed after {max_attempts} attempts"
        ) from e.__cause__


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pydantic import field_validator

    class MovieReview(BaseModel):
        title: str
        rating: float
        summary: str

        @field_validator("rating")
        @classmethod
        def rating_in_range(cls, v: float) -> float:
            if not (0.0 <= v <= 10.0):
                raise ValueError(f"Rating must be between 0 and 10, got {v}")
            return v

    def validate_and_transform(review: MovieReview) -> dict:
        # Custom business logic beyond Pydantic — also retried on failure
        if len(review.summary) < 20:
            raise ValueError("Summary is too short to be useful")
        return {
            "title": review.title.upper(),
            "rating": review.rating,
            "summary": review.summary,
        }

    output = structured_output_with_retries(
        schema=MovieReview,
        messages=[
            {
                "role": "user",
                "content": "Review the movie Inception in one short sentence.",
            }
        ],
        validation_callable=validate_and_transform,
        model="openai/gpt-4.1-mini",
        max_attempts=3,
        retry_exceptions=(ValidationError, ValueError),
    )

    print(output)
