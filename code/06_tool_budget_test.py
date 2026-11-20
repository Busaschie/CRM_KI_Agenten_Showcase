"""Tool budget as a regression test: the tool list and the server instructions are context cost in every chat.

Origin: apps/assistant/tests/test_tool_budget.py (measured the way an MCP client receives the list).
Excerpt, shortened; not runnable on its own.
"""
MAX_TOOLS = 60
MAX_DESCRIPTIONS = 25_650        # characters over all tool descriptions
MAX_SCHEMAS = 18_200             # characters over all parameter schemas (JSON)
MAX_INSTRUCTIONS = 3_800         # server instructions per path; the connector only passes the first ~4,096 bytes
MAX_INSTRUCTION_BYTES = 3_950    # UTF-8 bytes (umlauts count double)


def test_limits_hold(numbers):
    assert numbers["tools"] <= MAX_TOOLS, "A new tool needs an offset: remove or merge another one"
    assert numbers["descriptions"] <= MAX_DESCRIPTIONS
    assert numbers["schemas"] <= MAX_SCHEMAS
    assert numbers["instructions"] <= MAX_INSTRUCTIONS


# Rules belong in the description of the tool that is called first (it is loaded together with that tool), not into the always-loaded
# instructions. Safety rules (confirmation, stop window, protected characteristics) stay in the instructions; a second test checks the placement.
