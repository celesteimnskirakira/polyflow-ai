"""
Polyflow CLI — multi-model AI workflow engine.

Key commands:
  polyflow doctor          Check your setup
  polyflow list            Browse available workflows
  polyflow run <workflow>  Run a workflow (by name or file path)
  polyflow new "..."       Generate a workflow from a description
  polyflow validate <file> Validate a workflow YAML
  polyflow schema          Show the YAML schema reference
  polyflow pull <name>     Pull a workflow from the community registry
  polyflow search          List community workflows
  polyflow init            Configure API keys
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from polyflow import __version__
from polyflow.config import Config, save_config, load_config

console = Console()
err_console = Console(stderr=True)

# ─── Workflow resolution ──────────────────────────────────────────────────────

def _resolve_workflow(ref: str) -> Path:
    """
    Resolve a workflow reference to a Path.
    Accepts: file path, name (with or without .yaml),
             name from workflows/examples/, ~/.polyflow/workflows/.
    """
    candidate = Path(ref)

    # 1. Exact path
    if candidate.exists() and candidate.is_file():
        return candidate

    # 2. Add .yaml extension
    with_yaml = Path(ref + ".yaml") if not ref.endswith(".yaml") else candidate
    if with_yaml.exists():
        return with_yaml

    # 3. Search in well-known directories
    search_dirs = [
        Path("workflows/examples"),
        Path("workflows"),
        Path.home() / ".polyflow" / "workflows",
    ]
    # Also try relative to the polyflow package's own examples
    _pkg_examples = Path(__file__).parent.parent.parent.parent / "workflows" / "examples"
    if _pkg_examples.is_dir():
        search_dirs.append(_pkg_examples)

    name = Path(ref).stem  # strip any extension
    known_names: list[str] = []
    for d in search_dirs:
        for suffix in ("", ".yaml"):
            p = d / (name + suffix)
            if p.exists():
                return p
        if d.is_dir():
            known_names.extend(p.stem for p in d.glob("*.yaml"))

    # "Did you mean?" fuzzy suggestion
    import difflib
    close = difflib.get_close_matches(name, known_names, n=3, cutoff=0.5)
    suggestion = ""
    if close:
        suggestion = f"\n  • Did you mean: {', '.join(close)}?"

    raise FileNotFoundError(
        f"Workflow '{ref}' not found.{suggestion}\n"
        f"  • Run [bold]polyflow list[/bold] to see available workflows\n"
        f"  • Run [bold]polyflow pull {ref}[/bold] to download from registry\n"
        f"  • Run [bold]polyflow new \"{ref}\"[/bold] to generate one"
    )


def _list_local_workflows() -> list[tuple[str, str, str]]:
    """Return list of (name, description, path) for local workflows."""
    results = []
    search_dirs = [
        Path("workflows/examples"),
        Path("workflows"),
        Path.home() / ".polyflow" / "workflows",
    ]
    _pkg_examples = Path(__file__).parent.parent.parent.parent / "workflows" / "examples"
    if _pkg_examples.is_dir():
        search_dirs.insert(0, _pkg_examples)

    seen = set()
    for d in search_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            if p.name in seen:
                continue
            seen.add(p.name)
            try:
                import yaml
                raw = yaml.safe_load(p.read_text())
                desc = raw.get("description", "")
                tags = raw.get("tags", [])
                results.append((p.stem, desc, str(p), tags))
            except Exception:
                results.append((p.stem, "", str(p), []))
    return results


# ─── Commands ─────────────────────────────────────────────────────────────────

@click.group(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
@click.version_option(__version__, prog_name="polyflow")
@click.pass_context
def main(ctx):
    """
    Polyflow — define, run and share multi-model AI workflows in YAML.

    \b
    Get started in 30 seconds:
      export OPENROUTER_API_KEY=sk-or-...
      polyflow list
      polyflow run code-review-multi-model -i "$(git diff HEAD~1)"

    \b
    Docs & examples: https://github.com/celesteimnskirakira/polyflow
    """
    if ctx.invoked_subcommand is None:
        _show_welcome()
        console.print(ctx.get_help())


def _show_welcome() -> None:
    """Print a Rich welcome panel when polyflow is run with no arguments."""
    from rich.panel import Panel
    from rich.text import Text

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    config = load_config()

    title = Text(f"Polyflow v{__version__}", style="bold cyan")

    if api_key or config.uses_openrouter:
        status_line = "[bold green]Ready![/bold green]  Try: [bold]polyflow list[/bold]"
    else:
        status_line = (
            "[bold yellow]Setup needed.[/bold yellow]  "
            "Set [bold]OPENROUTER_API_KEY=sk-or-...[/bold] or run [bold]polyflow init[/bold]\n"
            "  Get a free key at [link=https://openrouter.ai]https://openrouter.ai[/link]"
        )

    # Context-aware suggestion: detect git repo
    context_tip = ""
    if Path(".git").is_dir():
        context_tip = (
            "\n[dim]Detected: git repository[/dim]\n"
            "  [bold cyan]→[/bold cyan] [bold]polyflow run code-review-multi-model -i \"$(git diff HEAD~1)\"[/bold]\n"
        )

    quick_ref = (
        "\n[dim]Quick reference:[/dim]\n"
        "  [bold]polyflow list[/bold]                    Browse local workflows\n"
        "  [bold]polyflow run <name> -i \"..\"[/bold]     Run a workflow\n"
        "  [bold]polyflow new[/bold]                     Generate workflow with AI\n"
        "  [bold]polyflow onboard <tool>[/bold]          Generate workflow for any tool\n"
        "  [bold]polyflow run <name> --dry-run[/bold]    Preview prompts without API calls\n"
        "  [bold]polyflow doctor[/bold]                  Check setup\n"
    )

    console.print()
    console.print(
        Panel(
            f"  {status_line}{context_tip}{quick_ref}",
            title=title,
            border_style="cyan",
            padding=(0, 1),
        )
    )
    console.print()


@main.command()
def doctor():
    """Check your environment and API key setup."""
    import httpx

    console.print("\n[bold]Polyflow Doctor[/bold] — system check\n")
    ok = True

    def check(label: str, status: bool, note: str = "", fix: str = ""):
        icon = "[green]✓[/green]" if status else "[red]✗[/red]"
        line = f"  {icon}  {label}"
        if note:
            line += f"  [dim]{note}[/dim]"
        console.print(line)
        if not status and fix:
            console.print(f"       [yellow]→ {fix}[/yellow]")
        return status

    # Python version
    import sys
    py_ok = sys.version_info >= (3, 11)
    check("Python", py_ok, f"{sys.version.split()[0]}", "Upgrade to Python 3.11+")
    ok = ok and py_ok

    # Polyflow version
    check("Polyflow", True, f"v{__version__}")

    # API keys
    console.print()
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    ant_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gem_key = os.environ.get("GEMINI_API_KEY", "")
    oai_key = os.environ.get("OPENAI_API_KEY", "")

    if or_key:
        check("OPENROUTER_API_KEY", True, f"{or_key[:12]}... (covers all models ✨)")
    else:
        check(
            "OPENROUTER_API_KEY", False,
            "not set",
            "export OPENROUTER_API_KEY=sk-or-... (get one at openrouter.ai)"
        )
        ok = False
        # Fall back to individual keys
        check("ANTHROPIC_API_KEY", bool(ant_key), "set" if ant_key else "not set")
        check("GEMINI_API_KEY",    bool(gem_key), "set" if gem_key else "not set")
        check("OPENAI_API_KEY",    bool(oai_key), "set" if oai_key else "not set")
        if not any([ant_key, gem_key, oai_key]):
            ok = False

    # Config file
    console.print()
    cfg_path = Path.home() / ".polyflow" / "config.yaml"
    check("Config file", cfg_path.exists(), str(cfg_path) if cfg_path.exists() else "not found (using env vars)")

    # Network + OpenRouter reachability (quick check)
    console.print()
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=5,
                      headers={"Authorization": f"Bearer {or_key}"} if or_key else {})
        reachable = r.status_code in (200, 401)  # 401 = reachable but key invalid
        check("OpenRouter API", reachable, "reachable" if reachable else f"HTTP {r.status_code}")
    except Exception as e:
        check("OpenRouter API", False, "unreachable", "Check network connection")

    # Local workflows
    console.print()
    workflows = _list_local_workflows()
    check("Local workflows", len(workflows) > 0, f"{len(workflows)} found" if workflows else "none found")

    console.print()
    if ok:
        console.print("[bold green]✓ All good! Ready to run.[/bold green]")
        console.print("\n  Try: [bold]polyflow list[/bold]")
    else:
        console.print("[bold yellow]⚠ Fix the issues above, then re-run polyflow doctor[/bold yellow]")
    console.print()


@main.command("list")
@click.option("--tag", "-t", default=None, help="Filter by tag")
def list_workflows(tag: str | None):
    """List available workflows (local + examples)."""
    workflows = _list_local_workflows()

    if not workflows:
        console.print("[yellow]No workflows found.[/yellow]")
        console.print("  Run [bold]polyflow search[/bold] to browse community workflows")
        console.print("  Run [bold]polyflow pull <name>[/bold] to download one")
        return

    if tag:
        all_tags = sorted({t for _, _, _, tags in workflows for t in tags})
        filtered = [(n, d, p, t) for n, d, p, t in workflows if any(tag in item for item in t)]
        if not filtered:
            import difflib
            suggestions = difflib.get_close_matches(tag, all_tags, n=3, cutoff=0.6)
            msg = f"[yellow]No workflows with tag '{tag}'.[/yellow]"
            if suggestions:
                msg += f"\n  Did you mean: {', '.join(suggestions)}?"
            console.print(msg)
            return
        workflows = filtered

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", padding=(0, 1))
    table.add_column("Name", style="bold white", min_width=28)
    table.add_column("Description", style="dim")
    table.add_column("Tags", style="cyan", min_width=20)

    for name, desc, path, tags in workflows:
        short_desc = (desc[:60] + "…") if len(desc) > 61 else desc
        tags_str = " ".join(f"[dim]{t}[/dim]" for t in tags[:4])
        table.add_row(name, short_desc, tags_str)

    console.print(f"\n  [bold]{len(workflows)} workflows available[/bold]\n")
    console.print(table)
    console.print()
    console.print("  Run: [bold]polyflow run <name> -i \"your input\"[/bold]")
    if tag is None:
        console.print("  Filter: [bold]polyflow list --tag security[/bold]")
    console.print()


@main.command()
@click.argument("workflow_ref")
@click.option("--input", "-i", "user_input", default="", help="Input to pass to the workflow")
@click.option("--output", "-o", default=None, help="Save final output to a file")
@click.option("--show-output/--no-show-output", default=True, help="Preview step outputs")
@click.option("--dry-run", is_flag=True, default=False,
              help="Preview rendered prompts without calling any APIs")
def run(workflow_ref: str, user_input: str, output: str | None, show_output: bool, dry_run: bool):
    """
    Run a workflow by name or file path.

    \b
    Examples:
      polyflow run code-review-multi-model -i "$(git diff HEAD~1)"
      polyflow run ./my-flow.yaml -i "build a todo API"
      polyflow run bug-triage -i "TypeError in auth.py line 42"
      polyflow run code-review-multi-model --dry-run -i "test"
    """
    from polyflow.engine.runner import run_workflow

    try:
        workflow_path = _resolve_workflow(workflow_ref)
    except FileNotFoundError as e:
        err_console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    if not user_input:
        user_input = click.prompt("  Workflow input")

    config = load_config()
    if not dry_run and not config.uses_openrouter and not config.api_keys:
        err_console.print(
            "[yellow]⚠ No API keys found.[/yellow] "
            "Set [bold]OPENROUTER_API_KEY[/bold] or run [bold]polyflow init[/bold]."
        )
        sys.exit(1)

    ctx = asyncio.run(run_workflow(
        workflow_path, user_input, config,
        show_output=show_output, dry_run=dry_run,
    ))

    if output and ctx.step_outputs:
        last_output = list(ctx.step_outputs.values())[-1]
        Path(output).write_text(last_output, encoding="utf-8")
        console.print(f"[dim]Output written to {output}[/dim]")


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True, path_type=Path))
def validate(workflow_file: Path):
    """
    Validate a workflow YAML against the schema.

    \b
    Examples:
      polyflow validate my-flow.yaml
      polyflow validate workflows/examples/code-review-multi-model.yaml
    """
    import yaml
    from pydantic import ValidationError
    from polyflow.schema.workflow import Workflow

    try:
        raw = yaml.safe_load(workflow_file.read_text())
        wf = Workflow.model_validate(raw)
        console.print(f"\n  [green]✓[/green] [bold]{wf.name}[/bold] — valid ({len(wf.steps)} steps)\n")
        for step in wf.steps:
            if step.type == "parallel":
                stype = f"[dim]parallel[/dim] × {len(step.steps)}"
            else:
                stype = f"[dim]{step.model}[/dim]"
            hitl = " [yellow]+hitl[/yellow]" if step.hitl else ""
            cond = " [blue]+if[/blue]" if step.condition else ""
            console.print(f"    [dim]{step.id:28}[/dim] {stype}{hitl}{cond}")
        console.print()
    except ValidationError as e:
        err_console.print(f"\n  [red]✗ Validation failed:[/red] {workflow_file.name}\n")
        for error in e.errors():
            loc = " → ".join(str(x) for x in error["loc"])
            err_console.print(f"  [red]  {loc}[/red]")
            err_console.print(f"      {error['msg']}\n")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"\n  [red]✗ Error:[/red] {e}\n")
        sys.exit(1)


@main.command()
def schema():
    """Show the Polyflow YAML schema reference."""
    from rich.markdown import Markdown

    md = Markdown(_SCHEMA_REFERENCE)
    console.print()
    console.print(md)
    console.print()


@main.command()
@click.argument("description", default="", required=False)
@click.option("--output", "-o", default=None, help="Save path (skips interactive menu)")
def new(description: str, output: str | None):
    """
    Generate a workflow from a natural language description (interactive).

    \b
    With no arguments, enters guided conversation mode.
    Pass a description to generate immediately.

    \b
    Examples:
      polyflow new
      polyflow new "Claude drafts, Gemini reviews security, I approve"
      polyflow new "OWASP security audit" -o sec-audit.yaml
    """
    config = load_config()
    if not config.uses_openrouter and not config.api_keys:
        err_console.print(
            "[yellow]⚠ No API keys found.[/yellow] "
            "Set [bold]OPENROUTER_API_KEY[/bold] or run [bold]polyflow init[/bold]."
        )
        sys.exit(1)

    _interactive_new(description or "", output, config)


def _generate_yaml(description: str, history: list[dict], config) -> str:
    """Call the LLM to generate workflow YAML. history is the conversation so far."""
    messages = [{"role": "user", "content": f"Generate a Polyflow workflow for:\n{description}"}]
    messages.extend(history)

    if config.uses_openrouter:
        from openai import OpenAI
        from polyflow.models.openrouter import OPENROUTER_BASE_URL
        client = OpenAI(api_key=config.openrouter_api_key, base_url=OPENROUTER_BASE_URL)
        raw = client.chat.completions.create(
            model="anthropic/claude-sonnet-4-5",
            max_tokens=2048,
            messages=[{"role": "system", "content": _NEW_SYSTEM_PROMPT}] + messages,
        ).choices[0].message.content
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=config.get_api_key("claude"))
        raw = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_NEW_SYSTEM_PROMPT,
            messages=messages,
        ).content[0].text

    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(ln for ln in lines if not ln.startswith("```")).strip()
    return raw


def _show_yaml(yaml_content: str, wf_name: str, step_ids: list[str]) -> None:
    from rich.syntax import Syntax
    console.print()
    console.print(Syntax(yaml_content, "yaml", theme="monokai", line_numbers=False, padding=(0, 1)))
    console.print(
        f"\n  [bold green]{wf_name}[/bold green]  "
        f"[dim]{len(step_ids)} steps: {', '.join(step_ids)}[/dim]"
    )


def _interactive_new(
    initial_description: str,
    save_path: str | None,
    config,
    _override_generate_fn=None,
) -> None:
    import yaml as _yaml
    from pydantic import ValidationError
    from polyflow.schema.workflow import Workflow

    console.print("\n  [bold]Polyflow — workflow generator[/bold]")
    console.print("  [dim]Describe what you want. Natural language is fine.[/dim]\n")

    # Get description if not provided
    if initial_description:
        description = initial_description
        console.print(f"  [dim]> {description}[/dim]\n")
    else:
        description = click.prompt("  What should this workflow do").strip()
        if not description:
            return

    history: list[dict] = []   # conversation for multi-turn refinement
    yaml_content: str = ""
    wf: Workflow | None = None

    # Use override generate function if provided (e.g. from onboard command)
    generate_fn = _override_generate_fn if _override_generate_fn else _generate_yaml

    while True:
        # ── Generate ──────────────────────────────────────────────────────────
        with console.status("[cyan]Generating...[/cyan]"):
            yaml_content = generate_fn(description, history, config)

        try:
            raw = _yaml.safe_load(yaml_content)
            wf = Workflow.model_validate(raw)
            step_ids = [s.id for s in wf.steps]
            _show_yaml(yaml_content, wf.name, step_ids)
            valid = True
        except (ValidationError, Exception) as e:
            console.print(f"\n  [yellow]⚠ Generated YAML has issues:[/yellow] {e}")
            console.print(Syntax(yaml_content, "yaml", theme="monokai", padding=(0, 1)) if yaml_content else "")
            valid = False

        # ── Menu ──────────────────────────────────────────────────────────────
        console.print()
        if valid:
            console.print("  [bold]What next?[/bold]")
            console.print("  [bold cyan][r][/bold cyan] Run it now")
            console.print("  [bold cyan][s][/bold cyan] Save to file")
            console.print("  [bold cyan][p][/bold cyan] Push to community (share)")
            console.print("  [bold cyan][e][/bold cyan] Refine (describe changes)")
            console.print("  [bold cyan][q][/bold cyan] Quit")
        else:
            console.print("  [bold cyan][e][/bold cyan] Try again / describe changes")
            console.print("  [bold cyan][w][/bold cyan] Save raw output anyway")
            console.print("  [bold cyan][q][/bold cyan] Quit")

        choice = click.prompt("\n  Choice", default="r" if valid else "e").strip().lower()

        # ── Run ───────────────────────────────────────────────────────────────
        if choice == "r" and valid and wf:
            user_input = click.prompt("  Workflow input").strip()
            out_path = Path(save_path or f"{wf.name}.yaml")
            out_path.write_text(yaml_content, encoding="utf-8")
            console.print(f"\n  [dim]Saved to {out_path}[/dim]\n")
            from polyflow.engine.runner import run_workflow
            asyncio.run(run_workflow(out_path, user_input, config, show_output=True))
            return

        # ── Save ──────────────────────────────────────────────────────────────
        elif choice in ("s", "w"):
            default_name = (wf.name if wf else "workflow") + ".yaml"
            out_path = Path(save_path or click.prompt("  Save as", default=default_name))
            out_path.write_text(yaml_content, encoding="utf-8")
            console.print(f"\n  [green]✓[/green] Saved to [bold]{out_path}[/bold]")
            if valid and wf:
                console.print(f"  Run:      [bold]polyflow run {out_path} -i \"your input\"[/bold]")
                console.print(f"  Validate: [bold]polyflow validate {out_path}[/bold]")
            console.print()
            return

        # ── Push to community ─────────────────────────────────────────────────
        elif choice == "p" and valid and wf:
            default_name = wf.name + ".yaml"
            out_path = Path(save_path or click.prompt("  Save as before sharing", default=default_name))
            out_path.write_text(yaml_content, encoding="utf-8")
            console.print(f"\n  [dim]Saved to {out_path}[/dim]")
            from click.testing import CliRunner as _CliRunner
            # Invoke share command inline
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                console.print(
                    "\n  [yellow]⚠ GITHUB_TOKEN not set.[/yellow] "
                    "Create one at: https://github.com/settings/tokens/new\n"
                    "  Then: [bold]export GITHUB_TOKEN=ghp_...[/bold]\n"
                    "  Or run: [bold]polyflow share " + str(out_path) + "[/bold]\n"
                )
            else:
                asyncio.run(_do_share(out_path, wf, token, None))
            return

        # ── Refine ────────────────────────────────────────────────────────────
        elif choice == "e":
            refinement = click.prompt("  Describe what to change").strip()
            # Keep conversation history so the LLM knows what was already generated
            history = [
                {"role": "assistant", "content": yaml_content},
                {"role": "user", "content": refinement},
            ]
            description = description  # keep original intent

        # ── Quit ──────────────────────────────────────────────────────────────
        elif choice == "q":
            console.print()
            return


@main.command()
@click.argument("tool_or_url")
@click.option("--output", "-o", default=None, help="Save path (skips interactive menu)")
def onboard(tool_or_url: str, output: str | None):
    """
    Generate a workflow by onboarding any tool or docs URL.

    \b
    Accepts a tool name (e.g. "cursor", "supabase") or a direct docs URL.
    Fetches the documentation and generates a personalized Polyflow workflow.

    \b
    Examples:
      polyflow onboard cursor
      polyflow onboard supabase
      polyflow onboard https://docs.example.com/api
    """
    config = load_config()
    if not config.uses_openrouter and not config.api_keys:
        err_console.print(
            "[yellow]⚠ No API keys found.[/yellow] "
            "Set [bold]OPENROUTER_API_KEY[/bold] or run [bold]polyflow init[/bold]."
        )
        sys.exit(1)

    _interactive_onboard(tool_or_url, output, config)


def _fetch_url_content(url: str) -> str:
    """Fetch a URL and strip HTML tags to get plain text."""
    import httpx
    import re

    with console.status(f"[cyan]Fetching {url}...[/cyan]"):
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True,
                             headers={"User-Agent": "polyflow-onboard/1.0"})
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {url}: {e}")

    # Strip HTML tags and collapse whitespace
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:6000]  # limit to avoid huge prompts


def _search_tool_docs(tool_name: str) -> tuple[str, str]:
    """
    Search for a tool's documentation using DuckDuckGo instant answers API.
    Returns (abstract_text, abstract_url).
    """
    import httpx

    with console.status(f"[cyan]Searching docs for '{tool_name}'...[/cyan]"):
        try:
            resp = httpx.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": f"{tool_name} documentation",
                    "format": "json",
                    "no_html": "1",
                    "no_redirect": "1",
                },
                timeout=10,
                headers={"User-Agent": "polyflow-onboard/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return (f"Tool: {tool_name}", "")

    abstract = data.get("AbstractText", "") or ""
    abstract_url = data.get("AbstractURL", "") or ""

    # If we got a URL, fetch more content from it
    if abstract_url:
        try:
            page_text = _fetch_url_content(abstract_url)
            combined = f"{abstract}\n\n{page_text}" if abstract else page_text
            return combined[:6000], abstract_url
        except Exception:
            pass

    # Fall back to related topics
    if not abstract:
        topics = data.get("RelatedTopics", [])
        snippets = []
        for t in topics[:5]:
            if isinstance(t, dict) and t.get("Text"):
                snippets.append(t["Text"])
        abstract = "\n".join(snippets) or f"Tool documentation for: {tool_name}"

    return abstract[:6000], abstract_url


def _generate_onboard_yaml(tool_name: str, docs_content: str, docs_url: str, config) -> str:
    """Generate a Polyflow workflow tailored to a tool, given its docs."""
    source_hint = f"(from {docs_url})" if docs_url else ""
    prompt = (
        f"Generate a Polyflow workflow to help a developer use the tool: {tool_name} {source_hint}.\n\n"
        f"Here is documentation / context about the tool:\n"
        f"---\n{docs_content[:4000]}\n---\n\n"
        f"Create a practical workflow that adapts {tool_name} to a typical developer project. "
        f"Make it immediately useful, with clear step names and prompts."
    )

    if config.uses_openrouter:
        from openai import OpenAI
        from polyflow.models.openrouter import OPENROUTER_BASE_URL
        client = OpenAI(api_key=config.openrouter_api_key, base_url=OPENROUTER_BASE_URL)
        raw = client.chat.completions.create(
            model="anthropic/claude-sonnet-4-5",
            max_tokens=2048,
            messages=[
                {"role": "system", "content": _NEW_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        ).choices[0].message.content
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=config.get_api_key("claude"))
        raw = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=_NEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ).content[0].text

    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(ln for ln in lines if not ln.startswith("```")).strip()
    return raw


def _interactive_onboard(tool_or_url: str, save_path: str | None, config) -> None:
    import yaml as _yaml
    from pydantic import ValidationError
    from polyflow.schema.workflow import Workflow

    console.print(f"\n  [bold]Polyflow Onboard — {tool_or_url}[/bold]")
    console.print("  [dim]Fetching docs and generating workflow...[/dim]\n")

    # Detect URL vs tool name
    if tool_or_url.startswith("http://") or tool_or_url.startswith("https://"):
        docs_url = tool_or_url
        try:
            docs_content = _fetch_url_content(docs_url)
        except RuntimeError as e:
            err_console.print(f"[red]✗ {e}[/red]")
            sys.exit(1)
        tool_name = docs_url.split("/")[2].replace("www.", "").replace("docs.", "")
    else:
        tool_name = tool_or_url
        docs_content, docs_url = _search_tool_docs(tool_name)

    if not docs_content:
        console.print(f"  [yellow]⚠ No documentation found for '{tool_name}'.[/yellow]")
        console.print("  Try passing the docs URL directly, e.g.:")
        console.print(f"  [bold]polyflow onboard https://docs.{tool_name}.com[/bold]\n")
        sys.exit(1)

    console.print(f"  [green]✓[/green] Got docs ({len(docs_content)} chars)" +
                  (f" from [dim]{docs_url}[/dim]" if docs_url else ""))
    console.print()

    # Generate the workflow (reuse _interactive_new logic from here).
    # Override only for the first generation (no history); refinements fall back to normal LLM.
    def _onboard_generate(desc: str, hist: list, cfg) -> str:
        if not hist:  # first generation: use tool docs
            return _generate_onboard_yaml(tool_name, docs_content, docs_url, cfg)
        return _generate_yaml(desc, hist, cfg)  # refinement pass: use standard generator

    _interactive_new(
        initial_description=f"Tool onboarding workflow for {tool_name}",
        save_path=save_path,
        config=config,
        _override_generate_fn=_onboard_generate,
    )


@main.command()
def init():
    """
    Configure API keys for Polyflow.

    \b
    Tip: Set OPENROUTER_API_KEY in your shell to skip this step.
    OpenRouter covers Claude, Gemini, and GPT-4 with a single key.
    Get a key at: https://openrouter.ai
    """
    console.print("\n  [bold]Polyflow Setup[/bold] — configure API keys\n")

    if os.environ.get("OPENROUTER_API_KEY"):
        console.print("  [green]✓[/green] OPENROUTER_API_KEY already set in environment\n")
        console.print("  You're ready to run! Try: [bold]polyflow list[/bold]\n")
        return

    console.print("  [bold]Option 1 (recommended):[/bold] OpenRouter — one key, all models")
    console.print("  Get a free key at [link=https://openrouter.ai]https://openrouter.ai[/link]\n")
    or_key = Prompt.ask("  OpenRouter API key (Enter to skip)", default="")
    if or_key:
        cfg = Config(openrouter_api_key=or_key)
        save_config(cfg)
        console.print("\n  [green]✓[/green] Saved to ~/.polyflow/config.yaml")
        console.print("  Run: [bold]polyflow doctor[/bold] to verify setup\n")
        return

    console.print("\n  [bold]Option 2:[/bold] Individual model keys\n")
    keys = {}
    for model, label, hint in [
        ("claude", "Anthropic (Claude)", "sk-ant-..."),
        ("gemini", "Google (Gemini)", "AIza..."),
        ("gpt-4", "OpenAI (GPT-4)", "sk-..."),
    ]:
        key = Prompt.ask(f"  {label} [{hint}] (Enter to skip)", default="")
        if key:
            keys[model] = key

    cfg = Config(api_keys=keys)
    save_config(cfg)
    console.print("\n  [green]✓[/green] Saved to ~/.polyflow/config.yaml\n")


@main.command()
@click.argument("name")
@click.option("--output", "-o", default=None, help="Save path (default: <name>.yaml)")
def pull(name: str, output: str):
    """
    Pull a workflow from the community registry.

    \b
    Examples:
      polyflow pull code-review-multi-model
      polyflow pull security-audit -o my-audit.yaml
    """
    from polyflow.registry.client import pull_workflow
    dest = Path(output or f"{name}.yaml")
    try:
        with console.status(f"[cyan]Pulling {name}...[/cyan]"):
            asyncio.run(pull_workflow(name, dest))
        console.print(f"\n  [green]✓[/green] Saved to [bold]{dest}[/bold]")
        console.print(f"  Validate: [bold]polyflow validate {dest}[/bold]")
        console.print(f"  Run:      [bold]polyflow run {name} -i \"your input\"[/bold]\n")
    except FileNotFoundError as e:
        console.print(f"\n  [red]✗[/red] {e}\n")
        sys.exit(1)


@main.command()
def search():
    """List available workflows in the community registry."""
    from polyflow.registry.client import list_workflows
    try:
        with console.status("[cyan]Fetching registry...[/cyan]"):
            workflows = asyncio.run(list_workflows())
        console.print(f"\n  [bold]{len(workflows)} community workflows:[/bold]\n")
        for name in workflows:
            console.print(f"  • {name}")
        console.print(f"\n  Install: [bold]polyflow pull <name>[/bold]\n")
    except Exception as e:
        console.print(f"\n  [red]Registry unavailable:[/red] {e}")
        console.print("  → https://github.com/celesteimnskirakira/polyflow\n")


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True, path_type=Path))
@click.option("--token", "-t", envvar="GITHUB_TOKEN", default=None,
              help="GitHub personal access token (or set GITHUB_TOKEN env var)")
@click.option("--message", "-m", default=None, help="Description for the PR")
def share(workflow_file: Path, token: str | None, message: str | None):
    """
    Share a workflow to the community registry via GitHub PR.

    \b
    Requires a GitHub personal access token with public_repo scope.
    Set GITHUB_TOKEN env var or pass with --token.

    \b
    Examples:
      polyflow share my-workflow.yaml
      polyflow share my-workflow.yaml -m "Useful for code reviews"
      polyflow share my-workflow.yaml --token ghp_...
    """
    import yaml
    from pydantic import ValidationError
    from polyflow.schema.workflow import Workflow

    # Validate first
    try:
        raw = yaml.safe_load(workflow_file.read_text())
        wf = Workflow.model_validate(raw)
    except (ValidationError, Exception) as e:
        err_console.print(f"\n  [red]✗ Validation failed:[/red] {e}\n")
        sys.exit(1)

    if not token:
        err_console.print("\n  [red]✗ GitHub token required.[/red]")
        err_console.print("  Create one at: https://github.com/settings/tokens/new")
        err_console.print("  Needs [bold]public_repo[/bold] scope only (not full repo)")
        err_console.print("  Then: [bold]export GITHUB_TOKEN=ghp_...[/bold]\n")
        sys.exit(1)

    console.print(f"\n  Sharing [bold]{wf.name}[/bold] to community registry...")
    asyncio.run(_do_share(workflow_file, wf, token, message))


async def _do_share(
    workflow_file: Path,
    wf,
    token: str,
    pr_message: str | None,
) -> None:
    import base64
    import httpx

    _OWNER = "celesteimnskirakira"
    _REPO  = "polyflow-community"
    _BASE  = "main"
    _PATH  = f"workflows/{workflow_file.name}"
    _API   = "https://api.github.com"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30) as gh:

        # ── 1. Get authenticated user ──────────────────────────────────────
        with console.status("[cyan]Authenticating...[/cyan]"):
            r = await gh.get(f"{_API}/user")
            if r.status_code == 401:
                err_console.print("\n  [red]✗ Invalid GitHub token.[/red]\n")
                sys.exit(1)
            r.raise_for_status()
            gh_user = r.json()["login"]
        console.print(f"  [green]✓[/green] Authenticated as [bold]{gh_user}[/bold]")

        # ── 2. Fork the repo (idempotent) ──────────────────────────────────
        with console.status("[cyan]Forking repository...[/cyan]"):
            await gh.post(f"{_API}/repos/{_OWNER}/{_REPO}/forks")
            # GitHub returns 202 whether fork is new or already exists.
            # Wait briefly for fork to become available.
            import asyncio as _aio
            await _aio.sleep(3)
        console.print(f"  [green]✓[/green] Fork ready: [dim]{gh_user}/{_REPO}[/dim]")

        # ── 3. Get base branch SHA ─────────────────────────────────────────
        with console.status("[cyan]Reading base branch...[/cyan]"):
            r = await gh.get(f"{_API}/repos/{_OWNER}/{_REPO}/git/ref/heads/{_BASE}")
            r.raise_for_status()
            base_sha = r.json()["object"]["sha"]

        # ── 4. Create branch on fork (idempotent) ─────────────────────────
        branch = f"share-{workflow_file.stem}"
        with console.status(f"[cyan]Creating branch {branch}...[/cyan]"):
            r = await gh.post(
                f"{_API}/repos/{gh_user}/{_REPO}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if r.status_code not in (201, 422):   # 422 = branch already exists
                r.raise_for_status()
        console.print(f"  [green]✓[/green] Branch: [dim]{branch}[/dim]")

        # ── 5. Upload workflow file ────────────────────────────────────────
        content_b64 = base64.b64encode(workflow_file.read_bytes()).decode()

        # Check if file already exists on the fork branch (need its SHA to update)
        existing_sha = None
        chk = await gh.get(
            f"{_API}/repos/{gh_user}/{_REPO}/contents/{_PATH}",
            params={"ref": branch},
        )
        if chk.status_code == 200:
            existing_sha = chk.json()["sha"]

        put_body: dict = {
            "message": f"Add workflow: {wf.name}",
            "content": content_b64,
            "branch": branch,
        }
        if existing_sha:
            put_body["sha"] = existing_sha

        with console.status("[cyan]Uploading workflow file...[/cyan]"):
            r = await gh.put(
                f"{_API}/repos/{gh_user}/{_REPO}/contents/{_PATH}",
                json=put_body,
            )
            r.raise_for_status()
        console.print(f"  [green]✓[/green] File uploaded: [dim]{_PATH}[/dim]")

        # ── 6. Open PR ────────────────────────────────────────────────────
        description = wf.description or ""
        tags = getattr(wf, "tags", [])
        body = pr_message or (
            f"## {wf.name}\n\n"
            f"{description}\n\n"
            + (f"**Tags:** {', '.join(f'`{t}`' for t in tags)}\n\n" if tags else "")
            + f"Shared via `polyflow share`."
        )

        with console.status("[cyan]Opening pull request...[/cyan]"):
            r = await gh.post(
                f"{_API}/repos/{_OWNER}/{_REPO}/pulls",
                json={
                    "title": f"Add workflow: {wf.name}",
                    "body": body,
                    "head": f"{gh_user}:{branch}",
                    "base": _BASE,
                },
            )
            if r.status_code == 422:
                # PR already exists — find its URL
                search_r = await gh.get(
                    f"{_API}/repos/{_OWNER}/{_REPO}/pulls",
                    params={"head": f"{gh_user}:{branch}", "state": "open"},
                )
                existing_prs = search_r.json()
                if existing_prs:
                    pr_url = existing_prs[0]["html_url"]
                    console.print(f"  [yellow]→[/yellow] PR already open: [bold]{pr_url}[/bold]")
                else:
                    console.print("  [yellow]→[/yellow] PR may already exist — check GitHub.")
                return
            r.raise_for_status()
            pr_url = r.json()["html_url"]

    console.print(f"\n  [bold green]✓ PR opened![/bold green]  {pr_url}")
    console.print("  The community will review and merge your workflow.\n")


@main.command()
@click.option("--shell", type=click.Choice(["bash", "zsh", "fish"]), default=None)
def completion(shell: str | None):
    """
    Print shell completion setup instructions.

    \b
    Examples:
      polyflow completion --shell zsh
      polyflow completion --shell bash
    """
    detected = os.environ.get("SHELL", "").split("/")[-1]
    s = shell or detected or "bash"

    instructions = {
        "bash": (
            'eval "$(_POLYFLOW_COMPLETE=bash_source polyflow)"\n\n'
            "Add to ~/.bashrc:\n"
            '  eval "$(_POLYFLOW_COMPLETE=bash_source polyflow)"'
        ),
        "zsh": (
            'eval "$(_POLYFLOW_COMPLETE=zsh_source polyflow)"\n\n'
            "Add to ~/.zshrc:\n"
            '  eval "$(_POLYFLOW_COMPLETE=zsh_source polyflow)"'
        ),
        "fish": (
            "_POLYFLOW_COMPLETE=fish_source polyflow | source\n\n"
            "Add to ~/.config/fish/completions/polyflow.fish:\n"
            "  _POLYFLOW_COMPLETE=fish_source polyflow | source"
        ),
    }
    console.print(f"\n  [bold]Shell completion ({s}):[/bold]\n")
    console.print(f"  {instructions.get(s, instructions['bash'])}\n")


# ─── Schema reference (inline, accessible via `polyflow schema`) ──────────────

_SCHEMA_REFERENCE = """\
# Polyflow YAML Schema Reference

## Minimal workflow

```yaml
name: my-workflow          # required
version: "1.0"             # optional, default "1.0"
description: "..."         # optional, shown at runtime

steps:
  - id: step1              # unique identifier (used in {{steps.step1.output}})
    name: My Step          # display name shown in terminal
    model: claude          # claude | gemini | gpt-4
    prompt: "..."          # prompt template (supports {{...}} expressions)
```

## Template expressions

| Expression | Description |
|---|---|
| `{{input}}` | User's input passed with `-i` flag |
| `{{steps.step_id.output}}` | Output from a previous step |
| `{{hitl.step_id.choice}}` | User's HITL choice (continue/abort/revise) |
| `{{hitl.step_id.note}}` | Revision notes from HITL |
| `{{vars.key}}` | Workflow variable |
| `{{context}}` | Injected file context |
| `{{a \\| b}}` | Pipe fallback — use `b` if `a` is empty |

## Parallel steps

```yaml
- id: validate
  name: Cross-Validate
  type: parallel
  steps:
    - id: gemini_check
      model: gemini
      prompt: "Review: {{steps.generate.output}}"
    - id: gpt4_check
      model: gpt-4
      prompt: "Review: {{steps.generate.output}}"
  aggregate:
    mode: diff          # diff | vote | summary | raw
    model: claude       # optional: model to synthesize results
```

## Human-in-the-loop (HITL)

```yaml
hitl:
  message: "Review the output. Continue?"
  options: [continue, abort, revise]   # any words you want
  show: diff                           # diff | summary | raw | (omit to hide)
  timeout: 10m
```

Use the choice in downstream steps:
```yaml
condition: "{{hitl.review.choice}} != 'abort'"
```

## Conditional execution

```yaml
condition: "{{hitl.review.choice}} == 'revise'"
```

Evaluates `LHS == RHS` or `LHS != RHS` (no code execution, safe).

## Error handling

```yaml
on_error:
  retry: 2                  # retry attempts (default 0)
  fallback: continue        # abort | continue | skip
  partial: continue         # parallel: continue if one sub-step fails
```

## Output

```yaml
output:
  format: markdown          # markdown | json | text
  save_to: output/result.md
  include: [step1, step3]   # specific steps to include (default: all)
```

## Context injection

```yaml
context:
  inject_cwd: true          # inject project file tree
  inject_files:             # inject specific files
    - "src/**/*.py"
    - "README.md"
  max_file_size: 50kb
```

## Variables

```yaml
vars:
  language: Python
  style: concise

steps:
  - prompt: "Write in {{vars.language}}. Style: {{vars.style}}."
```

## Step timeout

```yaml
- id: slow_step
  timeout: 2m               # 30s | 2m | 120 (seconds)
```

## Available models

| Alias | Model |
|---|---|
| `claude` | Claude Sonnet (via Anthropic or OpenRouter) |
| `gemini` | Gemini 2.0 Flash (via Google or OpenRouter) |
| `gpt-4` | GPT-4o (via OpenAI or OpenRouter) |
"""

_NEW_SYSTEM_PROMPT = """\
You are a Polyflow workflow generator. Convert natural language descriptions \
into valid Polyflow YAML workflows.

Rules:
- Output ONLY raw YAML. No markdown fences, no explanation.
- Use models: claude, gemini, gpt-4
- Include HITL checkpoints at key decision points
- Use {{input}} for the user's input
- Use {{steps.step_id.output}} to reference previous step outputs
- Make prompts detailed and specific

Schema quick reference:
  name: str (required)
  version: "1.0"
  steps:
    - id: str
      name: str
      model: claude|gemini|gpt-4
      prompt: str (supports {{...}} templates)
      type: sequential|parallel
      hitl: {message: str, options: list, show: diff|summary|raw}
      condition: "{{hitl.x.choice}} == 'value'"
      on_error: {retry: int, fallback: abort|continue}
"""
