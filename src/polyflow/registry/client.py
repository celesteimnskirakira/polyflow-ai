"""
Community workflow registry.
Currently backed by the polyflow GitHub repository's examples directory.
"""
import httpx
from pathlib import Path

_REPO = "celesteimnskirakira/polyflow-community"
_BRANCH = "main"
_WORKFLOWS_PATH = "workflows"

REGISTRY_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/{_BRANCH}/{_WORKFLOWS_PATH}"
REGISTRY_API_URL = f"https://api.github.com/repos/{_REPO}/contents/{_WORKFLOWS_PATH}?ref={_BRANCH}"


async def pull_workflow(name: str, dest: Path) -> None:
    """Download a workflow YAML from the registry."""
    url = f"{REGISTRY_RAW_BASE}/{name}.yaml"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url)
        if response.status_code == 404:
            raise FileNotFoundError(
                f"Workflow '{name}' not found in registry.\n"
                f"Run `polyflow search` to see available workflows."
            )
        response.raise_for_status()
    dest.write_text(response.text, encoding="utf-8")


async def list_workflows() -> list[str]:
    """List available workflows from the registry."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            REGISTRY_API_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        response.raise_for_status()
        files = response.json()

    if isinstance(files, dict) and "message" in files:
        raise RuntimeError(f"GitHub API error: {files['message']}")

    return sorted(
        f["name"].replace(".yaml", "")
        for f in files
        if isinstance(f, dict) and f.get("name", "").endswith(".yaml")
    )
