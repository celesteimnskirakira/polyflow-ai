from __future__ import annotations
import asyncio
import re
from typing import Optional
from polyflow.schema.workflow import Step
from polyflow.engine.template import TemplateContext, render
from polyflow.models import get_model_adapter
from polyflow.config import Config


def _parse_timeout(timeout_str: str) -> float:
    """Parse '60s', '2m', '30' into seconds as float."""
    s = timeout_str.strip().lower()
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


def _evaluate_condition(condition: str, ctx: TemplateContext) -> bool:
    """
    Safely evaluate a simple condition like:
      {{hitl.validate.choice}} == 'revise'
      {{hitl.validate.choice}} != 'abort'

    Renders the template first, then parses LHS OP RHS without eval().
    """
    rendered = render(condition, ctx).strip()

    for op in ("==", "!="):
        if op in rendered:
            left, _, right = rendered.partition(op)
            lhs = left.strip().strip("'\"")
            rhs = right.strip().strip("'\"")
            return (lhs == rhs) if op == "==" else (lhs != rhs)

    # Fallback: truthy check
    return bool(rendered) and rendered.lower() not in ("false", "0", "none", "")


async def execute_step(step: Step, ctx: TemplateContext, config: Config) -> Optional[str]:
    """Execute a single step. Returns None if skipped."""
    if step.condition and not _evaluate_condition(step.condition, ctx):
        return None

    if step.type == "parallel":
        return await execute_parallel(step, ctx, config)

    adapter = get_model_adapter(step.model, config)
    api_key = config.get_api_key(step.model)
    prompt = render(step.prompt, ctx)
    timeout_secs = _parse_timeout(step.timeout)

    for attempt in range(step.on_error.retry + 1):
        try:
            coro = adapter.complete(prompt, api_key=api_key, timeout=int(timeout_secs))
            return await asyncio.wait_for(coro, timeout=timeout_secs)
        except asyncio.TimeoutError:
            if attempt == step.on_error.retry:
                if step.on_error.fallback == "abort":
                    raise RuntimeError(f"Step '{step.id}' timed out after {step.timeout}")
                return None
        except Exception:
            if attempt == step.on_error.retry:
                if step.on_error.fallback == "abort":
                    raise
                return None
    return None


async def execute_parallel(step: Step, ctx: TemplateContext, config: Config) -> str:
    """Execute sub-steps in parallel, aggregate results."""

    async def run_substep(sub):
        adapter = get_model_adapter(sub.model, config)
        api_key = config.get_api_key(sub.model)
        prompt = render(sub.prompt, ctx)
        sub_timeout = _parse_timeout(sub.timeout)
        try:
            coro = adapter.complete(prompt, api_key=api_key, timeout=int(sub_timeout))
            return sub.id, await asyncio.wait_for(coro, timeout=sub_timeout)
        except Exception:
            if step.on_error.partial == "continue":
                return sub.id, None
            raise

    results = await asyncio.gather(*[run_substep(s) for s in step.steps])
    outputs = {sid: out for sid, out in results if out is not None}
    aggregated = _aggregate(outputs, step)

    # If aggregate.model is set, use that model to produce a final summary
    if step.aggregate and step.aggregate.model:
        default_prompt = (
            "Synthesize the following parallel model outputs into a single concise summary:\n\n"
            + aggregated
        )
        agg_prompt = (
            step.aggregate.prompt.replace("{{aggregated}}", aggregated)
            if step.aggregate.prompt
            else default_prompt
        )
        adapter = get_model_adapter(step.aggregate.model, config)
        api_key = config.get_api_key(step.aggregate.model)
        timeout_secs = _parse_timeout(step.timeout)
        aggregated = await asyncio.wait_for(
            adapter.complete(agg_prompt, api_key=api_key, timeout=int(timeout_secs)),
            timeout=timeout_secs,
        )

    return aggregated


def _aggregate(outputs: dict[str, str], step: Step) -> str:
    mode = step.aggregate.mode if step.aggregate else "raw"

    if mode == "raw":
        return "\n\n---\n\n".join(f"[{sid}]\n{out}" for sid, out in outputs.items())
    if mode == "diff":
        return "\n\n".join(f"## Review from {sid}:\n{out}" for sid, out in outputs.items())
    if mode == "vote":
        votes = [1 if "approve" in out.lower() else 0 for out in outputs.values()]
        verdict = "approved" if sum(votes) > len(votes) / 2 else "rejected"
        raw = "\n\n---\n\n".join(f"[{sid}]\n{out}" for sid, out in outputs.items())
        return f"Vote result: {verdict}\n\n{raw}"
    # summary: return raw (LLM summary done in runner if aggregate.model is set)
    return "\n\n---\n\n".join(f"[{sid}]\n{out}" for sid, out in outputs.items())
