
import asyncio
import json

from mcp import Client

from llm_client import get_model_completion
from mcp_client import MCP_URL


ALLOWED_TOOLS = {
    "data360_search_indicators",
    "data360_get_disaggregation",
    "data360_get_data"
}


async def answer_question(question: str):
    """
    Args:
        question (str): The user's question to answer.
    Returns:
        dict: A dictionary containing the final answer and the original mcp responses.
    """
    async with Client(MCP_URL) as mcp:

        # 1. Discover the tools and their real input schemas
        response = await mcp.list_tools()

        available = {
            tool.name: tool
            for tool in response.tools
            if tool.name in ALLOWED_TOOLS
        }

        if set(available) != ALLOWED_TOOLS:
            raise RuntimeError("Some required MCP tools are missing.")

        # 2. Translate MCP tool definitions into Qwen's format
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema
                }
            }
            for tool in available.values()
        ]

        # 3. Initialize the conversation
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a World Bank data assistant. "
                    "Use the available tools to retrieve real data. "
                    "Search for the indicator, check its coverage, "
                    "then retrieve observations. Never invent values. "
                    "Use WDI and filter for the requested country and year."
                )
            },
            {"role": "user", "content": question}
        ]

        retrieved_data = False

        mcp_data_results = []
        
        # 4. Allow up to five model turns
        for step in range(5):

            completion = get_model_completion(messages, tools)
            message = completion.choices[0].message
            calls = message.tool_calls or []

            # No tool calls means Qwen is trying to answer
            if not calls:
                if not retrieved_data:
                    raise RuntimeError(
                        "Qwen answered without retrieving observations."
                    )

                print("\nFinal answer:")
                print(message.content)
                return {
                    "answer": message.content,
                    "data_responses": mcp_data_results
                }

            # 5. Preserve the assistant's tool-call proposal
            assistant_calls = []

            for call in calls:
                args = call.function.arguments

                if isinstance(args, str):
                    args = json.loads(args)

                if not isinstance(args, dict):
                    raise ValueError("Invalid tool arguments.")

                name = call.function.name

                if name not in available:
                    raise ValueError(f"Unapproved tool: {name}")

                assistant_calls.append({
                    "id": str(call.id),
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args)
                    }
                })

            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": assistant_calls
            })

            # 6. Python executes each approved MCP tool call
            for call, proposed in zip(calls, assistant_calls):
                name = proposed["function"]["name"]
                args = json.loads(proposed["function"]["arguments"])

                print(f"\nMCP call: {name}")
                print("Arguments:", args)

                result = await mcp.call_tool(name, args)

                if result.is_error:
                    raise RuntimeError(f"MCP error: {result.content}")

                payload = result.structured_content

                if payload is None:
                    payload = [
                        item.text
                        for item in result.content
                        if item.type == "text"
                    ]

                if isinstance(payload, dict) and payload.get("error"):
                    raise RuntimeError(str(payload["error"]))

                if name == "data360_get_data":
                    retrieved_data = True
                    mcp_data_results.append(payload)

                result_text = json.dumps(payload, default=str)

                print("Result preview:", result_text[:1000])

                # 7. Return the tool result to Qwen
                messages.append({
                    "role": "tool",
                    "tool_call_id": proposed["id"],
                    "content": result_text[:16000]
                })

        raise RuntimeError("Maximum model turns reached.")


if __name__ == "__main__":
    asyncio.run(
        answer_question(
            "What was Egypt's total population in 2025 "
            "according to the World Bank WDI?"
        )
    )
