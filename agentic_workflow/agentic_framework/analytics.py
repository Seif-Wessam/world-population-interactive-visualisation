
import json

import boto3
import duckdb
import pandas as pd


BUCKET = "webgis-population-app"
KEY = "data/enriched_population_data.json"


def load_population_data() -> pd.DataFrame:
    """Retrieve population data from S3 as a pandas DataFrame."""
    s3 = boto3.client("s3", region_name="eu-north-1")

    response = s3.get_object(Bucket=BUCKET, Key=KEY)
    records = json.loads(response["Body"].read())

    return pd.DataFrame(records)



def create_connection(df: pd.DataFrame):
    """Create a restricted in-memory DuckDB database."""

    con = duckdb.connect(
        ":memory:",
        config={
            "memory_limit": "256MB",
            "threads": "2",
            "max_temp_directory_size": "256MB",
        }
    )

    try:
        # Load trusted pandas data into a DuckDB-owned table
        con.register("population_source", df)

        con.execute("""
            CREATE TABLE population AS
            SELECT * FROM population_source
        """)

        con.unregister("population_source")

        # Prevent subsequent SQL from accessing external files
        con.execute("SET enable_external_access = false")

        return con

    except Exception:
        con.close()
        raise



def get_schema(con) -> str:
    """Discover DuckDB tables and their column definitions."""

    # Discover the available tables
    tables = con.execute("SHOW TABLES").fetchall()

    definitions = []

    for (table_name,) in tables:

        # Retrieve the columns belonging to this table
        rows = con.execute(
            f'DESCRIBE "{table_name}"'
        ).fetchall()

        columns = ",\n    ".join(
            f'"{row[0]}" {row[1]}'
            for row in rows
        )

        definitions.append(
            f'CREATE TABLE "{table_name}" (\n'
            f'    {columns}\n'
            f');'
        )

    return "\n\n".join(definitions)


from sql_guard import validate_sql
MAX_ROWS = 1000

def execute_query(con, sql: str) -> pd.DataFrame:
    """Validate SQL and return at most 1000 result rows."""

    # 1. Check the query against our SQL rules
    validated_sql = validate_sql(sql)

    # 2. Execute the approved query
    cursor = con.execute(validated_sql)

    # 3. Keep the output column names
    columns = [item[0] for item in cursor.description]

    # 4. Fetch at most 1001 rows, not the whole result
    rows = cursor.fetchmany(MAX_ROWS + 1)

    # 5. Reject results larger than our limit
    if len(rows) > MAX_ROWS:
        con.abort()
        raise ValueError(
            f"Query returned more than {MAX_ROWS} rows."
        )

    # 6. Convert the small result to pandas
    return pd.DataFrame(rows, columns=columns)


def population_series(df: pd.DataFrame) -> pd.Series:
    """Convert query results into population values indexed by year."""
    year_col = "year" if "year" in df.columns else "date"

    result = df[[year_col, "population"]].copy()

    result["year"] = result[year_col].astype(int)
    result["population"] = pd.to_numeric(result["population"])

    if result["year"].duplicated().any():
        raise ValueError("Duplicate observation years.")

    return (
        result
        .set_index("year")["population"]
        .sort_index()
    )
