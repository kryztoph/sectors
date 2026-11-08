#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


PROJECT_DIR = Path(os.environ.get("SECTORS_PROJECT_DIR", Path(__file__).resolve().parents[1]))
DEFAULT_REPO = "kryztoph/csfox-reports"
BRANCH = os.environ.get("SECTORS_PUBLISH_BRANCH", os.environ.get("SECTORS_REPORTS_BRANCH", "master"))
LOGO_SOURCE = Path(os.environ.get("SECTORS_LOGO_SOURCE", "/Users/fox/Desktop/logo.png"))


def main() -> int:
    repo = _repo_name()
    _validate_target(repo, BRANCH)
    os.chdir(PROJECT_DIR)
    files = _publish_files()

    # Resolve canonical identity before any Git write (including renamed repos).
    metadata = _gh_json(f"repos/{repo}")
    canonical = metadata["full_name"]
    _validate_target(canonical, BRANCH)
    if canonical.casefold() != repo.casefold():
        raise ValueError("repository redirect rejected; configure its canonical name explicitly")

    base_commit = _gh_json(f"repos/{repo}/git/ref/heads/{BRANCH}")["object"]["sha"]
    base_tree = _gh_json(f"repos/{repo}/git/commits/{base_commit}")["tree"]["sha"]
    existing_paths = _tree_paths(repo, base_tree)

    tree_entries = []
    for source, target in files:
        blob = _create_blob(repo, source)
        tree_entries.append(
            {
                "path": target,
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            }
        )
    for target in _deleted_paths():
        if target in existing_paths:
            tree_entries.append(
                {
                    "path": target,
                    "mode": "100644",
                    "type": "blob",
                    "sha": None,
                }
            )

    tree = _gh_json(
        f"repos/{repo}/git/trees",
        method="POST",
        body={"base_tree": base_tree, "tree": tree_entries},
    )
    if tree["sha"] == base_tree:
        print("no report changes to commit")
        return 0

    commit = _gh_json(
        f"repos/{repo}/git/commits",
        method="POST",
        body={
            "message": "Update published reports",
            "tree": tree["sha"],
            "parents": [base_commit],
        },
    )
    _gh_json(
        f"repos/{repo}/git/refs/heads/{BRANCH}",
        method="PATCH",
        body={"sha": commit["sha"], "force": False},
    )
    print(f"published report trees to {repo}@{BRANCH}: {commit['sha']}")
    return 0


def _repo_name() -> str:
    for key in ("SECTORS_PUBLISH_REPO", "SECTORS_PUBLISH_REPO_URL", "SECTORS_REPORTS_REPO_URL"):
        if os.environ.get(key):
            _validate_target(_parse_repo(os.environ[key]), BRANCH)
    explicit = os.environ.get("SECTORS_PUBLISH_REPO")
    if explicit:
        return _parse_repo(explicit)
    url = os.environ.get("SECTORS_PUBLISH_REPO_URL") or os.environ.get("SECTORS_REPORTS_REPO_URL")
    if not url:
        return DEFAULT_REPO
    return _parse_repo(url)


def _parse_repo(value: str) -> str:
    value = value.strip()
    if value.startswith("git@github.com:"):
        path = value[len("git@github.com:"):]
    elif "://" in value:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment:
            raise ValueError("only canonical GitHub HTTPS repository URLs are supported")
        path = parsed.path.strip("/")
    else:
        path = value.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", path) or path.split("/")[1] in {".", ".."}:
        raise ValueError(f"cannot parse GitHub repository from {value!r}")
    return path


def _validate_target(repo: str, branch: str) -> None:
    if _parse_repo(repo).casefold() == "kryztoph/csfox":
        raise ValueError("publication to frontend kryztoph/csfox is forbidden; use kryztoph/csfox-reports")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) or ".." in branch or "//" in branch:
        raise ValueError("invalid publication branch")
    if repo.casefold() == DEFAULT_REPO and branch != "master":
        raise ValueError("csfox-reports publication requires verified target branch master")


def _publish_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    if LOGO_SOURCE.is_file():
        files.append((LOGO_SOURCE, "assets/logo.png"))

    files.extend(_sector_files())
    files.extend(_cotpy_files())
    files.extend(_analysis_files())

    if not files:
        raise FileNotFoundError("no report files found to publish")
    return files


def _analysis_files() -> list[tuple[Path, str]]:
    # Analysis is opt-in; the daily and weekly collectors do not generate it.
    paths = [Path("reports/candidates") / name for name in ("latest.json", "latest.md", "latest.html")]
    if not all(path.is_file() for path in paths):
        return []
    return [(path, f"reports/sectors/candidates/{path.name}") for path in paths]


def _sector_files() -> list[tuple[Path, str]]:
    tracker = Path("reports/sector_rotation_tracker.html")
    charts_index = Path("reports/sector_charts.html")
    briefs = sorted(path for path in Path("reports").glob("*-brief.md") if path.name != "latest-brief.md")

    required = [tracker, charts_index]
    for path in required:
        if not path.is_file():
            return []
    if not briefs:
        return []
    latest_brief_html = briefs[-1].with_suffix(".html")
    if not latest_brief_html.is_file():
        return []

    chart_pages = sorted(Path("reports/charts").glob("*.html"))
    if not chart_pages:
        return []

    files: list[tuple[Path, str]] = [
        (tracker, "reports/sectors/sector_rotation_tracker.html"),
        (charts_index, "reports/sectors/sector_charts.html"),
        (latest_brief_html, "reports/sectors/latest-brief.html"),
        (briefs[-1], "reports/sectors/latest-brief.md"),
    ]
    files.extend((path, f"reports/sectors/charts/{path.name}") for path in chart_pages)
    return files


def _cotpy_files() -> list[tuple[Path, str]]:
    index = Path("reports/cotpy/index.html")
    chart_pages = sorted(Path("reports/cotpy/charts").glob("*_interactive.html"))
    if not index.is_file() or not chart_pages:
        return []

    files: list[tuple[Path, str]] = [(index, "reports/cotpy/index.html")]
    files.extend((path, f"reports/cotpy/charts/{path.name}") for path in chart_pages)
    return files


def _deleted_paths() -> list[str]:
    return []


def _tree_paths(repo: str, tree_sha: str) -> set[str]:
    tree = _gh_json(f"repos/{repo}/git/trees/{tree_sha}?recursive=1")
    return {
        str(item.get("path"))
        for item in tree.get("tree", [])
        if isinstance(item, dict) and item.get("path")
    }


def _create_blob(repo: str, path: Path) -> dict[str, object]:
    content = base64.b64encode(path.read_bytes()).decode("ascii")
    return _gh_json(
        f"repos/{repo}/git/blobs",
        method="POST",
        body={"content": content, "encoding": "base64"},
    )


def _gh_json(endpoint: str, method: str = "GET", body: dict[str, object] | None = None) -> dict[str, object]:
    cmd = ["gh", "api", endpoint, "--method", method]
    input_data = None
    if body is not None:
        cmd.extend(["--input", "-"])
        input_data = json.dumps(body).encode("utf-8")
    completed = subprocess.run(cmd, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"gh api failed: {' '.join(cmd)}")
    return json.loads(completed.stdout.decode("utf-8"))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
