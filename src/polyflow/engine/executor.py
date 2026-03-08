from __future__ import annotations
import asyncio
from typing import Optional
from polyflow.schema.workflow import Step
from polyflow.engine.template import TemplateContext, render
from polyflow.models import get_model_adapter
from polyflow.config import Config


def _evaluate_condition(condition: str, ctx: TemplateContext) -> bool:
    """Evaluate a simple equality condition like "{{expr}} == 'value'"."""
    rendered = render(condition, ctx)
    try:
        return bool(eval(rendered, {"__builtins__": {}}))
    except Exception:
        return False


async def execute_step(step: Step, ctx: TemplateContext, config: Config) -> Optional[str]:
    """Execute a single sequential step. Returns None if skipped."""
    if step.condition and not _evaluate_condition(step.condition, ctx):
        return None

    if step.type == "parallel":
        return await execute_parallel(step, ctx, config)

    adapter = get_model_adapter(step.model)
    api_key = config.get_api_key(step.model)
    prompt = render(step.prompt, ctx)

    for attempt in range(step.on_error.retry + 1):
        try:
            return await adapter.complete(prompt, api_key=api_key)
        except Exception as e:
            if attempt == step.on_error.retry:
                if step.on_error.fallback == "abort":
                    raise
                return None
    return None


async def execute_parallel(step: Step, ctx: TemplateContext, config: Config) -> str:
    """Execute sub-steps in parallel, then aggregate results."""
    async def run_substep(sub):
        adapter = get_model_adapter(sub.model)
        api_key = config.get_api_key(sub.model)
        prompt = render(sub.prompt, ctx)
        try:
            return sub.id, await adapter.complete(prompt, api_key=api_key)
        except Exception:
            if step.on_error.partial == "continue":
                return sub.id, None
            raise

    results = await asyncio.gather(*[run_substep(s) for s in step.steps])
    outputs = {sid: out for sid, out in results if out is not None}

    return _aggregate(outputs, step, ctx, config)


def _aggregate(outputs: dict[str, str], step: Step, ctx: TemplateContext, config: Config) -> str:
    mode = step.aggregate.mode if step.aggregate else "raw"

    if mode == "raw":
        return "\n\n---\n\n".join(
            f"[{sid}]\n{out}" for sid, out in outputs.items()
        )
    if mode == "diff":
        lines = [f"## Review from {sid}:\n{out}" for sid, out in outputs.items()]
        return "\n\n".join(lines)
    if mode == "vote":
        votes = [1 if "approve" in out.lower() else 0 for out in outputs.values()]
        verdict = "approved" if sum(votes) > len(votes) / 2 else "rejected"
        raw_result = "\n\n---\n\n".join(f"[{sid}]\n{out}" for sid, out in outputs.items())
        return f"Vote result: {verdict}\n\n" + raw_result
    # summary: return raw for now
    return "\n\n---\n\n".join(f"[{sid}]\n{out}" for sid, out in outputs.items())
