import re
from dataclasses import dataclass, field
from jinja2 import Environment, Undefined


@dataclass
class TemplateContext:
    input: str = ""
    step_outputs: dict[str, str] = field(default_factory=dict)
    hitl_choices: dict[str, dict] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)
    context_str: str = ""


def _resolve_dotpath(path: str, ctx: TemplateContext) -> str:
    """Resolve a dot-path like 'steps.generate.output' against context."""
    parts = path.strip().split(".")
    if parts[0] == "steps" and len(parts) == 3 and parts[2] == "output":
        return ctx.step_outputs.get(parts[1], "")
    if parts[0] == "hitl" and len(parts) >= 2:
        step_hitl = ctx.hitl_choices.get(parts[1], {})
        if len(parts) == 3:
            return step_hitl.get(parts[2], "")
        return str(step_hitl)
    if parts[0] == "vars" and len(parts) == 2:
        return ctx.vars.get(parts[1], "")
    if parts[0] == "context":
        return ctx.context_str
    if parts[0] == "input":
        return ctx.input
    return ""


def render(template_str: str, ctx: TemplateContext) -> str:
    """
    Render a template string with {{...}} and {{a | b}} fallback syntax.
    Uses custom regex instead of Jinja2 to support the pipe-fallback pattern.
    """
    def replacer(match: re.Match) -> str:
        expr = match.group(1).strip()
        # Handle pipe fallback: {{a | b}}
        if "|" in expr:
            parts = [p.strip() for p in expr.split("|")]
            for part in parts:
                value = _resolve_dotpath(part, ctx)
                if value:
                    return value
            return ""
        return _resolve_dotpath(expr, ctx)

    return re.sub(r"\{\{(.+?)\}\}", replacer, template_str)
