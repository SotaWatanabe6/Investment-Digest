"""
Shared helper for calling Claude with enforced structured (JSON schema)
output. Every agent uses this rather than parsing free text, per PRD
Section 4.4.

Structured output is enforced via forced tool use: we define a single tool
whose input schema *is* the desired output schema, force the model to call
it, and read the tool call's arguments back as the result. This is more
reliable than asking the model to "respond in JSON" in the prompt text.
"""
from __future__ import annotations

import time

import anthropic

from models import AgentCallResult
from pricing import compute_cost_usd

_RESULT_TOOL_NAME = "submit_result"


def call_structured(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    user_content: str,
    schema: dict,
    max_tokens: int = 2048,
) -> tuple[AgentCallResult, int]:
    """Returns (AgentCallResult, duration_ms)."""
    started = time.monotonic()

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        tools=[
            {
                "name": _RESULT_TOOL_NAME,
                "description": "Submit the structured result for this task.",
                "input_schema": schema,
            }
        ],
        tool_choice={"type": "tool", "name": _RESULT_TOOL_NAME},
    )

    duration_ms = int((time.monotonic() - started) * 1000)

    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = compute_cost_usd(model, input_tokens, output_tokens)

    result = AgentCallResult(
        data=tool_use_block.input,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    return result, duration_ms
