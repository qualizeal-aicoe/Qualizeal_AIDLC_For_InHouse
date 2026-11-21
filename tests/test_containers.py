"""Every starter ships a container that proves itself: its gold set runs inside the image with no network, the image
runs as a non-root user with a working health check, and nothing private (keys, rates, run ledgers) is copied in.
These are the structural checks; CI builds every image and runs them (.github/scripts/container_check.py)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "qz-aidlc"
BUILD = PLUGIN / "templates" / "build"
STARTERS = sorted(p.name for p in BUILD.iterdir() if (p / "scaffold.json").is_file())
NEVER_IN_AN_IMAGE = (".env", ".env.*", ".git", ".qz/internal", ".qz/runs", ".qz/scratch", "traces")


def stages(dockerfile: str) -> list[str]:
    parts = re.split(r"(?m)^FROM ", dockerfile)
    return ["FROM " + p for p in parts[1:]]


def test_there_are_thirteen_starters_and_each_has_a_container():
    assert len(STARTERS) == 13, STARTERS
    for s in STARTERS:
        assert (BUILD / s / "Dockerfile").is_file() and (BUILD / s / ".dockerignore").is_file(), s


@pytest.mark.parametrize("name", STARTERS)
def test_the_container_file_is_pinned_non_root_and_healthy(name):
    text = (BUILD / name / "Dockerfile").read_text(encoding="utf-8")
    assert text.startswith("# syntax=docker/dockerfile:1"), name
    for line in re.findall(r"(?m)^FROM (\S+)", text):
        image = line.split("@")[0]
        assert ":" in image.rsplit("/", 1)[-1] and not image.endswith(":latest"), f"{name}: unpinned base image {line}"
    final = stages(text)[-1]
    users = re.findall(r"(?m)^USER (\S+)", final)
    assert users and users[-1] not in ("root", "0"), f"{name}: the final image must run as a non-root user"
    assert re.search(r'(?m)^HEALTHCHECK .*CMD \["', final), f"{name}: an exec-form health check in the final image"
    assert re.search(r"(?m)^(CMD|ENTRYPOINT) \[", final), f"{name}: an exec-form command"


@pytest.mark.parametrize("name", STARTERS)
def test_nothing_private_is_copied_into_the_image(name):
    ignored = set((BUILD / name / ".dockerignore").read_text(encoding="utf-8").split())
    missing = [x for x in NEVER_IN_AN_IMAGE if x not in ignored]
    assert not missing, f"{name}: .dockerignore must keep these out of the image: {missing}"
    assert not re.search(r"(?mi)^(ARG|ENV) \S*(KEY|TOKEN|SECRET|PASSWORD)\b", (BUILD / name / "Dockerfile").read_text(encoding="utf-8")), \
        f"{name}: no credential is baked into an image"


@pytest.mark.parametrize("name", STARTERS)
def test_the_container_check_runs_with_no_network_and_is_the_one_ci_runs(name):
    meta = json.loads((BUILD / name / "scaffold.json").read_text(encoding="utf-8"))
    check = meta["container_check"]
    assert "--network none" in check and "app:ci" in check, check
    if "--target gold" in check:   # the gold set runs in its own build stage
        assert re.search(r"(?m)^FROM .* AS gold$", (BUILD / name / "Dockerfile").read_text(encoding="utf-8")), name
    own_ci = BUILD / name / ".github" / "workflows" / "ci.yml"
    if own_ci.is_file():           # a kit with its own CI names the check in it; the rest get it from _common
        assert check in own_ci.read_text(encoding="utf-8"), f"{name}: its CI must run {check!r}"


def test_a_created_project_carries_its_container_release_recipe_and_ci_job(tmp_path):
    for name, stack in (("Order Support", "langgraph"), ("Policy Desk", "vectorless-rag")):
        dest = tmp_path / stack
        r = subprocess.run([sys.executable, "-I", str(PLUGIN / "scripts" / "qz.py"), "build", "new", stack, str(dest), "--name", name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stdout + r.stderr
        slug = name.lower().replace(" ", "-")
        docker = (dest / "Dockerfile").read_text(encoding="utf-8")
        assert f"docker build -t {slug} ." in docker and "__SLUG__" not in docker
        ci = (dest / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "container:" in ci and "docker build -t app:ci ." in ci and "--network none" in ci and "__CONTAINER_CHECK__" not in ci
        release = (dest / "docs" / "release.md").read_text(encoding="utf-8")
        for part in ("Shadow", "A small share", "Everyone", "Rollback: one switch", f"{slug}:<previous tag>", "--network none"):
            assert part in release, (stack, part)
        readme = (dest / "README.md").read_text(encoding="utf-8")
        assert "## Container and release" in readme, stack


def test_the_hybrid_kit_downloads_both_models_at_build_so_it_answers_offline():
    text = (BUILD / "advanced-rag" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARAG_MODEL_CACHE=/app/.models" in text
    assert re.search(r"(?m)^RUN .*arag ingest.*arag search --hybrid", text), "the reranker is loaded once at build"


def test_the_studio_ci_builds_every_image_on_a_release_branch():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("\n  containers:"):]
    assert "startsWith(github.head_ref, 'release/')" in job and "container_check.py" in job
    listed = re.search(r"stack: \[([^\]]+)\]", job, re.S).group(1)
    assert sorted(s.strip() for s in listed.split(",")) == STARTERS
