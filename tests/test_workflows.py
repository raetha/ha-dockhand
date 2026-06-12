"""
Static checks for GitHub Actions workflow files.

Catches common security and correctness issues that GitHub's CodeQL and
actionlint would flag, without requiring those tools to be installed.
Runs as part of the normal test suite so CI failures are caught before push.
"""

from __future__ import annotations

import os

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml not installed — skipping workflow checks")

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


def test_checkout_actions_use_pinned_version():
    """actions/checkout and actions/setup-python should use a pinned version, not @main."""
    unpinned = [
        f"{fname}/{job_id}: {step.get('uses', '')}"
        for fname, job_id, job in _all_jobs()
        for step in (job.get("steps") or [])
        if step.get("uses", "").startswith(("actions/checkout", "actions/setup-python"))
        and (
            step["uses"].endswith("@main") or step["uses"].endswith("@master")
        )
    ]
    assert unpinned == [], (
        "Official actions should use a pinned version (e.g. @v6), not @main/@master:\n"
        + "\n".join(f"  - {u}" for u in unpinned)
    )
