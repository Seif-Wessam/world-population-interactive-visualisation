from agentic_framework.analytics import create_connection, execute_query, load_population_data


df = load_population_data()
con = create_connection(df)

try:
    # Test A: A normal, small query
    sql = """
    SELECT date, population
    FROM population
    WHERE country_iso3 = 'CHE'
        AND CAST(date AS INTEGER) BETWEEN 2010 AND 2025
    ORDER BY date
    """

    result = execute_query(con, sql)

    print("Test A: Small query")
    print(result)
    print("PASS:", len(result), "rows returned")

    # Test B: An excessively large result
    print("\nTest B: Oversized query")

    try:
        execute_query(
            con,
            "SELECT * FROM population"
        )
        print("FAIL: Oversized result was accepted")

    except ValueError as error:
        print("PASS: Query rejected:", error)

    # Test C: Verify our resource settings
    print("\nTest C: DuckDB settings")

    settings = con.execute("""
        SELECT
            current_setting('memory_limit') AS memory,
            current_setting('threads') AS threads,
            current_setting('enable_external_access') AS external
    """).df()

    print(settings)

finally:
    con.close()
