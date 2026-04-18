"""Integration tests that call a real LLM.

Run with:
    pytest -m integration

Requires OPENAI_API_KEY in the environment.
"""

import pytest
from sqlalchemy import create_engine, inspect

from schema_gen import generate_sqlalchemy_models_from_prompt


pytestmark = pytest.mark.integration


@pytest.fixture
def in_memory_engine():
    engine = create_engine("sqlite:///:memory:")
    yield engine
    engine.dispose()


def test_full_cycle(in_memory_engine):
    """Generate a schema from a prompt, convert to ORM, create tables in SQLite."""
    schema = generate_sqlalchemy_models_from_prompt(
        prompt="Create a schema with a users table (id, username, email) "
        "and a posts table (id, title, body, user_id foreign key to users).",
        max_attempts=3,
    )

    # Schema should have at least 2 tables
    table_names = [t.name.lower() for t in schema.tables]
    assert len(schema.tables) >= 2
    assert any("user" in n for n in table_names)
    assert any("post" in n for n in table_names)

    # Convert to ORM classes
    orm_classes = schema.to_orm_classes()
    assert len(orm_classes) >= 2

    # Materialise tables in SQLite
    Base = list(orm_classes.values())[0].__bases__[0]
    Base.metadata.create_all(in_memory_engine)

    inspector = inspect(in_memory_engine)
    db_tables = inspector.get_table_names()
    assert len(db_tables) >= 2
