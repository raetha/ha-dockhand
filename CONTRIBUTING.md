# Contributing

Thanks for helping with Dockhand. Bug reports, ideas and translation fixes are all welcome.

- **Issues:** use the issue templates, and attach the integration's diagnostics download where it
  helps (Settings → Devices & services → Dockhand → ⋮ → Download diagnostics; it's made safe to
  post publicly).
- **Before proposing a feature,** check [docs/backlog.md](docs/backlog.md): it records ideas
  already evaluated and deliberately deferred or rejected, and why.
- **Pull requests:** open them against the `dev` branch, not `main` (`main` only receives
  releases). Before you do:
  - `bash scripts/run_tests.sh --full` passes (ruff, mypy, the quality scale rule check, and the
    full test suite with its 100% coverage gate; needs Python 3.14.2+).
  - Add a line under `## [Unreleased]` in `CHANGELOG.md` describing the change for people using
    the integration. Don't change the version in `manifest.json` or date a changelog section:
    that's the release step.
  - Adding an entity, device or config option? Work through
    [docs/architecture.md](docs/architecture.md)'s §5 checklist first: unique IDs, entity cleanup
    and config migrations go wrong silently.
  - New user-facing strings go into every locale file in the same pull request.
- **Translations** are machine-generated; corrections from native speakers are especially
  welcome, and need no Python knowledge. See "Translations" in the guide for how to correct one or
  add a language.

Setup, testing, code style, the changelog rules and how releases work are in
[docs/development.md](docs/development.md).
