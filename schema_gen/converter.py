"""Convert Pydantic schema definitions to SQLAlchemy Table objects."""

from sqlalchemy import (
    Integer,
    BigInteger,
    SmallInteger,
    String,
    Text,
    Float,
    Numeric,
    Boolean,
    Date,
    DateTime,
    Time,
    TIMESTAMP,
    LargeBinary,
    JSON,
)

try:
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

    HAS_POSTGRESQL = True
except ImportError:
    HAS_POSTGRESQL = False

from schema_gen.enums import SQLColumnType

# Mapping from SQLColumnType enum to SQLAlchemy type classes
SQLALCHEMY_TYPE_MAP = {
    SQLColumnType.INTEGER: Integer,
    SQLColumnType.BIGINT: BigInteger,
    SQLColumnType.SMALLINT: SmallInteger,
    SQLColumnType.STRING: String,
    SQLColumnType.TEXT: Text,
    SQLColumnType.VARCHAR: String,
    SQLColumnType.FLOAT: Float,
    SQLColumnType.NUMERIC: Numeric,
    SQLColumnType.DECIMAL: Numeric,
    SQLColumnType.BOOLEAN: Boolean,
    SQLColumnType.DATE: Date,
    SQLColumnType.DATETIME: DateTime,
    SQLColumnType.TIME: Time,
    SQLColumnType.TIMESTAMP: TIMESTAMP,
    SQLColumnType.BINARY: LargeBinary,
    SQLColumnType.VARBINARY: LargeBinary,
    SQLColumnType.JSON: JSON,
    SQLColumnType.JSONB: JSON,  # Fallback: use JSON for non-Postgres
    SQLColumnType.UUID: String,  # Fallback: store UUIDs as strings
}

# Add PostgreSQL-specific types if available
if HAS_POSTGRESQL:
    SQLALCHEMY_TYPE_MAP[SQLColumnType.JSONB] = JSONB
    SQLALCHEMY_TYPE_MAP[SQLColumnType.UUID] = lambda: PG_UUID(as_uuid=True)
