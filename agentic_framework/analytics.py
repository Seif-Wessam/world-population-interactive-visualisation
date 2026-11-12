
import re
from collections.abc import Mapping

import duckdb
import pandas as pd

from agentic_framework.sql_guard import validate_sql


MAX_ROWS = 1000

# Table names are supplied by trusted Python code, not Qwen.
VALID_TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def create_connection(
    tables: Mapping[str, pd.DataFrame]
) -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB database from trusted DataFrames."""

    con = duckdb.connect(
        ":memory:",
        config={
            "memory_limit": "256MB",
            "threads": "2",
            "max_temp_directory_size": "256MB",
        },
    )

    try:
        if not tables:
            raise ValueError("At least one table is required.")

        for table_name, df in tables.items():

            if not VALID_TABLE_NAME.fullmatch(table_name):
                raise ValueError(f"Invalid table name: {table_name}")

            if not isinstance(df, pd.DataFrame):
                raise TypeError(f"{table_name} must be a DataFrame.")

            if df.columns.duplicated().any():
                raise ValueError(f"Duplicate columns in {table_name}.")

            source_name = f"__source_{table_name}"

            con.register(source_name, df)

            try:
                con.execute(
                    f'CREATE TABLE "{table_name}" AS '
                    f'SELECT * FROM "{source_name}"'
                )
            finally:
                con.unregister(source_name)

        # All source DataFrames have now been copied into DuckDB.
        con.execute("SET enable_external_access = false")

        return con

    except Exception:
        con.close()
        raise


def inspect_tables(
    con: duckdb.DuckDBPyConnection,
    approved_tables: set[str],
) -> dict[str, dict[str, str]]:
    """Discover columns for explicitly approved database tables."""

    existing_tables = {
        row[0]
        for row in con.execute("SHOW TABLES").fetchall()
    }

    if not approved_tables:
        raise ValueError("No approved tables supplied.")

    unknown = approved_tables - existing_tables

    if unknown:
        raise ValueError(f"Missing approved tables: {sorted(unknown)}")

    result = {}

    for table_name in sorted(approved_tables):

        if not VALID_TABLE_NAME.fullmatch(table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        rows = con.execute(
            f'DESCRIBE "{table_name}"'
        ).fetchall()

        result[table_name] = {
            row[0]: row[1]
            for row in rows
        }

    return result


def get_schema(
    con: duckdb.DuckDBPyConnection,
    approved_tables: set[str],
) -> str:
    """Generate SQL schema definitions for Qwen."""

    tables = inspect_tables(con, approved_tables)

    definitions = []

    for table_name, columns in tables.items():

        column_ddl = ",\n    ".join(
            f'"{name}" {dtype}'
            for name, dtype in columns.items()
        )

        definitions.append(
            f'CREATE TABLE "{table_name}" (\n'
            f'    {column_ddl}\n'
            f');'
        )

    return "\n\n".join(definitions)


def execute_query(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    approved_tables: set[str],
) -> pd.DataFrame:
    """Validate and execute model-generated SQL."""

    schema = inspect_tables(con, approved_tables)

    allowed_columns = {
        table: set(columns)
        for table, columns in schema.items()
    }

    validated_sql = validate_sql(
        sql,
        allowed_tables=allowed_columns,
    )

    cursor = con.execute(validated_sql)

    columns = [item[0] for item in cursor.description]

    rows = cursor.fetchmany(MAX_ROWS + 1)

    if len(rows) > MAX_ROWS:
        con.abort()
        raise ValueError(
            f"Query returned more than {MAX_ROWS} rows."
        )

    return pd.DataFrame(rows, columns=columns)
