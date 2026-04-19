"""Tests for schema_gen.llm_generator."""

from pydantic import ValidationError

from schema_gen import (
    DatabaseSchema,
    generate_sqlalchemy_models_from_prompt,
    post_process_schema,
)
from schema_gen.enums import SQLColumnType
from schema_gen.models import ColumnDefinition, TableDefinition, TypeParameter
from schema_gen import llm_generator


def _make_valid_schema() -> DatabaseSchema:
    """Build a minimal but fully valid DatabaseSchema for post-processing tests."""
    return DatabaseSchema(
        tables=[
            TableDefinition(
                name="User",
                columns=[
                    ColumnDefinition(
                        name="id",
                        type=SQLColumnType.INTEGER,
                        primary_key=True,
                        nullable=False,
                        autoincrement=True,
                    ),
                    ColumnDefinition(
                        name="email",
                        type=SQLColumnType.STRING,
                        type_parameters=TypeParameter(length=255),
                        nullable=False,
                    ),
                ],
            )
        ]
    )


def test_post_process_schema_passthrough():
    """A valid schema is returned unchanged (same instance)."""
    schema = _make_valid_schema()
    returned = post_process_schema(schema)
    assert returned is schema
    # No mutation of the valid columns.
    assert returned.tables[0].columns[0].nullable is False
    assert returned.tables[0].columns[1].nullable is False


def test_post_process_schema_fixes_nullable_primary_key():
    """A primary key column with nullable=True must be corrected to nullable=False."""
    schema = DatabaseSchema(
        tables=[
            TableDefinition(
                name="User",
                columns=[
                    ColumnDefinition(
                        name="id",
                        type=SQLColumnType.INTEGER,
                        primary_key=True,
                        nullable=True,  # the bug we're fixing
                        autoincrement=True,
                    ),
                    ColumnDefinition(
                        name="email",
                        type=SQLColumnType.STRING,
                        type_parameters=TypeParameter(length=255),
                        nullable=False,
                    ),
                ],
            )
        ]
    )

    returned = post_process_schema(schema)

    assert returned.tables[0].columns[0].nullable is False
    # Non-PK column untouched.
    assert returned.tables[0].columns[1].nullable is False


def test_generate_calls_structured_output_with_expected_args(monkeypatch):
    """generate_sqlalchemy_models_from_prompt wires the right args to the helper."""
    captured: dict = {}
    expected_schema = _make_valid_schema()

    def fake_structured_output(
        *, schema, messages, validation_callable, model, max_attempts, retry_exceptions
    ):
        captured.update(
            schema=schema,
            messages=messages,
            validation_callable=validation_callable,
            model=model,
            max_attempts=max_attempts,
            retry_exceptions=retry_exceptions,
        )
        return expected_schema

    monkeypatch.setattr(
        llm_generator, "structured_output_with_retries", fake_structured_output
    )

    result = generate_sqlalchemy_models_from_prompt(
        prompt="Create a blog with users and posts",
        model="anthropic/claude-3-haiku-test",
        max_attempts=5,
    )

    assert result is expected_schema
    assert captured["schema"] is DatabaseSchema
    assert captured["model"] == "anthropic/claude-3-haiku-test"
    assert captured["max_attempts"] == 5
    assert captured["validation_callable"] is post_process_schema
    assert ValidationError in captured["retry_exceptions"]
    assert ValueError in captured["retry_exceptions"]

    # The prompt should be embedded into a single user-role message.
    messages = captured["messages"]
    assert isinstance(messages, list) and len(messages) == 1
    assert messages[0]["role"] == "user"
    assert "Create a blog with users and posts" in messages[0]["content"]


def test_generate_uses_default_model_when_not_specified(monkeypatch):
    """If `model` is not provided, the module-level DEFAULT_MODEL is used."""
    captured: dict = {}

    def fake_structured_output(*, model, **_kwargs):
        captured["model"] = model
        return _make_valid_schema()

    monkeypatch.setattr(
        llm_generator, "structured_output_with_retries", fake_structured_output
    )

    generate_sqlalchemy_models_from_prompt(prompt="anything")

    assert captured["model"] == llm_generator.DEFAULT_MODEL
