import sqlglot
from sqlglot import exp


ALLOWED_COLUMNS = {
    "country",
    "country_id",
    "country_iso3",
    "date",
    "population",
    "region",
    "is_aggregate",
}


def validate_sql(
    sql: str,
    allowed_tables: dict[str, set[str]]
    ) -> str:
    """Validate a simple query against existing tables."""

    # 1. Parse the SQL into statements.
    statements = [
        s for s in sqlglot.parse(sql, read="duckdb")
        if s is not None
    ]

    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is allowed.")

    query = statements[0]

    # 2. Only a SELECT statement is accepted.
    if not isinstance(query, exp.Select):
        raise ValueError("Only SELECT queries are allowed.")

    tables = list(query.find_all(exp.Table))

    #check 
    if len(tables) != 1:
        raise ValueError("Exactly one approved table is required.")

    table_name = tables[0].name

    if table_name not in allowed_tables:
        raise ValueError(f"Unapproved table: {table_name}")

    allowed_columns = allowed_tables[table_name]

    # 5. Allow a small set of analytical functions.
    allowed_functions = (
        exp.Cast, exp.Count, exp.Sum,
        exp.Avg, exp.Min, exp.Max, exp.And,
        exp.Or, exp.Case, exp.If
    )

    for function in query.find_all(exp.Func):
        if not isinstance(function, allowed_functions):
            raise ValueError("Unapproved SQL function.")

    # 6. Check column references.
    aliases = {
        a.alias for a in query.find_all(exp.Alias)
    }

    for column in query.find_all(exp.Column):
        if column.name not in ALLOWED_COLUMNS | aliases:
            raise ValueError(f"Unknown column: {column.name}")

    return query.sql(dialect="duckdb")

if __name__ == "__main__":

    queries = [
        "SELECT date, population FROM population",
        "DROP TABLE population",
        "SELECT * FROM read_csv('private.csv')",
    ]

    for sql in queries:
        try:
            print("ACCEPTED:", validate_sql(sql))
        except ValueError as error:
            print("REJECTED:", error)