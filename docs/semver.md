# Versioning policy

This is the canonical semver policy for both `ha-dockhand` and `ha-dockhand-cards`. One document, referenced from both repos' development guides, rather than two copies that can drift apart — the two repos already share release mechanics (a release pull request sets the version and dates the `CHANGELOG.md` section; CI tags and publishes), so the policy governing *which* bump applies should be shared too.

`ha-dockhand-cards` has its own small supplement for concerns that only make sense there — see "Versioning" in [ha-dockhand-cards' development guide](https://github.com/raetha/ha-dockhand-cards/blob/main/docs/development.md#versioning).

Standard [SemVer](https://semver.org/) (`MAJOR.MINOR.PATCH`), with the following made concrete for these two repos specifically, since "breaking" is otherwise a judgment call and that judgment call has drifted before.

## Major — breaking

Anything that can break an existing user's working setup without them changing their own config, or that removes something they may depend on:

- **ha-dockhand:**
  - A config entry schema **major** bump (`SCHEMA_VERSION`), with or without a migration — downgrading across it stops working, and entries more than one schema major old can no longer be upgraded. It's the clean-up point for old rename code, so it only happens in a major release; see `docs/architecture.md` §4.
  - Renaming or removing a stored setting *without* a migration (the user's choice is lost). With one — a `RenamedOption` plus a `SCHEMA_MINOR_VERSION` bump — it's minor: the setting carries over, and a downgrade to a release on the previous schema version keeps it too.
  - Renaming an existing entity `translation_key` — this is a cross-repo break, since `ha-dockhand-cards` resolves entities by `translation_key` (see that repo's `docs/architecture.md` §1). Coordinate a release on both sides when this happens.
  - Removing an entity, service, or a previously-supported HA version from the compatibility floor.
- **ha-dockhand-cards:**
  - Renaming a card's `type` (the `custom:dockhand-*-card` string) or removing a card entirely.
  - Renaming or removing an existing YAML config key *without* a working backward-compatible fallback for it. Same reasoning as the config entry `VERSION` case above: a genuine migration — the old key keeps being read correctly indefinitely, with no user action ever required, and normal use of the editor naturally migrates a config to the new key without the user having to do anything deliberate — is what keeps a rename from being breaking to the end user, not the rename itself. This only applies when the fallback is real and unconditional (every code path that reads the value falls back correctly, not just the common one) and is actually verified end-to-end, not assumed; a rename with no fallback, or a fallback that only covers some cases, is still major.
  - Dropping support for an entity/attribute shape a released version currently reads (e.g. requiring a newer ha-dockhand release than before, with no fallback).

## Minor — new capability, backward compatible

- A new entity, sensor, service, or card.
- A new optional config key, editor field, or card mode.
- New locale coverage, or new translated strings alongside existing ones.
- Any additive change where an existing config keeps working unmodified.
- A stored setting renamed or moved with a migration (schema minor bump) — see Major above.

## Patch — no capability change

- Bug fixes, including making behavior that was already meant to work actually work, even when the fix needs a new Dockhand API call (1.11.2 shipped Dockhand's own release check for #48 as a patch).
- Cosmetic/visual fixes that don't change behavior.
- Translation fill-ins for already-covered keys.
- Documentation.

## Adding a new `translation_key`

Not breaking on its own (existing keys are untouched), but it's still worth bumping at least minor and calling it out clearly in `CHANGELOG.md`, since `ha-dockhand-cards` may want a corresponding release to actually resolve and use the new entity.

## HA compatibility floor: the two repos are allowed to differ, but only one direction

Both repos require Home Assistant 2026.8 from 2.0.0, matching other widely used custom integrations; it's where HA's entry-scoped device registry calls arrived, so neither repo needs a fallback for older device lookups. Raising either floor is a major change (above).

The rule going forward: **`ha-dockhand-cards`' floor must never sit below `ha-dockhand`'s** — the cards depend on the integration, not the reverse, so there's no scenario where an older cards floor than the integration's makes sense. Whenever `ha-dockhand`'s HA minimum is raised for a release, raise `ha-dockhand-cards`' to at least match in the same pass (verify against HA's real frontend source first rather than assuming compatibility) — don't wait for a separate ask. They don't need to match at every point in between; they need to never invert.

## Notes

- This applies going forward from 2026-07-24. Past `ha-dockhand` releases aren't being retroactively relabeled against this policy — some had scope that would read as "major" under these rules (e.g. config entry version bumps shipped as minor releases). Treat this document as the standard starting now, not a historical audit.
- When a change is ambiguous (e.g. a large minor with several additive pieces vs. a proper major), prefer being conservative — a slightly-too-high bump costs nothing; a slightly-too-low one erodes trust in the version number meaning anything.
