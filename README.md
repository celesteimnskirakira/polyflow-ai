# Polyflow

[![PyPI version](https://img.shields.io/pypi/v/polyflow-ai.svg)](https://pypi.org/project/polyflow-ai/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-59%20passing-brightgreen.svg)](#)

**Run multi-model AI workflows in a single YAML file.**

Combine Claude, Gemini, and GPT-4 — parallel or sequential — with human checkpoints, template variables, and output saving. No boilerplate, no SDK juggling.

```
pip install polyflow
export OPENROUTER_API_KEY=sk-or-...
polyflow run code-review-multi-model -i "$(git diff HEAD~1)"
```

---

## Why Polyflow?

Most AI tasks aren't one prompt. A good code review means:
1. Claude reads the diff and identifies issues
2. Gemini checks for security vulnerabilities in parallel
3. GPT-4 suggests refactoring
4. You approve before the final summary is written

Polyflow makes this a **20-line YAML file** you can save, share, and version-control.

---

## Install

```bash
pip install polyflow
```

Requires Python 3.11+.

**Set up API keys** (one key covers all models):

```bash
export OPENROUTER_API_KEY=sk-or-...    # openrouter.ai — Claude + Gemini + GPT-4
```

Or configure per-model keys:

```bash
polyflow init
```

Verify your setup:

```bash
polyflow doctor
```

---

## Quick Start

```bash
# Browse 22 ready-to-use workflows
polyflow list

# Run a code review on your last commit
polyflow run code-review-multi-model -i "$(git diff HEAD~1)"

# Triage a bug report
polyflow run bug-triage -i "TypeError: 'NoneType' object is not subscriptable in auth.py:42"

# Run a security audit
polyflow run security-audit -i "$(cat src/auth.py)"

# Generate a new workflow from a description
polyflow new "Claude writes an ADR, Gemini challenges it, I approve" -o adr-flow.yaml
```

---

## Example Workflow

```yaml
name: code-review-multi-model
description: "Parallel review by 3 models with human approval"
version: "1.0"

steps:
  - id: analyze
    name: Analyze Diff
    model: claude
    prompt: |
      Review this code diff. List issues by severity.
      {{input}}

  - id: cross_validate
    name: Cross-Validate
    type: parallel
    steps:
      - id: security
        model: gemini
        prompt: "Check for security vulnerabilities: {{steps.analyze.output}}"
      - id: refactor
        model: gpt-4
        prompt: "Suggest refactoring improvements: {{steps.analyze.output}}"
    aggregate:
      mode: diff           # show what models agree/disagree on

  - id: review_gate
    name: Human Review
    model: claude
    prompt: "Summarize all feedback: {{steps.cross_validate.output}}"
    hitl:
      message: "Review complete. Ship it?"
      options: [approve, revise, abort]
      show: raw

  - id: final
    name: Final Report
    model: claude
    condition: "{{hitl.review_gate.choice}} == 'approve'"
    prompt: |
      Write a final review report.
      Analysis: {{steps.analyze.output}}
      Cross-validation: {{steps.cross_validate.output}}

output:
  format: markdown
  save_to: review-output.md
```

---

## Core Concepts

### Template Expressions

| Expression | Description |
|---|---|
| `{{input}}` | Input passed with `-i` |
| `{{steps.step_id.output}}` | Output from a previous step |
| `{{hitl.step_id.choice}}` | User's choice at a HITL checkpoint |
| `{{hitl.step_id.note}}` | Revision notes from HITL |
| `{{vars.key}}` | Workflow variable |
| `{{context}}` | Injected file/directory context |
| `{{a \| b}}` | Fallback: use `b` if `a` is empty |

### Parallel Steps + Aggregation

```yaml
- id: validate
  type: parallel
  steps:
    - id: gemini_view
      model: gemini
      prompt: "..."
    - id: gpt4_view
      model: gpt-4
      prompt: "..."
  aggregate:
    mode: diff        # diff | vote | summary | raw
    model: claude     # optional synthesis model
```

### Human-in-the-Loop (HITL)

```yaml
hitl:
  message: "Review and decide:"
  options: [continue, revise, abort]
  show: raw             # diff | summary | raw
```

Use the choice downstream:

```yaml
condition: "{{hitl.step_id.choice}} == 'revise'"
```

### Context Injection

Automatically inject project files into your prompt:

```yaml
context:
  inject_cwd: true              # project file tree
  inject_files:
    - "src/**/*.py"
    - "README.md"
  max_file_size: 50kb
```

### Error Handling

```yaml
on_error:
  retry: 2
  fallback: continue    # abort | continue | skip
```

---

## CLI Reference

```
polyflow list [--tag security]       Browse available workflows
polyflow run <name|path> -i "..."    Run a workflow
polyflow validate <file.yaml>        Validate workflow YAML
polyflow new "description" -o f.yaml Generate from natural language
polyflow pull <name>                 Download from community registry
polyflow search                      List community workflows
polyflow init                        Configure API keys
polyflow doctor                      Check your setup
polyflow schema                      Show full YAML schema reference
```

---

## Available Workflows (22 built-in)

| Workflow | Description |
|---|---|
| `code-review-multi-model` | Parallel review by Claude + Gemini + GPT-4 |
| `security-audit` | OWASP-based security analysis |
| `bug-triage` | Severity classification + fix suggestions |
| `test-generation` | Unit test generation with coverage analysis |
| `pr-description` | Auto-generate PR descriptions from diffs |
| `feature-spec` | Convert user story → technical specification |
| `adr-generator` | Architecture Decision Record with stakeholder review |
| `incident-postmortem` | Structured incident analysis |
| `api-documentation` | OpenAPI documentation generation |
| `database-schema-design` | Schema design with normalization review |
| `deploy-checklist` | Pre-deployment readiness check |
| `changelog-generator` | Conventional commit → changelog |
| `dependency-audit` | Vulnerability + license analysis |
| `performance-analysis` | Bottleneck identification + optimization |
| `microservice-design` | Service boundary design with ADR |
| `data-pipeline-design` | ETL/streaming architecture design |
| `technical-interview` | Interview question generation |
| `content-moderation` | Multi-model content policy review |
| `api-spec-design` | REST API spec from requirements |
| `code-refactoring` | Refactoring plan with safety analysis |

Browse with `polyflow list` or see all in [`workflows/examples/`](workflows/examples/).

---

## Models

| Alias | Model | Provider |
|---|---|---|
| `claude` | Claude Sonnet | Anthropic / OpenRouter |
| `gemini` | Gemini 2.0 Flash | Google / OpenRouter |
| `gpt-4` | GPT-4o | OpenAI / OpenRouter |

**Recommended:** Use [OpenRouter](https://openrouter.ai) for a single API key that covers all three models.

---

## Architecture

```
YAML workflow
    ↓
Pydantic validation (schema/workflow.py)
    ↓
Jinja2-style template engine (engine/template.py)
    ↓
Async executor (engine/executor.py)
    ├── Sequential steps
    ├── Parallel steps → asyncio.gather
    ├── HITL checkpoints
    └── Conditional skip
    ↓
Model adapters (models/)
    ├── OpenRouter (unified — recommended)
    ├── Claude (Anthropic SDK)
    ├── Gemini (google-genai)
    └── GPT-4 (openai)
    ↓
Output saving (markdown | json | text)
```

---

## Contributing

Workflows are plain YAML — no code required.

1. Fork the repo
2. Add your workflow to `workflows/examples/`
3. Validate: `polyflow validate your-workflow.yaml`
4. Open a PR

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT — see [LICENSE](LICENSE).
