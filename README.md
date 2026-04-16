# schema_gen

Generation of database schemas from natural language prompts using the validation loop pattern.

## Overview

`schema_gen` is a Python library that uses Large Language Models (LLMs) to generate SQLAlchemy database schemas from natural language descriptions. It employs a validation loop pattern to ensure the generated schemas are valid and can be directly converted to working SQLAlchemy ORM classes.

### Key Features

- **Natural Language to Schema**: Describe your database structure in plain English and get a complete schema
- **Validation Loop Pattern**: Automatically retries LLM generation if validation fails, ensuring correct output
- **Type Safety**: Uses Pydantic v2 models for schema representation with full type checking
- **SQLAlchemy Integration**: Seamless conversion to SQLAlchemy ORM classes and Table objects
- **Comprehensive Validation**: Multi-level validation including:
  - Pydantic field validation
  - Column type parameter validation
  - Foreign key reference validation
  - Circular dependency detection
  - Primary key requirements
- **Database Support**: Works with PostgreSQL, MySQL, SQLite, and other SQLAlchemy-supported databases
- **Round-trip Conversion**: Convert between Pydantic schema models and SQLAlchemy ORM classes

## Installation

### Using Poetry (Recommended)

```bash
cd schema_gen
poetry install
```

For PostgreSQL support with additional features:
```bash
poetry install --extras postgres
```

### Using pip

```bash
pip install -e .
```

## Quick Start

### Basic Usage

```python
from schema_gen import generate_sqlalchemy_models_from_prompt

# Generate schema from natural language. `model` is a LiteLLM model string;
# the corresponding provider API key must be set in the environment
# (e.g. OPENAI_API_KEY for openai/*, ANTHROPIC_API_KEY for anthropic/*).
schema = generate_sqlalchemy_models_from_prompt(
    prompt="""
    Create a blog schema with:
    - Users who can write posts
    - Posts with title, content, and timestamps
    - Comments on posts
    """,
    model="openai/gpt-4o",
)

# Convert to SQLAlchemy ORM classes
orm_classes = schema.to_orm_classes()

# Use the generated classes
User = orm_classes["User"]
Post = orm_classes["Post"]
Comment = orm_classes["Comment"]
```

### Creating a Database

```python
from sqlalchemy import create_engine

# Create database
engine = create_engine("sqlite:///blog.db")

# Create tables from generated schema
Base = list(orm_classes.values())[0].__bases__[0]
Base.metadata.create_all(engine)
```

### Full Example

See [`example.py`](example.py) for a complete working example that:
1. Generates a project management schema from a natural language prompt
2. Creates a SQLite database
3. Populates it with sample data
4. Demonstrates queries using the generated ORM classes

Run it with:
```bash
export OPENAI_API_KEY='your-api-key-here'
poetry run python example.py
```

## Architecture

### Core Components

#### Models (`schema_gen.models`)

- **`DatabaseSchema`**: Top-level container for the entire database schema
- **`TableDefinition`**: Defines a single table with columns, constraints, and relationships
- **`ColumnDefinition`**: Defines a column with type, constraints, and default values
- **`ForeignKeyDefinition`**: Foreign key constraint with ON DELETE/UPDATE actions
- **`IndexDefinition`**: Index definition with type (BTREE, HASH, etc.)
- **`UniqueConstraint`**: Multi-column unique constraint
- **`CheckConstraint`**: Check constraint with SQL expression

#### Enums (`schema_gen.enums`)

- **`SQLColumnType`**: Supported column types (INTEGER, STRING, TIMESTAMP, JSON, etc.)
- **`ForeignKeyAction`**: Actions for foreign keys (CASCADE, SET NULL, RESTRICT, etc.)
- **`IndexType`**: Database index types (BTREE, HASH, GIST, GIN)

#### LLM Generator (`schema_gen.llm_generator`)

- **`generate_sqlalchemy_models_from_prompt()`**: Main function that uses an LLM with validation loop
- **`post_process_schema()`**: Validates and post-processes generated schemas
- Automatic retry logic if Pydantic validation or ORM conversion fails

#### Structured Output Helper (`schema_gen.structured_output_with_retries`)

- **`structured_output_with_retries()`**: Self-contained validation-loop helper built on [instructor](https://github.com/instructor-ai/instructor) + [litellm](https://github.com/BerriAI/litellm) + [tenacity](https://github.com/jd/tenacity). Forces the LLM to return a valid Pydantic instance and retries with the validation error text appended on failure.

#### Database Setup (`schema_gen.setup_db`)

- **`create_database()`**: Create PostgreSQL database if it doesn't exist
- **`create_sqlalchemy_engine()`**: Create SQLAlchemy engine from credentials
- **`setup_database()`**: Complete database initialization with table creation

### Validation Loop Pattern

The validation loop ensures generated schemas are correct:

1. **Prompt Construction**: Natural language description is formatted for the LLM
2. **LLM Generation**: Uses the local `structured_output_with_retries` helper (instructor + litellm)
3. **Pydantic Validation**: Automatic validation of field types and constraints
4. **Post-Processing**: Additional validation:
   - Verify foreign key references point to existing tables
   - Check for circular dependencies
   - Validate column type parameters
   - Ensure all tables have primary keys
5. **ORM Conversion**: Attempt to convert to SQLAlchemy ORM classes
6. **Retry**: If any validation fails, the error message is sent back to the LLM for correction

## API Documentation

### Main Functions

#### `generate_sqlalchemy_models_from_prompt()`

```python
def generate_sqlalchemy_models_from_prompt(
    prompt: str,
    model: str = "anthropic/claude-sonnet-4-5-20250929",
    max_attempts: int = 3,
) -> DatabaseSchema:
    """
    Generate a database schema from a natural language prompt.

    Args:
        prompt: Natural language description of the desired schema
        model: LiteLLM model string (e.g. "openai/gpt-4o",
               "anthropic/claude-sonnet-4-5-20250929"). The relevant provider
               API key must be set in the environment.
        max_attempts: Maximum number of LLM calls before giving up.

    Returns:
        DatabaseSchema: Validated schema that can be converted to ORM classes

    Raises:
        RuntimeError: If schema generation fails after max_attempts
    """
```

### Schema Classes

#### `DatabaseSchema`

```python
class DatabaseSchema(BaseModel):
    """Complete database schema definition."""
    tables: List[TableDefinition]

    def to_orm_classes(self) -> Dict[str, Type]:
        """Convert schema to SQLAlchemy ORM classes."""

    def to_sqlalchemy_tables(self, metadata: MetaData) -> Dict[str, Table]:
        """Convert schema to SQLAlchemy Table objects."""
```

#### `TableDefinition`

```python
class TableDefinition(BaseModel):
    """Single table definition."""
    name: str
    columns: List[ColumnDefinition]
    foreign_keys: List[ForeignKeyDefinition] = []
    indexes: List[IndexDefinition] = []
    unique_constraints: List[UniqueConstraint] = []
    check_constraints: List[CheckConstraint] = []
```

## LLM Providers

The library uses [LiteLLM](https://docs.litellm.ai/docs/providers) under the hood, so any provider LiteLLM supports works with the appropriate `provider/model` string and the corresponding API key in your environment:

### OpenAI

```python
generate_sqlalchemy_models_from_prompt(prompt, model="openai/gpt-4o")
# requires OPENAI_API_KEY
```

### Anthropic Claude

```python
generate_sqlalchemy_models_from_prompt(prompt, model="anthropic/claude-sonnet-4-5-20250929")
# requires ANTHROPIC_API_KEY
```

### Other Providers

See the [LiteLLM provider docs](https://docs.litellm.ai/docs/providers) for the full list — Azure, Cohere, Gemini, Ollama, Bedrock, etc.

## Configuration

### Environment Variables

- **`OPENAI_API_KEY`**: Required for OpenAI models
- **`ANTHROPIC_API_KEY`**: Required for Anthropic models

### Python Version

Requires Python 3.11 or higher.

## Advanced Usage

### Custom Validation

```python
from schema_gen import DatabaseSchema, generate_sqlalchemy_models_from_prompt, post_process_schema

# Generate schema
schema = generate_sqlalchemy_models_from_prompt(prompt, model="openai/gpt-4o")

# Additional custom validation
schema = post_process_schema(schema)

# Your custom checks
for table in schema.tables:
    if not table.columns:
        raise ValueError(f"Table {table.name} has no columns")
```

### PostgreSQL-Specific Features

```python
from schema_gen import DBCredentials, create_database

# Create PostgreSQL database
credentials = DBCredentials(
    user="postgres",
    password="password",
    host="localhost",
    port="5432",
    database="mydb",
    engine="postgres",
)

engine, created = create_database(credentials, delete_if_exists=False, orm_classes)
```

## Examples

### E-commerce Schema

```python
prompt = """
Create an e-commerce schema with:
- Customers with contact information
- Products with SKU, price, and inventory
- Orders placed by customers
- Order items linking orders to products
- Payments for orders
"""

schema = generate_sqlalchemy_models_from_prompt(prompt, model="openai/gpt-4o")
```

### SaaS Application

```python
prompt = """
Create a multi-tenant SaaS schema with:
- Organizations (tenants)
- Users belonging to organizations
- Subscriptions for organizations
- Usage metrics tracked per organization
"""

schema = generate_sqlalchemy_models_from_prompt(prompt, model="openai/gpt-4o")
```

## License

See [LICENSE](LICENSE) file for details.

## Contributing

This library was extracted from the Storyline project for standalone use. Contributions are welcome.

## Dependencies

- **pydantic** (>=2.11.7) - Schema validation and type safety
- **sqlalchemy** (>=2.0.36) - Database ORM and query building
- **instructor** (>=1.6.0) - Structured output wrapper
- **litellm** (==1.82.6) - Multi-provider LLM client. Pinned to 1.82.6 because versions 1.82.7 and 1.82.8 were compromised by a supply-chain attack (TeamPCP, March 2026).
- **tenacity** (>=9.0.0) - Retry logic
- **psycopg2-binary** (optional) - PostgreSQL support
