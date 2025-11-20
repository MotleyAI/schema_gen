"""Validation logic for database schema definitions."""

from typing import List, Set, Dict
from collections import defaultdict


def validate_type_parameters(type_params, column_type, column_name: str):
    """
    Validate that type parameters match the column type requirements.

    Args:
        type_params: TypeParameter object or None
        column_type: SQLColumnType enum value
        column_name: Name of the column (for error messages)

    Raises:
        ValueError: If type parameters don't match the column type requirements
    """
    from storyline.schema_gen.enums import SQLColumnType

    requires_length = column_type in {SQLColumnType.STRING, SQLColumnType.VARCHAR}
    requires_precision = column_type in {SQLColumnType.NUMERIC, SQLColumnType.DECIMAL}
    # Guard against non-existent ENUM in current enum set
    enum_type = getattr(SQLColumnType, "ENUM", None)
    requires_enum = enum_type is not None and column_type == enum_type

    if requires_length and (type_params is None or type_params.length is None):
        raise ValueError(
            f"Column '{column_name}': {column_type} requires length parameter"
        )
    if requires_precision and (type_params is None or type_params.precision is None):
        raise ValueError(
            f"Column '{column_name}': {column_type} requires precision parameter"
        )
    if requires_enum and (not type_params or not type_params.enum_values):
        raise ValueError(
            f"Column '{column_name}': ENUM type requires enum_values parameter"
        )

def validate_has_primary_key(columns, table_name: str):
    """
    Ensure table has at least one primary key column.

    Args:
        columns: List of ColumnDefinition objects
        table_name: Name of the table (for error messages)

    Raises:
        ValueError: If table has no primary key
    """
    if not any(col.primary_key for col in columns):
        raise ValueError(f"Table '{table_name}' must have at least one primary key column")


def validate_foreign_key_columns_exist(foreign_keys, columns, table_name: str):
    """
    Ensure all foreign key columns exist in the table.

    Args:
        foreign_keys: List of ForeignKeyDefinition objects
        columns: List of ColumnDefinition objects
        table_name: Name of the table (for error messages)

    Raises:
        ValueError: If a foreign key references a non-existent column
    """
    column_names = {col.name for col in columns}

    for fk in foreign_keys:
        if fk.column_name not in column_names:
            raise ValueError(
                f"Table '{table_name}': Foreign key references non-existent "
                f"column '{fk.column_name}'"
            )


def validate_unique_constraint_columns_exist(unique_constraints, columns, table_name: str):
    """
    Ensure all unique constraint columns exist in the table.

    Args:
        unique_constraints: List of UniqueConstraint objects
        columns: List of ColumnDefinition objects
        table_name: Name of the table (for error messages)

    Raises:
        ValueError: If a unique constraint references a non-existent column
    """
    column_names = {col.name for col in columns}

    for uc in unique_constraints:
        for col_name in uc.columns:
            if col_name not in column_names:
                raise ValueError(
                    f"Table '{table_name}': Unique constraint references "
                    f"non-existent column '{col_name}'"
                )


def validate_index_columns_exist(indexes, columns, table_name: str):
    """
    Ensure all index columns exist in the table.

    Args:
        indexes: List of IndexDefinition objects
        columns: List of ColumnDefinition objects
        table_name: Name of the table (for error messages)

    Raises:
        ValueError: If an index references a non-existent column
    """
    column_names = {col.name for col in columns}

    for idx in indexes:
        for col_name in idx.columns:
            if col_name not in column_names:
                raise ValueError(
                    f"Table '{table_name}': Index references non-existent "
                    f"column '{col_name}'"
                )


def validate_foreign_key_references(tables):
    """
    Ensure all foreign keys reference existing tables.

    Args:
        tables: List of TableDefinition objects

    Raises:
        ValueError: If a foreign key references a non-existent table
    """
    table_names = {table.name for table in tables}

    for table in tables:
        for fk in table.foreign_keys:
            if fk.referenced_table not in table_names:
                raise ValueError(
                    f"Table '{table.name}': Foreign key references "
                    f"non-existent table '{fk.referenced_table}'"
                )


def validate_no_circular_dependencies(tables):
    """
    Check for circular foreign key dependencies among non-nullable foreign keys.

    Only checks non-nullable foreign keys, as nullable FKs can be set after
    record creation and don't prevent data insertion.

    Args:
        tables: List of TableDefinition objects

    Raises:
        ValueError: If circular dependencies are detected
    """
    # Build dependency graph: table -> set of tables it depends on
    graph: Dict[str, Set[str]] = defaultdict(set)

    for table in tables:
        for fk in table.foreign_keys:
            # Find the column
            col = next((c for c in table.columns if c.name == fk.column_name), None)
            # Only track non-nullable FKs for circular dependency check
            if col and not col.nullable:
                graph[table.name].add(fk.referenced_table)

    # Detect cycles using DFS
    def has_cycle(node: str, visited: Set[str], rec_stack: Set[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in graph[node]:
            if neighbor not in visited:
                if has_cycle(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    visited: Set[str] = set()
    for table in tables:
        if table.name not in visited:
            if has_cycle(table.name, visited, set()):
                raise ValueError(
                    f"Circular foreign key dependency detected involving table: {table.name}. "
                    f"Consider making some foreign key columns nullable to break the cycle."
                )


def validate_column_names_unique(columns, table_name: str):
    """
    Ensure all column names are unique within a table.

    Args:
        columns: List of ColumnDefinition objects
        table_name: Name of the table (for error messages)

    Raises:
        ValueError: If duplicate column names are found
    """
    column_names = [col.name for col in columns]
    duplicates = {name for name in column_names if column_names.count(name) > 1}

    if duplicates:
        raise ValueError(
            f"Table '{table_name}': Duplicate column names found: {', '.join(duplicates)}"
        )


def validate_table_names_unique(tables):
    """
    Ensure all table names are unique within the schema.

    Args:
        tables: List of TableDefinition objects

    Raises:
        ValueError: If duplicate table names are found
    """
    table_names = [table.name for table in tables]
    duplicates = {name for name in table_names if table_names.count(name) > 1}

    if duplicates:
        raise ValueError(
            f"Duplicate table names found: {', '.join(duplicates)}"
        )
