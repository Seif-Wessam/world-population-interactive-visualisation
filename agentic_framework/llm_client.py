
import os
from pathlib import Path
from urllib import response
import json
import re

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

# 1. Load environment variables from this module's .env
load_dotenv(Path(__file__).with_name(".env"))

# 2. Retrieve configuration
token = os.environ["HF_TOKEN"]
model = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-9B")

# 3. Initialize the Hugging Face inference client
client = InferenceClient(
    api_key=token,
    provider="deepinfra" #provider="deepinfra"
)


def get_model_response(prompt: str) -> str:
    """
    Send a prompt to Qwen and return its text response.
    """

    from huggingface_hub.errors import HfHubHTTPError

    try:
        response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4196,
                temperature=0.7,
                extra_body={
                    "chat_template_kwargs": {
                        "enable_thinking": False
                    }
                }
            )
    except HfHubHTTPError as exc:
        print("HTTP status:", exc.response.status_code)
        print("Response body:", exc.response.text)
        raise

    choice = response.choices[0]
    content = choice.message.content or ""

    if not content.strip():
        raise RuntimeError("Qwen returned an empty response.")

    return content


def decompose_question(question: str) -> list[dict]:
    """Identify the distinct measurements needed to answer a question."""

    prompt = f"""
You are planning data retrieval for a World Bank analytics system.

Identify the minimum set of distinct statistical measurements
needed to answer the user's question.

Do NOT search for World Bank indicators.
Do NOT invent indicator IDs.
Do NOT include derived calculations as separate measurements
when they can be calculated from one underlying indicator.

Preserve important qualifiers such as:
- total, male, female
- per capita versus absolute
- national estimate versus modeled ILO estimate
- measurement units and definitions

Return ONLY a JSON array. Each element must contain:
- metric: a specific measurement description
- country_code: ISO 3166-1 alpha-3 country code
- start_year: integer
- end_year: integer

For multiple countries, use a separate requirement
for each measurement/country combination.

User question:
{question}
"""

    content = get_model_response(prompt).strip()

    if content.startswith("```"):
        content = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            content,
        ).strip()

    requirements = json.loads(content)

    if not isinstance(requirements, list):
        raise ValueError("Expected a list of measurements.")

    if not 1 <= len(requirements) <= 5:
        raise ValueError("Expected between 1 and 5 measurements.")

    validated = []
    seen = set()

    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ValueError("Invalid measurement requirement.")

        metric = requirement.get("metric")
        country = requirement.get("country_code")
        start = requirement.get("start_year")
        end = requirement.get("end_year")

        if not isinstance(metric, str) or not metric.strip():
            raise ValueError("Missing measurement description.")

        if not isinstance(country, str) or not re.fullmatch(
            r"[A-Z]{3}", country
        ):
            raise ValueError("Invalid country code.")

        if (
            type(start) is not int
            or type(end) is not int
            or not 1960 <= start <= end <= 2100
        ):
            raise ValueError("Invalid year range.")

        item = {
            "metric": metric.strip(),
            "country_code": country,
            "start_year": start,
            "end_year": end,
        }

        identity = (
            item["metric"].casefold(),
            country,
            start,
            end,
        )

        if identity not in seen:
            validated.append(item)
            seen.add(identity)

    return validated


def get_model_completion(messages: list, tools: list):
    """
    Send a conversation and available tool definitions to Qwen.

    Returns the full API response, including proposed tool calls.
    """
    return client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        max_tokens=1200
    )
