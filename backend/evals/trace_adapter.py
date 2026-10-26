"""Adapt captured ADK events into DeepEval's ordered trace spans."""

from __future__ import annotations

from typing import Any


async def record_adk_event(event: Any) -> None:
    """Record one ADK event as nested agent/tool spans under the eval trace.

    Google ADK events are captured by the eval runner rather than automatically
    traced by DeepEval. This adapter preserves event order and omits model
    thought-only text from the evaluation trace.
    """
    from deepeval.tracing import observe, update_current_span

    author = str(getattr(event, "author", "unknown"))
    get_calls = getattr(event, "get_function_calls", None)
    calls = get_calls() or [] if callable(get_calls) else []
    for call in calls:
        name = str(getattr(call, "name", "unknown_tool"))
        args = dict(getattr(call, "args", {}) or {})

        @observe(type="tool")
        async def record_tool_call(tool_name: str, parameters: dict[str, Any]) -> None:
            update_current_span(
                input={"tool": tool_name, "arguments": parameters},
                output="Tool call issued by the ADK agent",
            )

        await record_tool_call(name, args)

    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    text_parts = [
        str(getattr(part, "text", ""))
        for part in parts
        if getattr(part, "text", None) and not getattr(part, "thought", False)
    ]
    if text_parts:

        @observe(type="agent")
        async def record_agent_output(stage: str, output: str) -> None:
            update_current_span(input={"stage": stage}, output=output)

        await record_agent_output(author, "\n".join(text_parts))
