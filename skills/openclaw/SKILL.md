---
name: polyflow
description: Run multi-model AI workflows using the polyflow CLI. Sends the same task to Claude, Gemini, and GPT-4 in parallel and synthesizes consensus results. Use for code review, security audits, cross-validation, or any task where comparing multiple model outputs improves reliability over a single model's answer.
version: 1.0.0
metadata:
  openclaw:
    requires:
      bins:
        - polyflow
      env:
        - OPENROUTER_API_KEY
    primaryEnv: OPENROUTER_API_KEY
    emoji: "⚡"
    homepage: https://github.com/celesteimnskirakira/polyflow
    install:
      - kind: uv
        package: polyflow-ai
        bins: [polyflow]
---

Run parallel multi-model AI workflows. Three models analyze the same task simultaneously — consensus beats any single AI.

## Setup

```bash
pip install polyflow-ai
export OPENROUTER_API_KEY=sk-or-...   # openrouter.ai — one key for all models
polyflow doctor                        # verify setup
```

## Commands

```bash
# Run a built-in workflow
polyflow run code-review-multi-model -i "$(git diff HEAD~1)"
polyflow run security-audit -i "$(cat src/auth.py)"
polyflow run cross-validate -i "your design or problem"

# Browse 22 built-in workflows
polyflow list
polyflow list --tag security

# Run headlessly (no interactive prompts)
polyflow run <workflow> --ci -i "..."
```

## Workflow selection

| Task | Workflow |
|---|---|
| Code review | `code-review-multi-model` |
| Security scan | `security-audit` |
| Cross-validate a plan | `cross-validate` |
| Bug triage | `bug-triage` |
| Generate tests | `test-generation` |
| PR description | `pr-description` |

## How consensus works

Parallel steps send the same prompt to multiple models simultaneously. Aggregate modes:

- `vote` — findings all models agree on (high confidence)
- `diff` — where models disagree (needs review)
- `summary` — one model synthesizes all outputs

Models check each other. No human approval needed.

## Custom workflow example

```yaml
name: security-consensus
steps:
  - id: audit
    type: parallel
    steps:
      - id: claude
        model: claude
        prompt: "Find security vulnerabilities: {{input}}"
      - id: gemini
        model: gemini
        prompt: "Find security vulnerabilities: {{input}}"
      - id: gpt4
        model: gpt-4
        prompt: "Find security vulnerabilities: {{input}}"
    aggregate:
      mode: vote
      model: claude
```
