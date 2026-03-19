"""
Static checks for GitHub Actions workflow files.

Catches common security and correctness issues that GitHub's CodeQL and
actionlint would flag, without requiring those tools to be installed.
Runs as part of the normal unittest suite so CI failures are caught
before push.
"""
from __future__ import annotations
import os
import unittest

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".github", "workflows",
)


def _load_workflows() -> dict[str, dict]:
    """Return {filename: parsed_yaml} for all workflow files."""
    if not HAS_YAML:
        return {}
    result = {}
    if not os.path.isdir(WORKFLOWS_DIR):
        return result
    for fname in os.listdir(WORKFLOWS_DIR):
        if fname.endswith((".yml", ".yaml")):
            path = os.path.join(WORKFLOWS_DIR, fname)
            with open(path) as f:
                result[fname] = yaml.safe_load(f)
    return result


@unittest.skipUnless(HAS_YAML, "pyyaml not installed — skipping workflow checks")
class TestWorkflowPermissions(unittest.TestCase):
    """Every job must declare explicit permissions (least-privilege principle).

    GitHub's CodeQL flags jobs that inherit the default token permissions,
    which are overly broad. Each job should declare at minimum:
        permissions:
          contents: read
    """

    def test_all_jobs_have_permissions(self):
        workflows = _load_workflows()
        self.assertTrue(workflows, "No workflow files found in .github/workflows/")
        failures = []
        for fname, wf in workflows.items():
            jobs = wf.get("jobs") or {}
            for job_id, job in jobs.items():
                if not isinstance(job, dict):
                    continue
                if "permissions" not in job:
                    failures.append(f"{fname}: job '{job_id}' has no permissions block")
        self.assertEqual(
            failures, [],
            "Jobs missing permissions (CodeQL 'Workflow does not contain permissions'):\n"
            + "\n".join(f"  - {f}" for f in failures),
        )

    def test_no_job_uses_write_all_permissions(self):
        """write-all is overly permissive — flag it as a warning."""
        workflows = _load_workflows()
        failures = []
        for fname, wf in workflows.items():
            jobs = wf.get("jobs") or {}
            for job_id, job in jobs.items():
                if not isinstance(job, dict):
                    continue
                perms = job.get("permissions")
                if perms == "write-all":
                    failures.append(f"{fname}: job '{job_id}' uses write-all permissions")
        self.assertEqual(
            failures, [],
            "Jobs with overly broad write-all permissions:\n"
            + "\n".join(f"  - {f}" for f in failures),
        )


@unittest.skipUnless(HAS_YAML, "pyyaml not installed — skipping workflow checks")
class TestWorkflowStructure(unittest.TestCase):
    """Basic structural checks on workflow files."""

    def test_all_workflows_are_valid_yaml(self):
        """All .yml files in .github/workflows/ must parse as valid YAML."""
        if not os.path.isdir(WORKFLOWS_DIR):
            self.skipTest(".github/workflows/ not found")
        for fname in os.listdir(WORKFLOWS_DIR):
            if not fname.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(WORKFLOWS_DIR, fname)
            with self.subTest(file=fname):
                try:
                    with open(path) as f:
                        data = yaml.safe_load(f)
                    self.assertIsNotNone(data, f"{fname} parsed as empty/null")
                except yaml.YAMLError as e:
                    self.fail(f"{fname} failed to parse as YAML: {e}")

    def test_all_workflows_have_jobs(self):
        """Every workflow must define at least one job."""
        for fname, wf in _load_workflows().items():
            with self.subTest(file=fname):
                jobs = wf.get("jobs") or {}
                self.assertTrue(jobs, f"{fname} has no jobs defined")

    def test_all_workflows_have_triggers(self):
        """Every workflow must define at least one trigger (on:)."""
        for fname, wf in _load_workflows().items():
            with self.subTest(file=fname):
                trigger = wf.get("on") or wf.get(True)  # YAML parses 'on' as True
                self.assertIsNotNone(trigger, f"{fname} has no trigger defined")

    def test_checkout_actions_use_pinned_version(self):
        """actions/checkout and actions/setup-python should use @v4/@v5, not @main."""
        unpinned = []
        for fname, wf in _load_workflows().items():
            for job_id, job in (wf.get("jobs") or {}).items():
                if not isinstance(job, dict):
                    continue
                for step in job.get("steps") or []:
                    uses = step.get("uses", "")
                    if uses.startswith(("actions/checkout", "actions/setup-python")):
                        if uses.endswith("@main") or uses.endswith("@master"):
                            unpinned.append(f"{fname}/{job_id}: {uses}")
        self.assertEqual(
            unpinned, [],
            "Official actions should use pinned versions (@v4, @v5), not @main/@master:\n"
            + "\n".join(f"  - {u}" for u in unpinned),
        )


if __name__ == "__main__":
    unittest.main()
