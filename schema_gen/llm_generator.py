"""LLM-driven SQLAlchemy ORM model generation with automatic retry logic."""

import logging
from typing import Optional

from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import PromptTemplate

from storyline.schema_gen.models import DatabaseSchema

from motleycrew.utils.structured_output_with_retries import structured_output_with_retries

logger = logging.getLogger(__name__)


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
    language_model: Optional[BaseLanguageModel] = None,
) -> DatabaseSchema:
    """
    Generate SQLAlchemy ORM model classes from a natural language prompt.

    Uses MotleyCrew's structured_output_with_retries to generate a validated
    database schema, then converts it to SQLAlchemy ORM classes.

    Args:
        prompt: Natural language description of the desired database schema
        language_model: LLM to use for generation (optional)

    Returns:
        A DatabaseSchema object containing the generated schema

    Raises:
        ValueError: If schema generation or conversion fails

    Example:
        >>> llm = ChatAnthropic(model="claude-sonnet-4-5-20250929")
        >>> models = generate_sqlalchemy_models_from_prompt(
        ...     "Create a blog with users, posts, and comments",
        ...     language_model=llm
        ... ).to_orm_classes()
        >>> User = models['User']
        >>> Post = models['Post']
    """
    logger.info("Starting SQLAlchemy model generation from prompt")
    logger.info(f"User prompt: {prompt}")
    logger.info(
        f"Language model: {language_model.__class__.__name__ if language_model else 'None'}"
    )

    prompt_template = """You are a database schema designer. Generate a complete database schema based on the user's requirements:

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

    prompt_template = PromptTemplate.from_template(prompt_template).format(prompt=prompt)
    logger.info("Generated prompt template for LLM")

    # Use structured_output_with_retries to generate and validate schema
    logger.info("Calling structured_output_with_retries to generate schema")
    schema_result = structured_output_with_retries(
        schema=DatabaseSchema,
        prompt=prompt_template,
        input_messages={"prompt": prompt},
        language_model=language_model,
        post_process=post_process_schema,
    )

    # Convert the validated schema to ORM classes
    logger.info("Converting validated schema to ORM classes")
    orm_classes = schema_result.to_orm_classes()

    logger.info(
        f"Successfully generated {len(orm_classes)} ORM model classes: {list(orm_classes.keys())}"
    )
    return schema_result
