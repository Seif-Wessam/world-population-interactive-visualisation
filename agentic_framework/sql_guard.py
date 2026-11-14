
import sqlglot
from sqlglot import exp


# Analytical functions permitted in model-generated SQL.
ALLOWED_FUNCTIONS = (
    exp.Count,
    exp.Sum,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.Cast,
    exp.Coalesce,
    exp.Round,
    exp.Abs,
    exp.Nullif,
    exp.Case,
    exp.If,
    exp.And,
    exp.Or,
    exp.Not,
)

MAX_LIMIT = 1000


def validate_sql(
    sql: str,
    allowed_tables: dict[str, set[str]],
) -> str:
    """Validate model-generated SQL against the authorized DuckDB schema."""

    if not allowed_tables:
        raise ValueError("No authorized tables provided.")

    # 1. Parse SQL into an abstract syntax tree.
    try:
        statements = [
            statement
            for statement in sqlglot.parse(sql, read="duckdb")
            if statement is not None
        ]
    except sqlglot.errors.ParseError as error:
        raise ValueError(f"Invalid SQL syntax: {error}") from error

    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is allowed.")

    query = statements[0]

    # 2. Permit only one complete SELECT query.
    if not isinstance(query, exp.Select):
        raise ValueError("Only SELECT statements are allowed.")

    if not query.expressions:
        raise ValueError(
            "SELECT must contain at least one expression."
        )

    if len(list(query.find_all(exp.Select))) != 1:
        raise ValueError("Nested SELECT queries are not allowed.")

    # 3. Reject unsupported SQL constructs.
    forbidden_clauses = (
        "with_",
        "into",
        "qualify",
        "windows",
        "laterals",
        "sample",
        "locks",
        "offset",
    )

    for clause in forbidden_clauses:
        if query.args.get(clause):
            raise ValueError(f"Unsupported SQL clause: {clause}")

    if any(query.find_all(exp.Subquery)):
        raise ValueError("Subqueries are not allowed.")

    # 4. Validate the FROM clause.
    from_clause = query.args.get("from_")

    if (
        from_clause is None
        or not isinstance(from_clause.this, exp.Table)
        or from_clause.expressions
    ):
        raise ValueError("A single approved base table is required.")

    joins = query.args.get("joins") or []

    if len(joins) > 1:
        raise ValueError("At most one JOIN is allowed.")

    tables = [from_clause.this]

    if joins:
        if not isinstance(joins[0].this, exp.Table):
            raise ValueError("JOIN must reference an approved table.")

        tables.append(joins[0].this)

    # 5. Resolve table names and their aliases.
    aliases = {}
    referenced_tables = []

    for table in tables:
        if (
            not isinstance(table.this, exp.Identifier)
            or table.args.get("db")
            or table.args.get("catalog")
            or table.args.get("pivots")
        ):
            raise ValueError("Unsupported table reference.")

        table_name = table.name
        alias = table.alias_or_name

        if table_name not in allowed_tables:
            raise ValueError(f"Unauthorized table: {table_name}")

        if alias in aliases:
            raise ValueError(f"Duplicate table alias: {alias}")

        aliases[alias] = table_name
        referenced_tables.append(table_name)

    # Ensure no additional tables are hidden elsewhere.
    if len(list(query.find_all(exp.Table))) != len(tables):
        raise ValueError("Unexpected table reference.")

    # 6. Permit only the defined observations-metadata JOIN.
    if joins:
        join = joins[0]

        if set(referenced_tables) != {
            "observations",
            "indicators",
        }:
            raise ValueError("Unauthorized table combination.")

        if (
            (join.args.get("kind") or "").upper()
            not in ("", "INNER")
            or join.args.get("side")
            or join.args.get("method")
            or join.args.get("using")
        ):
            raise ValueError("Only explicit INNER JOIN is supported.")

        condition = join.args.get("on")

        if not isinstance(condition, exp.EQ):
            raise ValueError("JOIN must use an equality condition.")

        left = condition.left
        right = condition.right

        if not (
            isinstance(left, exp.Column)
            and isinstance(right, exp.Column)
        ):
            raise ValueError("Invalid JOIN condition.")

        join_columns = {
            (aliases.get(left.table), left.name),
            (aliases.get(right.table), right.name),
        }

        expected_columns = {
            ("observations", "indicator_id"),
            ("indicators", "indicator_id"),
        }

        if join_columns != expected_columns:
            raise ValueError(
                "Tables must JOIN on their indicator_id columns."
            )

    # 7. Reject unauthorized SQL functions.
    for function in query.find_all(exp.Func):
        if not isinstance(function, ALLOWED_FUNCTIONS):
            raise ValueError(
                f"Unauthorized SQL function: {function.sql_name()}"
            )

    # 8. Reject SELECT * while allowing COUNT(*).
    for star in query.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):
            raise ValueError("SELECT * is not allowed.")

    # 9. Validate every column against the actual schema.
    output_aliases = {
        expression.alias
        for expression in query.expressions
        if isinstance(expression, exp.Alias)
    }

    for column in query.find_all(exp.Column):
        column_name = column.name
        table_alias = column.table

        if table_alias:
            if table_alias not in aliases:
                raise ValueError(
                    f"Unknown table alias: {table_alias}"
                )

            table_name = aliases[table_alias]

            if column_name not in allowed_tables[table_name]:
                raise ValueError(
                    f"Unknown column: {table_alias}.{column_name}"
                )

        else:
            matching_tables = [
                table_name
                for table_name in referenced_tables
                if column_name in allowed_tables[table_name]
            ]

            if len(matching_tables) == 1:
                continue

            # Allow result aliases in ORDER BY, GROUP BY and HAVING.
            alias_context = column.find_ancestor(
                exp.Order,
                exp.Group,
                exp.Having,
            )

            if (
                len(matching_tables) == 0
                and column_name in output_aliases
                and alias_context is not None
            ):
                continue

            if len(matching_tables) > 1:
                raise ValueError(
                    f"Ambiguous column: {column_name}"
                )

            raise ValueError(f"Unknown column: {column_name}")

    # 10. Restrict explicit result limits.
    limit = query.args.get("limit")

    if limit is not None:
        limit_expression = limit.expression

        if not isinstance(limit_expression, exp.Literal):
            raise ValueError("LIMIT must be a constant integer.")

        try:
            limit_value = int(limit_expression.this)
        except (TypeError, ValueError):
            raise ValueError("LIMIT must be an integer.") from None

        if not 1 <= limit_value <= MAX_LIMIT:
            raise ValueError(
                f"LIMIT must be between 1 and {MAX_LIMIT}."
            )

    # 11. Return normalized, validated DuckDB SQL.
    return query.sql(dialect="duckdb")
