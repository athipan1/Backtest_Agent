from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#\s]+)", re.MULTILINE)
IMMUTABLE_ACTION_PATTERN = re.compile(r"^[^/@\s]+/[^@\s]+@[0-9a-f]{40}$")


def _external_action_uses() -> list[tuple[Path, str]]:
    references: list[tuple[Path, str]] = []
    for workflow in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        content = workflow.read_text(encoding="utf-8")
        for reference in USES_PATTERN.findall(content):
            if reference.startswith("./"):
                continue
            references.append((workflow, reference))
    return references


def test_all_external_github_actions_use_immutable_commit_shas() -> None:
    references = _external_action_uses()

    assert references, "expected at least one external GitHub Action reference"
    mutable = [
        f"{path.relative_to(REPO_ROOT)}: {reference}"
        for path, reference in references
        if IMMUTABLE_ACTION_PATTERN.fullmatch(reference) is None
    ]
    assert mutable == [], "mutable GitHub Action references found:\n" + "\n".join(mutable)


def test_docker_publish_workflow_uses_node24_native_action_generations() -> None:
    workflow = (WORKFLOWS_DIR / "docker_imge.yml").read_text(encoding="utf-8")

    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in workflow
    assert "docker/login-action@dbcb813823bdd20940b903addbd779551569679f" in workflow
    assert "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a" in workflow
    assert "permissions:\n  contents: read" in workflow
