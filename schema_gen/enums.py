"""Enums for SQLAlchemy schema generation."""

from schema_gen import StrEnum


class SQLColumnType(StrEnum):
    """SQLAlchemy column types supported for schema generation."""

    # Integer types
    INTEGER = "Integer"
    BIGINT = "BigInteger"
    SMALLINT = "SmallInteger"

    # String types
    STRING = "String"  # Requires length parameter
    TEXT = "Text"
    VARCHAR = "String"  # Alias for STRING

    # Float/Decimal types
    FLOAT = "Float"
    NUMERIC = "Numeric"  # Requires precision parameter
    DECIMAL = "Numeric"  # Alias for NUMERIC

    # Boolean
    BOOLEAN = "Boolean"

    # Date/Time types
    DATE = "Date"
    DATETIME = "DateTime"
    TIME = "Time"
    TIMESTAMP = "TIMESTAMP"

    # Binary types
    BINARY = "LargeBinary"
    VARBINARY = "LargeBinary"

    # JSON types
    JSON = "JSON"
    JSONB = "JSONB"  # PostgreSQL specific

    # UUID
    UUID = "UUID"

    # TODO: might want to implement this one day?
    # # Enum type (requires values parameter)
    # ENUM = "Enum"


class ForeignKeyAction(StrEnum):
    """Actions for ON DELETE and ON UPDATE foreign key constraints."""

    CASCADE = "CASCADE"
    SET_NULL = "SET NULL"
    RESTRICT = "RESTRICT"
    NO_ACTION = "NO ACTION"
    SET_DEFAULT = "SET DEFAULT"


class IndexType(StrEnum):
    """Database index types (database-specific support may vary)."""

    BTREE = "btree"
    HASH = "hash"
    GIST = "gist"  # PostgreSQL
    GIN = "gin"  # PostgreSQL
