"""LLM-driven SQLAlchemy ORM model generation with automatic retry logic."""

import logging

from pydantic import ValidationError

from schema_gen.models import DatabaseSchema
from schema_gen.structured_output_with_retries import structured_output_with_retries

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "openai/gpt-4.1-mini"


_SCHEMA_PROMPT_TEMPLATE = """You are a database schema designer. Generate a complete database schema based on the user's requirements:

{prompt}

For each table, specify:
- Table name and comment (description)
- Columns with types, constraints, and comments
- Foreign keys with proper references and ON DELETE/UPDATE actions
- Indexes for frequently queried columns
- Unique constraints EXACTLY for all primary keys and no other columns

Use appropriate data types:
- INTEGER, BIGINT, SMALLINT for whole numbers
- STRING (with length), TEXT for strings
- FLOAT, NUMERIC (with precision/scale) for decimals
- BOOLEAN for true/false
- DATE, DATETIME, TIMESTAMP for dates/times
- JSON, JSONB for structured data
- UUID for unique identifiers

Ensure referential integrity:
- Foreign keys reference existing tables
- Primary keys are defined
- Avoid circular non-nullable foreign key dependencies

Don't insert uniqueness constraints except for primary keys.
Provide clear, descriptive comments for tables and all columns.
"""


def post_process_schema(schema: DatabaseSchema) -> DatabaseSchema:
    """
    Post-process function that validates DatabaseSchema by attempting ORM conversion.

    This function is called by structured_output_with_retries after Pydantic
    validation. It validates the schema by attempting to convert it to SQLAlchemy
    ORM classes, ensuring no exceptions occur during the conversion process.

    Also fixes common schema issues:
    - Ensures ALL primary key columns are marked as nullable=False

    Args:
        schema: DatabaseSchema - the schema to post-process

    Returns:
        The input DatabaseSchema object (for compatibility with structured_output_with_retries)

    Raises:
        ValueError: If schema conversion fails
    """
    logger.info(f"Post-processing schema: {schema.schema_name}")

    # Fix ALL nullable primary keys (primary keys must always be non-nullable)
    for table in schema.tables:
        for column in table.columns:
            if column.primary_key and column.nullable:
                logger.warning(
                    f"Fixing nullable primary key: {table.name}.{column.name} "
                    f"(changing nullable from True to False)"
                )
                column.nullable = False

    try:
        # Validate by attempting to convert to ORM classes
        # This ensures the schema is valid and can be converted without errors
        _ = schema.to_orm_classes()
        logger.info("Schema validation successful")
    except Exception as e:
        logger.error(f"Schema validation failed: {e}")
        raise ValueError(f"Failed to convert schema to ORM classes: {e}") from e

    return schema


def generate_sqlalchemy_models_from_prompt(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_attempts: int = 3,
) -> DatabaseSchema:
    """
    Generate SQLAlchemy ORM model classes from a natural language prompt.

    Uses structured_output_with_retries (instructor + litellm + tenacity) to
    generate a validated database schema, then converts it to SQLAlchemy ORM
    classes.

    Args:
        prompt: Natural language description of the desired database schema
        model: LiteLLM model string (e.g. "openai/gpt-4.1-mini",
               "openai/gpt-4o"). The relevant provider API key must be set in
               the environment (e.g. OPENAI_API_KEY).
        max_attempts: Maximum number of LLM calls before giving up.

    Returns:
        A DatabaseSchema object containing the generated schema.

    Raises:
        RuntimeError: If schema generation fails after max_attempts.

    Example:
        >>> models = generate_sqlalchemy_models_from_prompt(
        ...     "Create a blog with users, posts, and comments",
        ...     model="openai/gpt-4.1-mini",
        ... ).to_orm_classes()
        >>> User = models['User']
        >>> Post = models['Post']
    """
    logger.info("Starting SQLAlchemy model generation from prompt")
    logger.info(f"User prompt: {prompt}")
    logger.info(f"Model: {model}")

    rendered_prompt = _SCHEMA_PROMPT_TEMPLATE.format(prompt=prompt)
    messages = [{"role": "user", "content": rendered_prompt}]
    logger.info("Calling structured_output_with_retries to generate schema")

    schema_result: DatabaseSchema = structured_output_with_retries(
        schema=DatabaseSchema,
        messages=messages,
        validation_callable=post_process_schema,
        model=model,
        max_attempts=max_attempts,
        retry_exceptions=(ValidationError, ValueError),
    )

    logger.info(
        f"Successfully generated schema with {len(schema_result.tables)} tables: "
        f"{[t.name for t in schema_result.tables]}"
    )
    return schema_result
