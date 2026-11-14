import pytest

from agentic_framework.sql_guard import validate_sql


ALLOWED_TABLES = {
    "observations": {
        "indicator_id",
        "country_iso3",
        "year",
        "value",
    },
    "indicators": {
        "indicator_id",
        "name",
        "unit",
    },
}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT year FROM observations",
        "SELECT AVG(value) FROM observations",
        "SELECT COUNT(*) FROM observations",
        "SELECT country_iso3 FROM observations LIMIT 10",
    ],
)
def test_valid_queries(sql):
    result = validate_sql(sql, ALLOWED_TABLES)

    assert isinstance(result, str)
    assert result



# ---------------------------------------------------------
# Additional tests: analytical functionality
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        # Aggregation
        """
        SELECT country_iso3, AVG(value) AS avg_value
        FROM observations
        GROUP BY country_iso3
        ORDER BY avg_value DESC
        LIMIT 10
        """,

        # Conditional aggregation
        """
        SELECT
            MAX(CASE WHEN year = 2023 THEN value END)
            - MAX(CASE WHEN year = 2015 THEN value END)
            AS change
        FROM observations
        WHERE country_iso3 = 'CHE'
        """,

        # Metadata join
        """
        SELECT o.year, o.value, i.unit
        FROM observations AS o
        JOIN indicators AS i
            ON o.indicator_id = i.indicator_id
        WHERE o.country_iso3 = 'CHE'
        ORDER BY o.year
        """,

        # Reversed join equality
        """
        SELECT o.year, i.name
        FROM observations AS o
        JOIN indicators AS i
            ON i.indicator_id = o.indicator_id
        """,

        # Count all observations
        """
        SELECT COUNT(*) AS n
        FROM observations
        """,

        # Filtering and grouping
        """
        SELECT year, SUM(value) AS total
        FROM observations
        WHERE year BETWEEN 2015 AND 2023
        GROUP BY year
        HAVING SUM(value) > 0
        ORDER BY year
        """,
    ],
)
def test_complex_valid_queries(sql):
    result = validate_sql(sql, ALLOWED_TABLES)

    assert isinstance(result, str)
    assert result.strip()


# ---------------------------------------------------------
# Additional tests: unauthorized operations
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE observations",
        "DELETE FROM observations",
        "UPDATE observations SET value = 0",
        "INSERT INTO observations VALUES (1)",
        "CREATE TABLE backup AS SELECT * FROM observations",
        "ALTER TABLE observations ADD COLUMN test INTEGER",
        "TRUNCATE TABLE observations",
        "SELECT value FROM observations; DROP TABLE observations",
    ],
)
def test_reject_database_modifications(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, ALLOWED_TABLES)


# ---------------------------------------------------------
# Additional tests: table and column authorization
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        # Unauthorized table
        "SELECT password FROM users",

        # Unknown column
        "SELECT password FROM observations",

        # Invalid qualified column
        "SELECT i.country_iso3 FROM indicators AS i",

        # Unknown table alias
        "SELECT x.value FROM observations AS o",

        # Ambiguous unqualified column
        """
        SELECT indicator_id
        FROM observations AS o
        JOIN indicators AS i
            ON o.indicator_id = i.indicator_id
        """,

        # Cross join
        """
        SELECT COUNT(*)
        FROM observations AS a
        CROSS JOIN observations AS b
        """,

        # Invalid join relationship
        """
        SELECT o.year, i.name
        FROM observations AS o
        JOIN indicators AS i
            ON o.country_iso3 = i.indicator_id
        """,
    ],
)
def test_reject_unauthorized_references(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, ALLOWED_TABLES)


# ---------------------------------------------------------
# Additional tests: dangerous or complex SQL constructs
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        # External file access
        "SELECT * FROM read_csv('/private/data.csv')",

        # External filesystem access
        "SELECT * FROM read_parquet('private.parquet')",

        # Nested SELECT
        """
        SELECT value
        FROM observations
        WHERE value > (
            SELECT AVG(value)
            FROM observations
        )
        """,

        # CTE
        """
        WITH x AS (
            SELECT year, value FROM observations
        )
        SELECT year FROM x
        """,

        # Set operation
        """
        SELECT year FROM observations
        UNION ALL
        SELECT year FROM observations
        """,

        # Window function
        """
        SELECT
            year,
            ROW_NUMBER() OVER (ORDER BY year) AS rn
        FROM observations
        """,

        # Unrestricted output of all columns
        "SELECT * FROM observations",

        # Qualified wildcard
        "SELECT o.* FROM observations AS o",
    ],
)
def test_reject_unsupported_constructs(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, ALLOWED_TABLES)


# ---------------------------------------------------------
# Additional tests: query limits
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "limit_value",
    [1, 10, 100, 999, 1000],
)
def test_valid_limits(limit_value):
    sql = (
        "SELECT year FROM observations "
        f"LIMIT {limit_value}"
    )

    result = validate_sql(sql, ALLOWED_TABLES)

    assert result


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT year FROM observations LIMIT 0",
        "SELECT year FROM observations LIMIT 1001",
        "SELECT year FROM observations LIMIT -1",
        "SELECT year FROM observations LIMIT 'ten'",
        "SELECT year FROM observations LIMIT 10 OFFSET 500",
    ],
)
def test_reject_invalid_limits(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, ALLOWED_TABLES)


# ---------------------------------------------------------
# Additional tests: parser edge cases
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "SELECT",
        "SELECT FROM observations",
        "SELECT year FROM",
    ],
)
def test_reject_invalid_sql(sql):
    with pytest.raises(ValueError):
        validate_sql(sql, ALLOWED_TABLES)


def test_reject_empty_authorized_schema():
    with pytest.raises(ValueError):
        validate_sql(
            "SELECT year FROM observations",
            {},
        )


def test_accept_sql_comments():
    sql = """
    -- Retrieve annual observations
    SELECT year, value
    FROM observations
    WHERE country_iso3 = 'CHE'
    """

    result = validate_sql(sql, ALLOWED_TABLES)

    assert result



# ---------------------------------------------------------
# Logical operators: AND, OR, NOT
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        # AND
        """
        SELECT year, value
        FROM observations
        WHERE country_iso3 = 'CHE'
          AND year >= 2015
        """,

        # OR
        """
        SELECT year, value
        FROM observations
        WHERE country_iso3 = 'CHE'
           OR country_iso3 = 'FRA'
        """,

        # NOT
        """
        SELECT year, value
        FROM observations
        WHERE NOT country_iso3 = 'CHE'
        """,

        # Combined AND and OR
        """
        SELECT year, value
        FROM observations
        WHERE country_iso3 = 'CHE'
          AND (year = 2022 OR year = 2023)
        """,

        # Combined AND, OR and NOT
        """
        SELECT year, value
        FROM observations
        WHERE NOT (
            country_iso3 = 'FRA'
            OR year < 2015
        )
        AND value > 0
        """,

        # Logical operators with aggregation
        """
        SELECT country_iso3, AVG(value) AS avg_value
        FROM observations
        WHERE year >= 2015
          AND year <= 2023
          AND NOT country_iso3 = 'FRA'
        GROUP BY country_iso3
        HAVING AVG(value) > 0
        """,
    ],
)
def test_logical_operators(sql):
    validated_sql = validate_sql(sql, ALLOWED_TABLES)

    assert isinstance(validated_sql, str)
    assert validated_sql.strip()
