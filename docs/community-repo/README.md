# Polyflow Community Workflows

Community-contributed workflows for [Polyflow](https://github.com/celesteimnskirakira/polyflow).

## Using a workflow

```bash
polyflow search                        # browse all workflows
polyflow pull <name>                   # download to current directory
polyflow run <name> -i "your input"    # run it
```

## Contributing a workflow

The easiest way — no git knowledge required:

```bash
polyflow share my-workflow.yaml
```

This opens a PR automatically. A GitHub Actions bot validates the YAML schema and merges it if it passes. Your workflow will be available to everyone within minutes.

**Requirements:**
- A GitHub account
- A [personal access token](https://github.com/settings/tokens/new) with `public_repo` scope
- `export GITHUB_TOKEN=ghp_...`

## Manual contribution

If you prefer the traditional way:

1. Fork this repo
2. Add your workflow to `workflows/`
3. Validate: `polyflow validate workflows/your-workflow.yaml`
4. Open a PR — the bot validates and merges automatically

## Workflow requirements

- Must pass `polyflow validate`
- Must include `name`, `description`, `version`, and `tags` fields
- File name must be lowercase kebab-case (e.g. `my-workflow.yaml`)

## Available workflows

Browse the [`workflows/`](workflows/) directory or run `polyflow search`.
