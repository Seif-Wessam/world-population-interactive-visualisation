import asyncio
import os
from time import perf_counter

import pandas as pd
import pytest


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_ANSWER_TEST") != "1",
    reason="Opt-in test requiring real Qwen and MCP access.",
)
def test_live_answer(monkeypatch):
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    # Import only when the live test is enabled.
    from agentic_framework.main import answer_question

    question = (
        "How did Egypt's total population change between "
        "2000 and 2023? Report the population in both years, "
        "the absolute change in people, and the percentage change."
    )

    started = perf_counter()
    outcome = asyncio.run(answer_question(question))
    elapsed = perf_counter() - started

    # Print diagnostics before assertions so partial outcomes
    # remain inspectable when the test fails.
    print(f"\nElapsed: {elapsed:.1f} seconds")
    print("\nSelected datasets:", outcome["selections"])
    print("\nInitial SQL:\n", outcome["sql"])
    print("\nInitial results:\n", outcome["results"].to_string(index=False))
    print("\nStatus:", outcome.get("analysis_status"))
    print("Reason:", outcome.get("analysis_reason"))
    print("\nAnswer:\n", outcome.get("answer"))

    assert outcome["s3_prefixes"] == []
    assert isinstance(outcome["results"], pd.DataFrame)
    assert not outcome["results"].empty
    assert isinstance(outcome["sql"], str)
    assert outcome["sql"].strip()

    assert "answer" in outcome, "Controller is not integrated."
    assert isinstance(outcome["answer"], str)
    assert outcome["answer"].strip()
    assert "{{" not in outcome["answer"]
    assert "}}" not in outcome["answer"]

    assert outcome["analysis_status"] == "complete", (
        f"Analysis remained partial: {outcome['analysis_reason']}"
    )
    assert outcome["analysis_reason"] is None