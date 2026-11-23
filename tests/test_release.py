"""Release checks: manifests, skills and agents parse; no client references or secrets in the QZ layer;
templates are clean; the qz MCP server lists its tools; pricing parity when a workbook is available."""
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))
# Names that must never appear in what ships: clients and people from other engagements. Kept as SHA-256 of the
# lower-case word or two-word phrase, so this file does not carry the names it guards against.
NEVER = {
    "14e4add97c4b517d0d58b375d4be91b8932fc6ce275426685875022ff7c29071",
    "17f52ffe17eb92161fde5ca033dd1f8dfed180dac276cdd7c87aa7defa64428f",
    "1be67d8dff44dcd9c8de939f3b6fb778bb87c8a83fd77a6efae92c76f7939397",
    "229198ac50189365a5dd6412995ab24b4126c777fd69673153f92a0b1ba46882",
    "265719f4e7ee032fe4a0c5ed5735a0530545e4f35c8648155dc5450330327e2a",
    "2b4b2eadf7b2aece598d2f2ad4637361614a738a7cdf1a457d8b46db072184d5",
    "3080162c4b10abf59a29668e0045a35dc68931bae1460d6cf648a57bc0dfc76b",
    "3322532d8589f95c912a7c956aecd5b0d8847263b9021438c72a126041f612e8",
    "375312ba8de49afa1236283d6b331a09c042bb08010b58fb4ba6e028ca4c7d46",
    "5a468dab0c23e11ab5d3bedf1d00ad6d2849c06e60716860b60fdef82034f1e6",
    "753b07add41b34c4b2a2f55e92242eca823efeb31bda8cc0d4ab8d9488845bd0",
    "7f692bc6ed45931699f6cd8cfaa923bd8537be0bb29fa0f3c5951aa43549e341",
    "8c0a50e23d627fe575360c4dfca06c0622aa513e4ec5067a5dae26d7fbf26ae4",
    "93babfec2f0c9778de88e6d0a303448a194353c425497bab45f7ba0a0dbe842d",
    "9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee8f0",
    "af60eaa4482849b325d61fd785454d9441d5d9196af59b3cded5389621b0a382",
    "b261335c03a3b001b796002f482252513133532aa7b893d6a17452181f405673",
    "b67019e259bfa1d16362f1ee7e3da34659ad9d408ee7ebd9a33e9e0d90519d9b",
    "bb5dc9592c60081487b270c05a5fbd2a23a86c3c6cbbfb615586152501a6f099",
    "e424dce6bf0bec35140e35fce06d42d9818231a90cec49125c1bc406a4d47770",
    "e4ffb7bd879b89da05f85a769c5c5f76095b45e83297cd2f79ae68509dfbca51",
    "e9982c51f4725089de6e14c46124a4c07a97469f769550cc426add5eed2b4dd1",
    "f12c3c16aa3d9e59da48044ec282d3f5d5ae30d3535073b027a1d9f446c5f122",
}


def leak(text: str) -> str | None:
    w = re.findall(r"[a-z0-9]+", text.lower())
    for g in set(w) | {f"{a} {b}" for a, b in zip(w, w[1:])}:
        if hashlib.sha256(g.encode()).hexdigest() in NEVER:
            return g
    return None


def frontmatter(p: Path) -> dict:
    t = p.read_text(encoding="utf-8")
    assert t.startswith("---\n"), p
    fm = t.split("---\n")[1]
    return dict(line.split(":", 1) for line in fm.strip().splitlines() if ":" in line and not line.startswith(" "))


def test_manifests_parse():
    for f in [REPO / ".claude-plugin" / "marketplace.json", PLUG / ".claude-plugin" / "plugin.json", PLUG / ".mcp.json",
              PLUG / "hooks" / "hooks.json", PLUG / "policy" / "qz-policy.json", PLUG / "themes" / "qualizeal.json",
              REPO / "managed-settings" / "managed-settings.json"]:
        json.loads(f.read_text(encoding="utf-8"))


def test_skills_and_agents():
    skills = list((PLUG / "skills").glob("*/SKILL.md"))
    assert len(skills) == 40
    for s in skills:
        fm = frontmatter(s)
        assert fm.get("description") and len(fm["description"]) < 400, s
    for a in (PLUG / "agents").glob("*.md"):
        fm = frontmatter(a)
        assert fm["model"].strip() in ("haiku", "sonnet", "opus") and fm.get("description"), a
    assert len(list((PLUG / "agents").glob("*.md"))) == 17
    for lane in ("deliver", "bid", "bid-formats", "demo", "kf", "report", "mentor", "architect", "build", "eval", "test", "audit", "design", "deck", "project", "publish", "spec"):
        assert (PLUG / "skills" / "qz" / "lanes" / f"{lane}.md").exists()


def test_no_client_references_or_secrets_in_qz_layer():
    from qz.guard import scan_secrets
    skip = {"PORT-NOTES.md", "LAYERS.md", "qz-redteam-cases.json"}
    for f in PLUG.rglob("*"):
        if not f.is_file() or "workspace-kit" in f.parts or f.suffix in (".png", ".docx", ".pptx", ".pyc") or f.name in skip:
            continue
        t = f.read_text(encoding="utf-8", errors="ignore")
        assert not leak(t), (f, leak(t))
        assert not scan_secrets(t), f


def test_templates_are_clean():
    for f in (PLUG / "templates").glob("*.pptx"):
        z = zipfile.ZipFile(f)
        assert not [n for n in z.namelist() if n.startswith("ppt/slides/slide")], "deck template must have no slides"
        text = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
        assert not leak(re.sub(r"<[^>]+>", " ", text)), f


def test_mcp_server_lists_tools():
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    r = subprocess.run([sys.executable, str(PLUG / "scripts" / "qz_mcp.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, timeout=30)
    tools = json.loads(r.stdout.splitlines()[1])["result"]["tools"]
    assert {"kf_search", "price_run", "deck_build", "sow_build", "report_card", "redteam", "demo_new", "demo_check", "demo_bundle", "demo_record",
            "arch", "agent_scaffold", "eval_run", "eval", "test_design", "project_audit", "kit_vendor", "doctor",
            "design_review", "web_audit", "ui_probe", "ui_run", "deck_review",
            "project_new", "project_file", "project_status", "project_sync", "house_style", "code_explore", "code_graph",
            "route", "office", "ship_check", "publish", "decisions"} <= {t["name"] for t in tools}
    assert len(tools) == 55
    hints = {t["name"]: t["annotations"] for t in tools}
    assert all(set(h) == {"readOnlyHint", "destructiveHint", "openWorldHint"} for h in hints.values())
    assert hints["kf_search"]["readOnlyHint"] and not hints["kf_search"]["openWorldHint"] and hints["kit_vendor"]["destructiveHint"]
    assert not hints["project_memory"]["readOnlyHint"] and hints["ui_run"]["openWorldHint"] and not hints["ctx"]["destructiveHint"]


def test_pricing_parity_with_workbook():
    wb = os.environ.get("QZ_PRICING_WORKBOOK")
    if not wb or not Path(wb).exists():
        import pytest
        pytest.skip("set QZ_PRICING_WORKBOOK to run the parity test")
    from qz.bid import pricing
    plan = pricing.sample_plan_from_workbook(wb)
    exp = plan.pop("_expected")
    s = pricing.price(plan, pricing.load_catalogue(wb))["summary"]
    for i, b in enumerate(("pre", "transition", "Y1", "Y2", "Y3", "Y4", "Y5", "TCV")):
        assert abs((exp["cost"][i] or 0) - s[b]["cost"]) < 0.01 and abs((exp["rev"][i] or 0) - s[b]["rev"]) < 0.01, b


def test_every_workflow_has_a_run_button_and_a_release_is_checked_before_it_is_committed():
    for f in (REPO / ".github" / "workflows").glob("*.yml"):
        assert "workflow_dispatch:" in f.read_text(encoding="utf-8"), f
    drop = (REPO / ".github" / "workflows" / "unpack-release.yml").read_text(encoding="utf-8")
    assert drop.index("pytest -q tests") < drop.index("git commit"), "a failed check publishes nothing"
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert all(x in ignore for x in (".qz/", "docs/internal/", ".env"))


def test_nothing_the_plugins_ship_is_ignored_by_git(tmp_path):
    """The marketplace installs from a git clone, so a file that git ignores never reaches an attendee's machine.
    A .gitignore inside a shipped kit (the AWS workspace has one) is the usual way this happens."""
    import shutil
    if not shutil.which("git"):
        import pytest
        pytest.skip("git is not installed here")
    files = {p.relative_to(REPO).as_posix() for p in (REPO / "plugins").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    for m in (REPO / "plugins").glob("*/MANIFEST.sha256"):
        files |= {f"{m.parent.relative_to(REPO).as_posix()}/{ln.split('  ', 1)[1]}" for ln in m.read_text(encoding="utf-8").splitlines() if "  " in ln}
    subprocess.run(["git", "init", "-q", str(tmp_path / "g")], check=True, capture_output=True)
    r = subprocess.run(["git", "-c", "core.excludesFile=", f"--git-dir={tmp_path / 'g' / '.git'}", f"--work-tree={REPO}", "check-ignore", "--no-index", "--stdin"],
                       input="\n".join(sorted(files)) + "\n", capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "", f"git ignores files the plugin ships:\n{r.stdout}"


def test_a_release_builds_from_the_repository_with_its_own_notes(tmp_path):
    script = REPO / ".github" / "scripts" / "build_release.py"
    run = lambda *a: subprocess.run([sys.executable, "-I", "-X", "utf8", str(script), *a], capture_output=True, text=True, encoding="utf-8")
    ver = json.loads((PLUG / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    assert run("version").stdout.strip() == ver
    r = run("notes", ver, str(tmp_path / "notes.md"))
    assert r.returncode == 0, r.stderr
    notes = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert notes.strip() and "\n## " not in notes, "one version's section, and nothing after it"
    assert run("notes", "99.0.0", str(tmp_path / "none.md")).returncode != 0, "no release without its changelog section"
    r = run("build", str(tmp_path / "dist"))
    assert r.returncode == 0, r.stdout + r.stderr
    with zipfile.ZipFile(tmp_path / "dist" / f"qz-aidlc-{ver}.zip") as z:
        names = z.namelist()
    assert [n for n in names if n.endswith(".claude-plugin/plugin.json")] == [".claude-plugin/plugin.json"]
    assert {"MANIFEST.sha256", "CREDITS.md"} <= set(names)
    assert not [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".env")) or n.startswith(("docs/internal/", ".qz/"))]
    assert (tmp_path / "dist" / "qz-console-{}.zip".format(json.loads(
        (REPO / "plugins" / "qz-console" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"])).is_file()


def test_releases_and_tidying_run_by_themselves_and_only_after_the_checks():
    wf = REPO / ".github" / "workflows"
    rel = (wf / "release.yml").read_text(encoding="utf-8")
    assert "workflow_run:" in rel and "workflows: [ci]" in rel and "branches: [main]" in rel
    assert "github.event.workflow_run.conclusion == 'success'" in rel and "github.event.workflow_run.event == 'push'" in rel
    assert rel.index('gh release view "v$v"') < rel.index("gh release create"), "a version is released once"
    assert rel.index("build_release.py notes") < rel.index("gh release create"), "no release without its notes"
    assert "macos=true -f containers=true" in rel
    tidy = (wf / "tidy.yml").read_text(encoding="utf-8")
    assert 'select(.name != "main" and (.protected | not))' in tidy
    assert '.merged_at != null and .base.ref == \\"main\\" and .head.sha == \\"$sha\\"' in tidy, "only a merged pull request's own head goes"
    ci = (wf / "ci.yml").read_text(encoding="utf-8")
    assert 'HEAD_REF: ${{ github.head_ref }}' in ci and 'case "$HEAD_REF" in release/*) mac=yes' in ci
    assert "${{ github.head_ref }}" not in ci.replace("HEAD_REF: ${{ github.head_ref }}", ""), "branch names reach the shell as data"
