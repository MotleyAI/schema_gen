import logging
import re

from sqlalchemy import create_engine, text

from schema_gen import DBCredentials

logger = logging.getLogger(__name__)

# Strict regex for safe PostgreSQL identifiers
# Allows: letters (a-z, A-Z), numbers (0-9), underscores (_), optional hyphens (-)
# Must start with a letter or underscore
# Using \A and \Z for absolute start/end to prevent multiline bypass
SAFE_IDENTIFIER_PATTERN = re.compile(r'\A[a-zA-Z_][a-zA-Z0-9_-]*\Z')


def validate_database_identifier(identifier: str) -> str:
    """
    Validate that a database identifier is safe to use in SQL statements.

    Args:
        identifier: The database identifier to validate

    Returns:
        The validated identifier

    Raises:
        ValueError: If the identifier doesn't match the safe pattern
    """
    if not identifier:
        raise ValueError("Database identifier cannot be empty")

    if not SAFE_IDENTIFIER_PATTERN.match(identifier):
        raise ValueError(
            f"Invalid database identifier '{identifier}'. "
            "Database names must start with a letter or underscore and contain only "
            "letters, numbers, underscores, and hyphens."
        )

    return identifier


def setup_database(db_credentials: DBCredentials, delete_if_exists: bool, orm_classes: dict):
    """
    Create database if it doesn't exist, or delete and recreate if requested.
    Also creates the tables from the ORM classes.

    Args:
        db_credentials: Database credentials (without database specified)
        delete_if_exists: Whether to delete and recreate if it exists
        orm_classes: Dictionary of ORM classes for creating tables

    Returns:
        Tuple of (engine, db_was_created):
            - engine: SQLAlchemy engine connected to the database
            - db_was_created: True if database was created/recreated, False if it already existed

    Raises:
        ValueError: If the database name is missing or contains invalid characters
    """
    # The database name to create is specified in the credentials
    database_name = db_credentials.database

    # Check that database name is provided
    if not database_name:
        raise ValueError(
            "Database name is missing in credentials. "
            "Please ensure db_credentials.database is set."
        )

    # Validate the database identifier to prevent SQL injection
    validated_name = validate_database_identifier(database_name)
    logger.info(f"Setting up database: {validated_name}")

    # Connect to default postgres database to check if target database exists
    # Use 'postgres' database for administrative operations
    db_creds_postgres = db_credentials.with_database("postgres")
    admin_engine = create_engine(db_creds_postgres.to_url())

    # Track whether database was created (for return value)
    db_was_created = False

    try:
        with admin_engine.connect() as conn:
            # Set autocommit for database operations
            conn.execution_options(isolation_level="AUTOCOMMIT")

            # Check if database exists
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"), {"dbname": validated_name}
            )
            db_exists = result.fetchone() is not None

            if db_exists:
                if delete_if_exists:
                    logger.warning(f"Database '{validated_name}' exists. Deleting and recreating...")
                    # Terminate existing connections
                    conn.execute(
                        text(
                            """
                            SELECT pg_terminate_backend(pg_stat_activity.pid)
                            FROM pg_stat_activity
                            WHERE pg_stat_activity.datname = :dbname
                            AND pid <> pg_backend_pid()
                        """
                        ),
                        {"dbname": validated_name},
                    )
                    # Drop database - validated_name is already validated, safe to use
                    conn.execute(text(f'DROP DATABASE IF EXISTS "{validated_name}"'))
                    # Create database
                    conn.execute(text(f'CREATE DATABASE "{validated_name}"'))
                    logger.info(f"Database '{validated_name}' recreated successfully.")
                    db_was_created = True
                else:
                    logger.info(f"Database '{validated_name}' already exists. Connecting to existing database.")
                    db_was_created = False
            else:
                # Create database
                logger.info(f"Creating database '{validated_name}'...")
                conn.execute(text(f'CREATE DATABASE "{validated_name}"'))
                logger.info(f"Database '{validated_name}' created successfully.")
                db_was_created = True
    finally:
        # Dispose of the admin engine to clean up connections
        admin_engine.dispose()

    # Use credentials with the specified database
    db_creds_with_db = db_credentials.with_database(validated_name)
    engine = create_engine(db_creds_with_db.to_url())

    # Create tables
    # Get metadata from any ORM class (they all share the same Base)
    if orm_classes:
        first_class = next(iter(orm_classes.values()))
        first_class.metadata.create_all(engine)
        logger.info(f"Created {len(orm_classes)} tables in database '{validated_name}'")

    return engine, db_was_created
