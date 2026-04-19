"""Pydantic models for SQLAlchemy schema generation."""

import logging
from typing import Optional, List, Any, Dict, Type, TYPE_CHECKING
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import (
    CheckConstraint as SACheckConstraint,
    Column,
    Enum as SAEnum,
    ForeignKey,
    Index,
    MetaData,
    Table,
    UniqueConstraint as SAUniqueConstraint,
    inspect,
)
from sqlalchemy.types import (
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
    TypeDecorator,
)

from schema_gen.converter import HAS_POSTGRESQL, SQLALCHEMY_TYPE_MAP
from schema_gen.enums import SQLColumnType, ForeignKeyAction, IndexType
from schema_gen import validators
from sqlalchemy.orm import declarative_base, mapped_column, relationship, DeclarativeBase

if HAS_POSTGRESQL:
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

logger = logging.getLogger(__name__)


class TypeParameter(BaseModel):
    """
    Parameters for column types that require additional configuration.

    Examples:
        - String(255): length=255
        - Numeric(10, 2): precision=10, scale=2
        - Enum('active', 'inactive'): enum_values=['active', 'inactive']
    """

    length: Optional[int] = Field(None, description="Length for String, VARCHAR types", ge=1)
    precision: Optional[int] = Field(None, description="Precision for Numeric, Decimal types", ge=1)
    scale: Optional[int] = Field(None, description="Scale for Numeric, Decimal types", ge=0)
    enum_values: Optional[List[str]] = Field(
        None, description="Allowed values for Enum type", min_length=1
    )
    timezone: Optional[bool] = Field(
        None, description="Whether DateTime/Time includes timezone (PostgreSQL)"
    )


class ColumnDefinition(BaseModel):
    """Definition of a database table column."""

    name: str = Field(..., description="Column name", min_length=1)
    type: SQLColumnType = Field(..., description="SQLAlchemy column type")
    type_parameters: Optional[TypeParameter] = Field(
        None, description="Parameters for parameterized types like String(255)"
    )
    nullable: bool = Field(True, description="Whether column allows NULL")
    primary_key: bool = Field(False, description="Is this a primary key column")
    unique: bool = Field(False, description="Unique constraint on this column")
    autoincrement: bool = Field(False, description="Auto-increment for Integer primary keys")
    index: bool = Field(False, description="Create an index on this column")
    comment: Optional[str] = Field(None, description="Column comment/description")
    default: Optional[str] = Field(
        None, description="Default value as string representation (e.g., '0', 'true')"
    )
    server_default: Optional[str] = Field(
        None, description="Server-side default SQL expression (e.g., 'CURRENT_TIMESTAMP')"
    )

    @field_validator("type_parameters")
    @classmethod
    def validate_type_parameters(cls, v, info):
        """Ensure type parameters match the column type"""
        if v is not None and "type" in info.data:
            validators.validate_type_parameters(
                v, info.data["type"], info.data.get("name", "unknown")
            )
        return v


class ForeignKeyDefinition(BaseModel):
    """Definition of a foreign key constraint."""

    column_name: str = Field(..., description="Column in this table", min_length=1)
    referenced_table: str = Field(..., description="Target table name", min_length=1)
    referenced_column: str = Field(default="id", description="Column in referenced table")
    ondelete: Optional[ForeignKeyAction] = Field(None, description="Action on DELETE")
    onupdate: Optional[ForeignKeyAction] = Field(None, description="Action on UPDATE")
    constraint_name: Optional[str] = Field(
        None, description="Custom constraint name (auto-generated if None)"
    )


class IndexDefinition(BaseModel):
    """Definition of a database index."""

    name: Optional[str] = Field(None, description="Index name (auto-generated if None)")
    columns: List[str] = Field(..., description="Columns in the index", min_length=1)
    unique: bool = Field(False, description="Is this a unique index")
    index_type: Optional[IndexType] = Field(None, description="Index type (database-specific)")


class CheckConstraint(BaseModel):
    """Definition of a check constraint."""

    name: Optional[str] = Field(None, description="Constraint name")
    expression: str = Field(
        ..., description="SQL expression for check constraint (e.g., 'age >= 18')", min_length=1
    )
    comment: Optional[str] = Field(None, description="Constraint description")


class UniqueConstraint(BaseModel):
    """Definition of a multi-column unique constraint."""

    name: Optional[str] = Field(None, description="Constraint name")
    columns: List[str] = Field(
        ..., description="Columns that form the unique constraint", min_length=1
    )


class TableDefinition(BaseModel):
    """Definition of a database table."""

    name: str = Field(..., description="Table name", min_length=1)
    comment: Optional[str] = Field(None, description="Table description")
    schema: Optional[str] = Field(None, description="Database schema (e.g., 'public', 'dbo')")
    columns: List[ColumnDefinition] = Field(..., description="Table columns", min_length=1)
    foreign_keys: List[ForeignKeyDefinition] = Field(
        default=[], description="Foreign key constraints"
    )
    unique_constraints: List[UniqueConstraint] = Field(
        default=[], description="Multi-column unique constraints"
    )
    indexes: List[IndexDefinition] = Field(default=[], description="Table indexes")
    check_constraints: List[CheckConstraint] = Field(default=[], description="Check constraints")

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, v, info):
        """Validate column definitions"""
        table_name = info.data.get("name", "unknown")

        # Check for unique column names
        validators.validate_column_names_unique(v, table_name)

        # Check for primary key
        validators.validate_has_primary_key(v, table_name)

        return v

    @model_validator(mode="after")
    def validate_references(self):
        """Validate that foreign keys, indexes, and constraints reference existing columns"""
        # Validate foreign keys
        validators.validate_foreign_key_columns_exist(self.foreign_keys, self.columns, self.name)

        # Validate unique constraints
        validators.validate_unique_constraint_columns_exist(
            self.unique_constraints, self.columns, self.name
        )

        # Validate indexes
        validators.validate_index_columns_exist(self.indexes, self.columns, self.name)

        return self


class DatabaseSchema(BaseModel):
    """Complete database schema definition."""

    tables: List[TableDefinition] = Field(..., description="Database tables", min_length=1)
    schema_name: Optional[str] = Field(None, description="Overall schema name/namespace")
    description: Optional[str] = Field(None, description="Schema description")

    @field_validator("tables")
    @classmethod
    def validate_table_names(cls, v):
        """Ensure all table names are unique"""
        validators.validate_table_names_unique(v)
        return v

    @model_validator(mode="after")
    def validate_cross_table_references(self):
        """Validate foreign key references and circular dependencies"""
        # Validate foreign keys reference existing tables
        validators.validate_foreign_key_references(self.tables)

        # Check for circular dependencies
        validators.validate_no_circular_dependencies(self.tables)

        return self

    def to_orm_classes(self) -> Dict[str, Type[DeclarativeBase]]:
        """
        Convert DatabaseSchema to SQLAlchemy ORM classes.

        This method converts the validated schema into actual SQLAlchemy ORM classes.
        It creates a new declarative base, generates ORM classes for each table with
        proper columns and foreign keys, and adds relationships between them.

        Returns:
            Dictionary mapping table names to ORM model classes

        Raises:
            ValueError: If schema conversion fails

        Example:
            >>> schema = DatabaseSchema(tables=[...])
            >>> orm_classes = schema.to_orm_classes()
            >>> User = orm_classes['User']
            >>> Post = orm_classes['Post']
        """
        # Import here to avoid circular imports and keep models.py lightweight

        logger.info(f"Converting schema to ORM classes: {self.schema_name}")
        logger.info(f"Schema description: {self.description}")
        logger.info(f"Number of tables: {len(self.tables)}")

        # Log detailed information about each table
        for table_def in self.tables:
            logger.info(f"  Table: {table_def.name}")
            if table_def.comment:
                logger.info(f"    Comment: {table_def.comment}")
            logger.info(f"    Columns ({len(table_def.columns)}):")
            for col_def in table_def.columns:
                col_info = f"      - {col_def.name}: {col_def.type.value}"
                if col_def.type_parameters:
                    params = []
                    if col_def.type_parameters.length:
                        params.append(f"length={col_def.type_parameters.length}")
                    if col_def.type_parameters.precision:
                        params.append(f"precision={col_def.type_parameters.precision}")
                    if col_def.type_parameters.scale:
                        params.append(f"scale={col_def.type_parameters.scale}")
                    if params:
                        col_info += f"({', '.join(params)})"

                constraints = []
                if col_def.primary_key:
                    constraints.append("PK")
                if not col_def.nullable:
                    constraints.append("NOT NULL")
                if col_def.unique:
                    constraints.append("UNIQUE")
                if col_def.autoincrement:
                    constraints.append("AUTOINCREMENT")
                if constraints:
                    col_info += f" [{', '.join(constraints)}]"

                if col_def.comment:
                    col_info += f" - {col_def.comment}"

                logger.info(col_info)

            if table_def.foreign_keys:
                logger.info(f"    Foreign Keys ({len(table_def.foreign_keys)}):")
                for fk_def in table_def.foreign_keys:
                    fk_info = f"      - {fk_def.column_name} -> {fk_def.referenced_table}.{fk_def.referenced_column}"
                    if fk_def.ondelete:
                        fk_info += f" [ON DELETE {fk_def.ondelete.value}]"
                    if fk_def.onupdate:
                        fk_info += f" [ON UPDATE {fk_def.onupdate.value}]"
                    logger.info(fk_info)

            if table_def.indexes:
                logger.info(f"    Indexes ({len(table_def.indexes)}):")
                for idx_def in table_def.indexes:
                    logger.info(f"      - {idx_def.name}: {', '.join(idx_def.columns)}")

            if table_def.unique_constraints:
                logger.info(f"    Unique Constraints ({len(table_def.unique_constraints)}):")
                for uc_def in table_def.unique_constraints:
                    logger.info(f"      - {uc_def.name}: {', '.join(uc_def.columns)}")

        # Create a new declarative base for this schema
        Base = declarative_base()

        # First pass: Create all ORM classes (columns only)
        orm_classes: Dict[str, Type] = {}

        for table_def in self.tables:
            orm_class = create_orm_class(table_def, Base, table_def.foreign_keys)
            orm_classes[table_def.name] = orm_class
            logger.info(f"Created ORM class: {table_def.name}")

        # Second pass: Add relationships
        add_relationships(orm_classes, self)
        logger.info(f"Successfully created {len(orm_classes)} ORM classes")

        return orm_classes

    @classmethod
    def from_orm_classes(cls, orm_classes: Dict[str, Type[DeclarativeBase]]) -> "DatabaseSchema":
        """
        Convert SQLAlchemy ORM classes back to DatabaseSchema.

        This is the reverse operation of to_orm_classes(), allowing you to:
        1. Convert ORM classes → DatabaseSchema
        2. Serialize to JSON
        3. Re-inflate later

        Args:
            orm_classes: Dictionary mapping table names to ORM model classes
                        (as returned by to_orm_classes())

        Returns:
            DatabaseSchema instance with all metadata extracted from ORM classes

        Example:
            >>> schema = DatabaseSchema(tables=[...])
            >>> orm_classes = schema.to_orm_classes()
            >>> # Round-trip conversion
            >>> schema_copy = DatabaseSchema.from_orm_classes(orm_classes)
            >>> assert schema == schema_copy
        """
        logger.info(f"Converting {len(orm_classes)} ORM classes to DatabaseSchema")

        tables = []

        for table_name, orm_class in orm_classes.items():
            # Get the SQLAlchemy Table object
            sa_table = orm_class.__table__

            logger.info(f"  Processing table: {table_name}")

            # Extract table-level metadata
            table_schema = getattr(sa_table, "schema", None)
            table_comment = None

            # Extract comment from __table_args__ if present
            if hasattr(orm_class, "__table_args__"):
                table_args = orm_class.__table_args__
                if isinstance(table_args, dict):
                    table_comment = table_args.get("comment")
                elif isinstance(table_args, tuple):
                    # Last element might be a dict with kwargs
                    for arg in table_args:
                        if isinstance(arg, dict):
                            table_comment = arg.get("comment")
                            break

            # Extract columns
            columns = []
            for col in sa_table.columns:
                # Get column type and parameters
                col_type, type_params = sqlalchemy_type_to_column_type(col.type)

                # Extract default values
                default_val = None
                server_default_val = None
                if col.default is not None:
                    # Default could be a scalar value or a ColumnDefault object
                    if hasattr(col.default, "arg"):
                        default_val = str(col.default.arg)
                    else:
                        default_val = str(col.default)

                if col.server_default is not None:
                    # Server default is a FetchedValue or similar
                    if hasattr(col.server_default, "arg"):
                        # For text() expressions, extract the SQL
                        server_default_val = str(col.server_default.arg)
                    else:
                        server_default_val = str(col.server_default)

                # Handle autoincrement (can be True, False, or 'auto')
                autoincrement_val = False
                if hasattr(col, "autoincrement"):
                    if col.autoincrement is True:
                        autoincrement_val = True
                    elif col.autoincrement == "auto":
                        # 'auto' means autoincrement if it's an integer PK
                        autoincrement_val = col.primary_key and col_type in [
                            SQLColumnType.INTEGER,
                            SQLColumnType.BIGINT,
                            SQLColumnType.SMALLINT,
                        ]

                # Handle unique and index which can be None in reflected models
                unique_val = bool(col.unique) if col.unique is not None else False
                index_val = bool(col.index) if hasattr(col, "index") and col.index is not None else False

                col_def = ColumnDefinition(
                    name=col.name,
                    type=col_type,
                    type_parameters=type_params,
                    nullable=col.nullable,
                    primary_key=col.primary_key,
                    unique=unique_val,
                    autoincrement=autoincrement_val,
                    index=index_val,
                    comment=col.comment,
                    default=default_val,
                    server_default=server_default_val,
                )
                columns.append(col_def)

            # Extract foreign keys
            foreign_keys = []
            for col in sa_table.columns:
                for fk in col.foreign_keys:
                    # fk.column is the referenced column
                    # fk.parent is the source column
                    ref_table = fk.column.table.name
                    ref_column = fk.column.name

                    # Extract ondelete and onupdate
                    ondelete = None
                    onupdate = None
                    if fk.ondelete:
                        try:
                            ondelete = ForeignKeyAction(fk.ondelete)
                        except ValueError:
                            logger.warning(f"Unknown FK action ondelete: {fk.ondelete}")

                    if fk.onupdate:
                        try:
                            onupdate = ForeignKeyAction(fk.onupdate)
                        except ValueError:
                            logger.warning(f"Unknown FK action onupdate: {fk.onupdate}")

                    fk_def = ForeignKeyDefinition(
                        column_name=col.name,
                        referenced_table=ref_table,
                        referenced_column=ref_column,
                        ondelete=ondelete,
                        onupdate=onupdate,
                        constraint_name=fk.name,
                    )
                    foreign_keys.append(fk_def)

            # Extract indexes
            indexes = []
            for idx in sa_table.indexes:
                idx_columns = [col.name for col in idx.columns]

                # Try to extract index type (PostgreSQL-specific)
                idx_type = None
                if hasattr(idx, "kwargs") and "postgresql_using" in idx.kwargs:
                    try:
                        idx_type = IndexType(idx.kwargs["postgresql_using"])
                    except ValueError:
                        logger.warning(
                            f"Unknown index type: {idx.kwargs['postgresql_using']}"
                        )

                idx_def = IndexDefinition(
                    name=idx.name,
                    columns=idx_columns,
                    unique=idx.unique,
                    index_type=idx_type,
                )
                indexes.append(idx_def)

            # Extract unique constraints (excluding those from unique=True on columns)
            unique_constraints = []
            for constraint in sa_table.constraints:
                if isinstance(constraint, SAUniqueConstraint):
                    # Skip single-column unique constraints (handled by column.unique)
                    if len(constraint.columns) > 1:
                        uc_columns = [col.name for col in constraint.columns]
                        uc_def = UniqueConstraint(
                            name=constraint.name,
                            columns=uc_columns,
                        )
                        unique_constraints.append(uc_def)

            # Extract check constraints
            check_constraints = []
            for constraint in sa_table.constraints:
                if isinstance(constraint, SACheckConstraint):
                    # Extract the SQL expression
                    expression = str(constraint.sqltext)

                    cc_def = CheckConstraint(
                        name=constraint.name,
                        expression=expression,
                        comment=None,  # SQLAlchemy doesn't store check constraint comments
                    )
                    check_constraints.append(cc_def)

            # Create TableDefinition
            table_def = TableDefinition(
                name=table_name,
                comment=table_comment,
                schema=table_schema,
                columns=columns,
                foreign_keys=foreign_keys,
                unique_constraints=unique_constraints,
                indexes=indexes,
                check_constraints=check_constraints,
            )
            tables.append(table_def)

        # Create DatabaseSchema
        # Note: We don't have access to the original schema_name and description
        # from ORM classes, so these will be None
        database_schema = cls(
            tables=tables,
            schema_name=None,
            description=None,
        )

        logger.info(f"Successfully created DatabaseSchema with {len(tables)} tables")

        return database_schema


def create_orm_class(
    table_def: TableDefinition, Base: Type, foreign_keys: Optional[List] = None
) -> Type:
    """
    Dynamically create a SQLAlchemy ORM class from a TableDefinition.

    Args:
        table_def: TableDefinition object
        Base: SQLAlchemy declarative base
        foreign_keys: Optional list of ForeignKeyDefinition objects

    Returns:
        Dynamically created ORM class
    """
    # Start with table metadata
    attrs = {
        "__tablename__": table_def.name,
    }

    # Add table args (comment, schema, etc.)
    table_args = []
    table_kwargs = {}

    if table_def.comment:
        table_kwargs["comment"] = table_def.comment

    if table_def.schema:
        table_kwargs["schema"] = table_def.schema

    # We'll add indexes, unique constraints, and check constraints after creating the class
    # Store them for later
    pending_indexes = list(table_def.indexes)
    pending_unique_constraints = list(table_def.unique_constraints)
    pending_check_constraints = list(table_def.check_constraints)

    if table_args or table_kwargs:
        attrs["__table_args__"] = (
            tuple(table_args) + (table_kwargs,) if table_kwargs else tuple(table_args)
        )

    # Add columns
    for col_def in table_def.columns:
        sa_type = create_sqlalchemy_type(col_def)

        # Build column kwargs
        col_kwargs = {
            "primary_key": col_def.primary_key,
            "nullable": col_def.nullable,
            "unique": col_def.unique,
            "index": col_def.index,
        }

        if col_def.comment:
            col_kwargs["comment"] = col_def.comment

        if col_def.autoincrement:
            col_kwargs["autoincrement"] = True

        if col_def.server_default:
            from sqlalchemy import text

            col_kwargs["server_default"] = text(col_def.server_default)

        # Check if this column has a foreign key
        has_fk = False
        if foreign_keys:
            for fk_def in foreign_keys:
                if fk_def.column_name == col_def.name:
                    fk_ref = f"{fk_def.referenced_table}.{fk_def.referenced_column}"
                    fk_kwargs = {}
                    if fk_def.ondelete:
                        fk_kwargs["ondelete"] = fk_def.ondelete.value
                    if fk_def.onupdate:
                        fk_kwargs["onupdate"] = fk_def.onupdate.value
                    if fk_def.constraint_name:
                        fk_kwargs["name"] = fk_def.constraint_name

                    col_kwargs["foreign_key"] = ForeignKey(fk_ref, **fk_kwargs)
                    has_fk = True
                    break

        # Create mapped column with proper type annotation
        # We can't use Mapped[] in dynamically created classes easily,
        # so we use mapped_column directly
        if has_fk:
            attrs[col_def.name] = mapped_column(
                sa_type, col_kwargs.pop("foreign_key"), **col_kwargs
            )
        else:
            attrs[col_def.name] = mapped_column(sa_type, **col_kwargs)

    # Create the class
    orm_class = type(table_def.name, (Base,), attrs)

    # Add indexes, unique constraints, and check constraints to the table
    # These need to be added after the class is created so we have access to columns
    table = orm_class.__table__

    # Add indexes
    for idx_def in pending_indexes:
        idx_columns = [table.c[col_name] for col_name in idx_def.columns]
        idx_args = {"unique": idx_def.unique}
        if idx_def.index_type:
            idx_args["postgresql_using"] = idx_def.index_type.value
        Index(idx_def.name, *idx_columns, **idx_args)

    # Add unique constraints
    for uc_def in pending_unique_constraints:
        uc_columns = [table.c[col_name] for col_name in uc_def.columns]
        constraint = SAUniqueConstraint(*uc_columns, name=uc_def.name)
        table.append_constraint(constraint)

    # Add check constraints
    for cc_def in pending_check_constraints:
        constraint = SACheckConstraint(cc_def.expression, name=cc_def.name)
        table.append_constraint(constraint)

    return orm_class


def add_relationships(orm_classes: Dict[str, Type], schema: DatabaseSchema):
    """
    Add relationship() attributes to ORM classes based on foreign keys.

    Args:
        orm_classes: Dictionary mapping table names to ORM classes
        schema: DatabaseSchema containing all table definitions
    """
    for table_def in schema.tables:
        orm_class = orm_classes[table_def.name]

        # Add relationships for each foreign key
        for fk_def in table_def.foreign_keys:
            # Determine relationship name (pluralized version of referenced table)
            ref_table_name = fk_def.referenced_table

            # Simple pluralization: add 's' if doesn't end with 's'
            rel_name = ref_table_name.lower()
            if not rel_name.endswith("s"):
                rel_name = rel_name + "s"

            # Make unique if needed
            counter = 1
            base_rel_name = rel_name
            while hasattr(orm_class, rel_name):
                rel_name = f"{base_rel_name}_{counter}"
                counter += 1

            # For many-to-one: singular name pointing to parent
            # Check if the column name suggests the relationship name
            if fk_def.column_name.endswith("_id"):
                rel_name = fk_def.column_name[:-3]  # Remove '_id' suffix

            # Add relationship
            setattr(
                orm_class,
                rel_name,
                relationship(ref_table_name, foreign_keys=[getattr(orm_class, fk_def.column_name)]),
            )


def create_sqlalchemy_type(col: ColumnDefinition) -> Any:
    """
    Convert a ColumnDefinition to a SQLAlchemy type instance.

    Args:
        col: ColumnDefinition object

    Returns:
        SQLAlchemy type instance (e.g., String(255), Integer(), etc.)

    Raises:
        ValueError: If the column type is unsupported or parameters are invalid
    """
    base_type = SQLALCHEMY_TYPE_MAP.get(col.type)

    if base_type is None:
        raise ValueError(f"Unsupported column type: {col.type}")

    # Check if base_type is callable (for types like lambda: PG_UUID(as_uuid=True))
    # vs a class (for types like String)
    if callable(base_type) and not isinstance(base_type, type):
        # It's a callable (e.g., lambda), call it to get the instance
        base_type_instance = base_type()
        # For callables, we already have the configured instance, just return it
        return base_type_instance

    # Handle parameterized types
    params = col.type_parameters
    if params:
        if col.type in [SQLColumnType.STRING, SQLColumnType.VARCHAR]:
            return base_type(params.length)

        elif col.type in [SQLColumnType.NUMERIC, SQLColumnType.DECIMAL]:
            if params.scale is not None:
                return base_type(params.precision, params.scale)
            else:
                return base_type(params.precision)

        elif col.type == SQLColumnType.ENUM:
            if not params.enum_values:
                raise ValueError(f"ENUM type for column '{col.name}' requires enum_values")
            # Create an enum type with a name based on the column
            enum_name = f"{col.name}_enum"
            return SAEnum(*params.enum_values, name=enum_name)

        elif col.type in [SQLColumnType.DATETIME, SQLColumnType.TIME]:
            if params.timezone is not None:
                return base_type(timezone=params.timezone)

    # Return base type without parameters
    return base_type()


def sqlalchemy_type_to_column_type(
    sa_type: Any,
) -> tuple[SQLColumnType, Optional[TypeParameter]]:
    """
    Convert a SQLAlchemy type instance to SQLColumnType enum and TypeParameter.

    This is the reverse operation of create_sqlalchemy_type().

    Args:
        sa_type: SQLAlchemy type instance (e.g., String(255), Integer(), etc.)

    Returns:
        Tuple of (SQLColumnType, Optional[TypeParameter])

    Raises:
        ValueError: If the SQLAlchemy type cannot be mapped to a SQLColumnType
    """
    # Handle PostgreSQL-specific types first
    if HAS_POSTGRESQL:
        if isinstance(sa_type, PG_UUID):
            return SQLColumnType.UUID, None
        if isinstance(sa_type, JSONB):
            return SQLColumnType.JSONB, None

    # Handle Enum type specially
    # Since SQLColumnType.ENUM is not supported (commented out in enums.py),
    # we convert ENUMs to VARCHAR/STRING type
    if isinstance(sa_type, SAEnum):
        # Get the length - use the longest enum value or the type's length if specified
        length = None
        if hasattr(sa_type, "length") and sa_type.length:
            length = sa_type.length
        elif hasattr(sa_type, "enums") and sa_type.enums:
            # Calculate max length from enum values
            length = max(len(str(val)) for val in sa_type.enums)

        type_params = TypeParameter(length=length) if length else None
        return SQLColumnType.STRING, type_params

    # Map SQLAlchemy type to SQLColumnType using isinstance checks
    # This handles both exact types and subclasses (e.g., VARCHAR is a subclass of String)
    column_type = None

    # Check type inheritance in order of specificity (most specific first)
    # We need to check more specific types before their base types
    # IMPORTANT: Some types inherit from others:
    # - Float inherits from Numeric, so check Float before Numeric
    # - TIMESTAMP inherits from DateTime, so check TIMESTAMP before DateTime
    # - Text inherits from String, so check Text before String
    # - BigInteger/SmallInteger inherit from Integer, so check them before Integer
    type_checks = [
        (LargeBinary, SQLColumnType.BINARY),
        (Text, SQLColumnType.TEXT),
        (String, SQLColumnType.STRING),  # After Text
        (BigInteger, SQLColumnType.BIGINT),
        (SmallInteger, SQLColumnType.SMALLINT),
        (Integer, SQLColumnType.INTEGER),  # After BigInteger/SmallInteger
        (Float, SQLColumnType.FLOAT),  # BEFORE Numeric (Float inherits from Numeric)
        (Numeric, SQLColumnType.NUMERIC),  # After Float
        (Boolean, SQLColumnType.BOOLEAN),
        (TIMESTAMP, SQLColumnType.TIMESTAMP),  # BEFORE DateTime (TIMESTAMP inherits from DateTime)
        (DateTime, SQLColumnType.DATETIME),  # After TIMESTAMP
        (Date, SQLColumnType.DATE),
        (Time, SQLColumnType.TIME),
        (JSON, SQLColumnType.JSON),
    ]

    for sa_type_class, col_type in type_checks:
        if isinstance(sa_type, sa_type_class):
            column_type = col_type
            break

    if column_type is None:
        # Get the type class for error message
        type_class = sa_type.__class__ if not isinstance(sa_type, type) else sa_type
        raise ValueError(f"Unsupported SQLAlchemy type: {type_class.__name__}")

    # Extract type parameters based on the column type
    type_params = None

    # String types with length
    if isinstance(sa_type, String) and hasattr(sa_type, "length") and sa_type.length:
        type_params = TypeParameter(length=sa_type.length)

    # Numeric types with precision and scale
    elif isinstance(sa_type, Numeric):
        precision = getattr(sa_type, "precision", None)
        scale = getattr(sa_type, "scale", None)
        if precision is not None or scale is not None:
            type_params = TypeParameter(precision=precision, scale=scale)

    # DateTime and Time types with timezone
    elif isinstance(sa_type, (DateTime, Time)):
        timezone = getattr(sa_type, "timezone", None)
        if timezone is not None:
            type_params = TypeParameter(timezone=timezone)

    return column_type, type_params


def create_sqlalchemy_tables(schema: DatabaseSchema, metadata: MetaData) -> Dict[str, Table]:
    """
    Convert a DatabaseSchema to SQLAlchemy Table objects.

    Uses a two-pass approach:
    1. Create all tables with columns (without foreign keys)
    2. Add foreign keys, indexes, and constraints after all tables exist

    Args:
        schema: DatabaseSchema object containing table definitions
        metadata: SQLAlchemy MetaData object to attach tables to

    Returns:
        Dictionary mapping table names to SQLAlchemy Table objects

    Raises:
        ValueError: If conversion fails due to invalid schema
    """
    tables: Dict[str, Table] = {}

    # First pass: Create tables with columns only (no foreign keys)
    for table_def in schema.tables:
        columns = []

        for col_def in table_def.columns:
            # Create SQLAlchemy column type
            sa_type = create_sqlalchemy_type(col_def)

            # Build column arguments
            column_args = {
                "primary_key": col_def.primary_key,
                "nullable": col_def.nullable,
                "unique": col_def.unique,
                "autoincrement": col_def.autoincrement,
                "index": col_def.index,
                "comment": col_def.comment,
            }

            # Add server_default if provided
            if col_def.server_default is not None:
                from sqlalchemy import text

                column_args["server_default"] = text(col_def.server_default)

            # Create column
            column = Column(col_def.name, sa_type, **column_args)
            columns.append(column)

        # Create table (without foreign keys initially)
        table = Table(
            table_def.name,
            metadata,
            *columns,
            schema=table_def.schema,
            comment=table_def.comment,
        )
        tables[table_def.name] = table

    # Second pass: Add foreign keys, indexes, and constraints
    for table_def in schema.tables:
        table = tables[table_def.name]

        # Add foreign keys
        for fk_def in table_def.foreign_keys:
            col = table.c[fk_def.column_name]

            # Build foreign key reference
            fk_reference = f"{fk_def.referenced_table}.{fk_def.referenced_column}"

            # Build foreign key arguments
            fk_args = {}
            if fk_def.ondelete:
                fk_args["ondelete"] = fk_def.ondelete.value
            if fk_def.onupdate:
                fk_args["onupdate"] = fk_def.onupdate.value
            if fk_def.constraint_name:
                fk_args["name"] = fk_def.constraint_name

            fk = ForeignKey(fk_reference, **fk_args)
            col.append_foreign_key(fk)

        # Add indexes
        for idx_def in table_def.indexes:
            idx_columns = [table.c[col_name] for col_name in idx_def.columns]

            # Build index arguments
            idx_args = {
                "unique": idx_def.unique,
            }

            # Add database-specific index type
            if idx_def.index_type:
                # PostgreSQL uses postgresql_using parameter
                idx_args["postgresql_using"] = idx_def.index_type.value

            Index(idx_def.name, *idx_columns, **idx_args)

        # Add unique constraints
        for uc_def in table_def.unique_constraints:
            uc_columns = [table.c[col_name] for col_name in uc_def.columns]
            SAUniqueConstraint(
                *uc_columns,
                name=uc_def.name,
            )

        # Add check constraints
        for cc_def in table_def.check_constraints:
            SACheckConstraint(
                cc_def.expression,
                name=cc_def.name,
            )

    return tables


def create_database_schema(
    schema: DatabaseSchema, engine, drop_existing: bool = False
) -> Dict[str, Table]:
    """
    Create database schema from DatabaseSchema definition.

    Convenience function that creates MetaData, converts schema to tables,
    and creates them in the database.

    Args:
        schema: DatabaseSchema object
        engine: SQLAlchemy engine
        drop_existing: If True, drop existing tables before creating

    Returns:
        Dictionary mapping table names to SQLAlchemy Table objects
    """
    metadata = MetaData()
    tables = create_sqlalchemy_tables(schema, metadata)

    if drop_existing:
        metadata.drop_all(engine)

    metadata.create_all(engine)

    return tables
