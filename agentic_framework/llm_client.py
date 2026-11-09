
import os
from pathlib import Path
from urllib import response

from dotenv import load_dotenv
from huggingface_hub import InferenceClient

# 1. Load environment variables from this module's .env
load_dotenv(Path(__file__).with_name(".env"))

# 2. Retrieve configuration
token = os.environ["HF_TOKEN"]
model = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-9B:cheapest")

# 3. Initialize the Hugging Face inference client
client = InferenceClient(
    api_key=token,
    provider="deepinfra"
)


def get_model_response(prompt: str) -> str:
    """
    Send a prompt to Qwen and return its text response.
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=512,
        temperature=0.7,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": False
            }
        }
    )

    choice = response.choices[0]
    content = choice.message.content or ""

    if not content.strip():
        raise RuntimeError("Qwen returned an empty response.")

    return content




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



if __name__ == "__main__":
    # Run this test only when executing llm_client.py directly.
    test_prompt = "What is 2 + 2? Answer with only the number."

    print(get_model_response(test_prompt))