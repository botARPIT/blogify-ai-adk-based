"""Dump the ADK agent tree and flag agents that break cost attribution.

Run:  python -m scripts.dump_agent_models
       python -m scripts.dump_agent_models --tokens 50000

Three classes of problem make an agent's cost invisible while it still bills you:

1. ``agent.name`` absent from ``STAGE_BY_AUTHOR`` — ``_extract_costs_from_events`` drops every
   event whose author is unmapped, so the tokens are never committed to the ledger.
2. ``model`` string absent from ``MODEL_PRICING`` — ``get_model_cost`` silently substitutes the
   flash price instead of raising, so the amount recorded is wrong rather than missing.
3. ``LoopAgent.max_iterations > 1`` — a stage inside the loop can run more than once, and
   ``_commit_costs`` skips any stage already recorded ``COMPLETED`` for the session.

All three are reported as WARN lines after the tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.pipeline import APP, STAGE_BY_AUTHOR  # noqa: E402
from src.config.budget_config import MODEL_PRICING, get_model_cost  # noqa: E402

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"


def colour_enabled() -> bool:
    return sys.stdout.isatty()


def paint(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if colour_enabled() else text


def model_name_of(agent: Any) -> str | None:
    """Return the underlying model id string for an agent, or None for composite agents.

    ADK wraps the id in different client classes over time (Gemini, LiteLLM, ...). All of them
    carry the id on a ``model`` attribute, so unwrap generically instead of isinstance-guarding a
    specific client -- a bare ``str(model)`` would dump the whole object repr into the report.
    """
    model = getattr(agent, "model", None)
    if model is None:
        return None
    if isinstance(model, str):
        return model
    inner = getattr(model, "model", None)
    if isinstance(inner, str):
        return inner
    return type(model).__name__


def describe(agent: Any, indent: int, tokens: int, warnings: list[str]) -> None:
    pad = "  " * indent
    branch = "└─ " if indent else ""
    kind = type(agent).__name__
    model = model_name_of(agent)
    name = getattr(agent, "name", "?")

    header = f"{pad}{branch}{paint(name, BOLD)} {paint(f'[{kind}]', DIM)}"

    if model is None:
        header += paint("  composite (no model)", DIM)
        max_iter = getattr(agent, "max_iterations", None)
        if max_iter:
            header += paint(f"  max_iterations={max_iter}", YELLOW)
    else:
        price = MODEL_PRICING.get(model)
        if price is None:
            header += paint(f"  model={model}  UNPRICED", RED)
            warnings.append(
                f"{name}: model '{model}' is not in MODEL_PRICING — get_model_cost "
                f"silently charges it at the flash rate "
                f"(${MODEL_PRICING['gemini-2.5-flash']}/1k tokens)"
            )
        else:
            header += paint(f"  model={model}", CYAN)
            header += paint(f"  ${price}/1k", DIM)
            header += paint(f"  ≈ ${get_model_cost(model, tokens):.6f} @ {tokens:,}tok", DIM)

        if name not in STAGE_BY_AUTHOR:
            stage = "—"
            header += paint(f"  → stage={stage}  UNMETERED", RED)
            warnings.append(
                f"{name}: absent from STAGE_BY_AUTHOR — every usage_metadata event for this "
                f"agent is discarded by _extract_costs_from_events; the tokens are spent but "
                f"never reach agent_runs, budget_ledger, or budget_spent_*"
            )
        else:
            header += paint(f"  → stage={STAGE_BY_AUTHOR[name]}", GREEN)

    output_key = getattr(agent, "output_key", None)
    if output_key:
        header += paint(f"  → {output_key}", DIM)

    print(header, flush=True)

    schema = getattr(agent, "output_schema", None)
    if schema is not None:
        print(f"{pad}   {paint('schema', DIM)} {schema.__name__}", flush=True)

    tools = getattr(agent, "tools", None) or []
    if tools:
        names = [getattr(t, "__name__", type(t).__name__) for t in tools]
        print(f"{pad}   {paint('tools', DIM)}  {', '.join(names)}", flush=True)

    max_iter = getattr(agent, "max_iterations", None)
    if max_iter and max_iter > 1:
        warnings.append(
            f"{name}: max_iterations={max_iter} — a contained stage may execute more than "
            f"once per run, but _commit_costs skips stages already COMPLETED for the session, "
            f"so repeat executions are unmetered"
        )

    for child in getattr(agent, "sub_agents", None) or []:
        describe(child, indent + 1, tokens, warnings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tokens",
        type=int,
        default=50_000,
        help="token count used for the per-agent cost estimate (default: 50000)",
    )
    args = parser.parse_args()

    warnings: list[str] = []

    print()
    print(paint("  ADK agent tree", BOLD), flush=True)
    print(paint(f"  {'─' * 60}", DIM), flush=True)

    describe(APP.root_agent, 0, args.tokens, warnings)

    metered = set(STAGE_BY_AUTHOR)
    print()
    print(paint("  cost attribution", BOLD), flush=True)
    print(paint(f"  {'─' * 60}", DIM), flush=True)
    print(f"  mapped stages : {', '.join(sorted(metered))}", flush=True)
    print(f"  priced models : {', '.join(sorted(MODEL_PRICING))}", flush=True)
    print(f"  default token : {args.tokens:,}", flush=True)
    print()

    if warnings:
        print(paint(f"  {len(warnings)} warning(s)", RED + BOLD), flush=True)
        print()
        for i, w in enumerate(warnings, 1):
            print(f"  {paint(f'[{i}]', RED)} {w}", flush=True)
            print()
        return 1

    print(paint("  no attribution problems detected", GREEN), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())