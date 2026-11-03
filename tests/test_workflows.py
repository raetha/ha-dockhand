"""
Static checks for GitHub Actions workflow files.

Catches common security and correctness issues that GitHub's CodeQL and
actionlint would flag, without requiring those tools to be installed.
Runs as part of the normal test suite so CI failures are caught before push.
"""

from __future__ import annotations

import os
import re

import pytest

yaml = pytest.importorskip(
    "yaml", reason="pyyaml not installed — skipping workflow checks"
)

WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github",
    "workflows",
)


def _load_workflows() -> dict[str, dict]:
    """Return {filename: parsed_yaml} for all workflow files."""
    result = {}
    if not os.path.isdir(WORKFLOWS_DIR):
        return result
    for fname in os.listdir(WORKFLOWS_DIR):
        if fname.endswith((".yml", ".yaml")):
            path = os.path.join(WORKFLOWS_DIR, fname)
            with open(path) as f:
                result[fname] = yaml.safe_load(f)
    return result


def _all_jobs() -> list[tuple[str, str, dict]]:
    """Return [(filename, job_id, job_dict)] for all jobs in all workflows."""
    jobs = []
    for fname, wf in _load_workflows().items():
        for job_id, job in (wf.get("jobs") or {}).items():
            if isinstance(job, dict):
                jobs.append((fname, job_id, job))
    return jobs


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def test_all_jobs_have_permissions():
    workflows = _load_workflows()
    assert workflows, "No workflow files found in .github/workflows/"
    failures = [
        f"{fname}: job '{job_id}' has no permissions block"
        for fname, job_id, job in _all_jobs()
        if "permissions" not in job
    ]
    assert failures == [], (
        "Jobs missing permissions (CodeQL 'Workflow does not contain permissions'):\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_no_job_uses_write_all_permissions():
    """write-all is overly permissive — flag it."""
    failures = [
        f"{fname}: job '{job_id}' uses write-all permissions"
        for fname, job_id, job in _all_jobs()
        if job.get("permissions") == "write-all"
    ]
    assert failures == [], (
        "Jobs with overly broad write-all permissions:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_all_workflows_are_valid_yaml():
    """All .yml files in .github/workflows/ must parse as valid YAML."""
    if not os.path.isdir(WORKFLOWS_DIR):
        pytest.skip(".github/workflows/ not found")
    for fname in os.listdir(WORKFLOWS_DIR):
        if not fname.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(WORKFLOWS_DIR, fname)
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            assert data is not None, f"{fname} parsed as empty/null"
        except yaml.YAMLError as e:
            pytest.fail(f"{fname} failed to parse as YAML: {e}")


def test_all_workflows_have_jobs():
    """Every workflow must define at least one job."""
    for fname, wf in _load_workflows().items():
        assert wf.get("jobs"), f"{fname} has no jobs defined"


def test_all_workflows_have_triggers():
    """Every workflow must define at least one trigger (on:)."""
    for fname, wf in _load_workflows().items():
        trigger = wf.get("on") or wf.get(True)  # YAML parses 'on' as True
        assert trigger is not None, f"{fname} has no trigger defined"


def test_actions_are_pinned_to_commits():
    """Every action is pinned to a full commit SHA (version in a comment), never a tag or branch."""
    unpinned = [
        f"{fname}/{job_id}: {step['uses']}"
        for fname, job_id, job in _all_jobs()
        for step in (job.get("steps") or [])
        if "uses" in step
        and not step["uses"].startswith("./")
        and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"])
    ]
    assert unpinned == [], "Actions must be pinned to a full commit SHA:\n" + "\n".join(
        f"  - {u}" for u in unpinned
    )


def test_no_expressions_inside_run_scripts():
    """${{ }} inside run: is a script-injection risk; pass values through env: instead."""
    risky = [
        f"{fname}/{job_id}: {step.get('name', step['run'][:40])}"
        for fname, job_id, job in _all_jobs()
        for step in (job.get("steps") or [])
        if "run" in step and "${{" in step["run"]
    ]
    assert risky == [], "Expressions inside run: scripts:\n" + "\n".join(
        f"  - {r}" for r in risky
    )


def test_checkouts_drop_credentials_unless_the_job_pushes():
    """persist-credentials: false keeps the token out of .git/config for later steps."""
    kept = [
        f"{fname}/{job_id}"
        for fname, job_id, job in _all_jobs()
        for step in (job.get("steps") or [])
        if step.get("uses", "").startswith("actions/checkout@")
        and (step.get("with") or {}).get("persist-credentials") is not False
        and not any("git push" in s.get("run", "") for s in job.get("steps") or [])
    ]
    assert kept == [], "Checkouts keeping credentials in jobs that never push:\n" + (
        "\n".join(f"  - {k}" for k in kept)
    )


def test_ci_gate_needs_every_check_job():
    """The ruleset requires only 'CI passed', so it must depend on every check job."""
    jobs = _load_workflows()["build.yml"]["jobs"]
    checks = {
        job_id for job_id, job in jobs.items() if job_id != "ci" and "if" not in job
    }
    gate = jobs["ci"]
    assert gate["name"] == "CI passed"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == checks
