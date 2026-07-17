# salesagent review harness

A multi-agent pull-request review harness for the [Prebid Sales Agent](https://github.com/prebid/salesagent)
(the AdCP sales-agent reference implementation). It fans out eight specialist
reviewers from one orchestrator command, each grounded in a shared review charter
and a bundled corpus of behavioral memory, and consolidates their findings with
symmetric verification.

It is an **overlay on a salesagent working copy** — the agents reference that
repo's `CLAUDE.md`, `src/`, `tests/`, structural guards, and the `verify-spec` /
`inspect-bdd-steps` / `guard` skills. It does not run standalone.

## What's in it

| Layer | Path | Role |
|---|---|---|
| Orchestrator | `.claude/commands/full-review.md` | `/full-review` — runs in the main session, derives the review target, fans out specialists, consolidates. Owns audit dimensions A (review completeness), B (CI), G (quality gates), H (process). |
| Specialists (8) | `.claude/agents/review-*.md` | One reviewer per surface: `code-patterns`, `error-wire`, `architecture-guards`, `test-integrity`, `bdd`, `spec-conformance`, `security`, `admin-ui`. |
| Discipline | `.claude/rules/private/review-charter.md` | The non-negotiable operating rules, the masking-gotcha doctrine, and the finding/report format. Step-0 read for every agent. |
| Tooling | `.claude/rules/private/reviewer-tooling.md` | Detection commands and false-green recipes the charter cites. |
| Detectors (10) | `.claude/rules/private/detectors/*.py` | Mechanized gates the charter, agents, and orchestrator invoke: disposition ledger, review completeness, spec-citation freshness, recovery audit, SDK-vs-spec drift, SSOT/duplication, import cycles, FIXME format, suggestion audit, and `bump_check.py` (the one-command drill for an `adcp` pin bump). Each ships a `--selftest`/self-test mode. |
| Reference corpus | `.claude/rules/private/memory/*.md` | Repo-fact reference files the agents read for grounding — the P1–P42 review-pattern catalog, wire-envelope policy, BDD harness patterns/pitfalls, AdCP spec-grounding guides, and test-infra gotchas. |

## Requirements

- [Claude Code](https://claude.com/claude-code) — the agents and `/full-review` are Claude Code constructs.
- A local [salesagent](https://github.com/prebid/salesagent) working copy to review. The harness
  installs into its `.claude/` and references its source, tests, skills, and
  `make quality` / `run_all_tests.sh`.
- `gh` CLI for PR-mode reviews (also used by the `review_completeness` detector).
- Python 3.10+ for the detectors (stdlib only). `recovery_audit` and `sdk_spec_drift`
  introspect the installed `adcp` SDK, so run those two via `uv run python` from the
  salesagent repo root; their spec snapshots are pinned to the repo's `adcp` version and
  hard-fail with instructions when the pin moves (`bump_check.py` is the refresh drill).

## Install

From the root of a salesagent working copy:

```bash
/path/to/salesagent-review-harness/install.sh
```

Or pass an explicit target:

```bash
./install.sh /path/to/salesagent
```

This copies the agents, the `/full-review` command, the charter + tooling, the
detectors, and the memory corpus into the target's `.claude/`.

The salesagent repo's own `.gitignore` already ignores every installed path
(`.claude/agents/review-*.md`, `.claude/commands/*-review.md`, `.claude/rules/private/`,
`.claude/reports`), so the install leaves the target's `git status` clean.

## Use

From the salesagent repo root:

```
/full-review 1399                # review PR #1399
/full-review src/core/tools/     # review an explicit path/glob
/full-review                     # review the current working tree
```

The orchestrator detects the mode, dispatches only the specialists the target
touches, consolidates with de-duplication and symmetric verification, and produces
one report. It **drafts** PR-thread replies but never posts them, and **proposes**
fixes but never applies them.

## Notes

- **Pattern IDs:** bracketed citations in the charter and agents (e.g.
  `feedback_verify_before_asserting`) name the behavioral lesson a rule came from;
  the write-ups behind them are intentionally not bundled — every operative rule is
  stated inline. Files under `.claude/rules/private/memory/` are the repo-fact
  reference corpus and ARE read directly.
- **Spec grounding:** `review-spec-conformance` grounds findings in the AdCP spec
  prose for the version the target repo pins, re-deriving the live version at run
  time rather than trusting a hardcoded pin.
- Reviews write optional reports to `.claude/reports/` (gitignored).
