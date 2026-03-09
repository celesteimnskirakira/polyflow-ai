# Polyflow — Project Direction for AI Agents

## What This Is

Polyflow is a CLI tool and GitHub Action that runs Claude, Gemini, and GPT-4 **in parallel on the same task**, defined in a single YAML file.

The core problem it solves: developers manually copy prompts to multiple AI services to cross-check results — Addy Osmani (Google Chrome engineering director) named this behavior **"Model Musical Chairs."** Polyflow automates it.

```bash
pip install polyflow-ai
polyflow run code-review-multi-model -i "$(git diff HEAD~1)"
```

---

## The Unique Combination (Our Moat)

No other tool has all five of these simultaneously:

| Feature | Why it matters |
|---|---|
| **Parallel multi-model execution** | Claude + Gemini + GPT-4 on the same prompt at the same time — not sequential, not a single model |
| **YAML-declarative workflows** | Version-controllable, shareable, readable by non-Python developers |
| **Human-in-the-Loop (HITL) checkpoints** | Pause execution for human approval at any step — first-class primitive |
| **GitHub Action (`action.yml`)** | One line of YAML in any repo to get AI-powered CI/CD |
| **`pip install` CLI** | No server, no signup, no GUI — works in terminals and scripts |

The closest competitors: OpenClaw (single model, no CI/CD), LangChain (Python boilerplate, no parallel multi-model), CodeRabbit/BugBot/Graphite (single model, SaaS pricing, no YAML).

---

## Target User

**Primary:** A developer who uses AI for code review, security audits, or workflow automation and is frustrated that:
1. Every AI tool only uses one model
2. Getting multi-model results requires copy-pasting the same prompt manually
3. CI/CD AI integration requires writing glue code

**Secondary:** Teams that want AI-powered PR review without paying $20-40/user/month for single-model SaaS tools.

---

## Architecture

```
src/polyflow/
  cli.py              Entry point — all Click commands (run, list, validate, new, doctor...)
  config.py           API key loading (OPENROUTER_API_KEY, ANTHROPIC_API_KEY, etc.)
  schema/
    workflow.py       Pydantic v2 models for the YAML schema (Workflow, Step, HitlConfig...)
  engine/
    runner.py         Top-level workflow executor — loads YAML, loops steps, handles output
    executor.py       Step execution — sequential, parallel (asyncio.gather), retry/backoff
    template.py       Jinja2-style template rendering ({{input}}, {{steps.x.output}}, pipes)
    hitl.py           Human-in-the-Loop terminal prompts
    context_builder.py  File injection (inject_cwd, inject_files globs)
  models/
    openrouter.py     OpenRouter adapter (recommended — covers all models with one key)
    claude.py         Anthropic SDK direct adapter
    gemini.py         google-genai SDK adapter
    openai_model.py   OpenAI SDK adapter
    base.py           Abstract base class
  registry/
    client.py         Community workflow registry (pull, search commands)

workflows/examples/   22 built-in workflows shipped with the package
action.yml            GitHub Action composite action
```

---

## Development Priorities

### P0 — Core stability (do not break)
- `polyflow run` with parallel steps
- OpenRouter adapter (most users will use this)
- HITL checkpoints
- `--ci` flag (used by GitHub Action)
- `action.yml`

### P1 — Next features (Issues already filed)
- `type: loop` — iterative PDCA loops with termination condition ([#1](https://github.com/celesteimnskirakira/polyflow/issues/1))
- `type: shell` — local command execution for full PDCA automation ([#2](https://github.com/celesteimnskirakira/polyflow/issues/2))

### P2 — Growth
- GitHub Marketplace listing (action.yml is ready)
- More built-in workflows for the `polyflow list` showcase
- Workflow registry (`polyflow pull <name>`) as community grows

---

## What NOT to Build

- **A GUI or web interface** — CLI-first is the positioning. Keep it.
- **An autonomous agent** — That's OpenClaw. Polyflow is declarative and controlled.
- **A SaaS platform** — Open source + GitHub Action is the distribution strategy.
- **Single-model workflows** — Every new built-in workflow should use at least 2 models or demonstrate HITL. Single-model is what every other tool already does.

---

## Key Design Decisions

**Why YAML over Python DSL?**
YAML workflows are version-controllable, PR-reviewable, and writable by non-engineers. Python DSLs (LangChain, CrewAI) require 80+ lines of boilerplate for what Polyflow does in 20 lines of YAML.

**Why OpenRouter as default?**
One API key covers Claude + Gemini + GPT-4. Reduces friction from 3 signups to 1.

**Why HITL as first-class primitive?**
Multi-model parallel execution is most valuable when a human can inspect the diff between model outputs and decide whether to continue. HITL + parallel is the core loop.

**Why `--ci` auto-approves HITL?**
CI/CD pipelines can't wait for human input. `--ci` auto-chooses `continue` (or first option), making all workflows safe to run headlessly.

---

## Promotion Context

- Published on PyPI as `polyflow-ai` (package name `polyflow` was taken)
- GitHub repo: `celesteimnskirakira/polyflow`
- Target: GitHub stars + resume material
- Key angle: "First tool to automate Model Musical Chairs in a GitHub Action"
- HackerNews Show HN is the highest-leverage channel for initial stars
- GitHub Marketplace submission (action.yml ready) is the long-tail channel

---

## Running Tests

```bash
# Unit tests (no API key needed)
pytest tests/ -k "not integration"

# All tests (requires OPENROUTER_API_KEY)
pytest tests/

# Validate a workflow YAML
polyflow validate workflows/examples/code-review-multi-model.yaml
```

Tests cover: schema validation, template rendering, executor logic (retry/backoff, parallel failures, aggregate.model), HITL, CLI commands.
