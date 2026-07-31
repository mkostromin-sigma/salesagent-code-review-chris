# salesagent review harness

A multi-agent pull-request review harness for the [Prebid Sales Agent](https://github.com/prebid/salesagent)
(the AdCP sales-agent reference implementation). It fans out eight specialist
Cursor agents from one orchestrator skill, each grounded in a shared review charter
and a bundled corpus of behavioral memory, and consolidates their findings with
symmetric verification.

This repository is a **Cursor plugin**. It does not run standalone — open a
salesagent working copy as the workspace, then invoke `/code-review-chris`. The agents
reference that repo's `AGENTS.md` / `CLAUDE.md`, `src/`, `tests/`, structural guards,
and salesagent skills (`verify-spec`, `inspect-bdd-steps`, `guard`).

## What's in it

| Layer | Path | Role |
|---|---|---|
| Orchestrator | `skills/code-review-chris/SKILL.md` | `/code-review-chris` — runs in the main session, derives the review target, fans out specialists, consolidates. Owns audit dimensions A (review completeness), B (CI), G (quality gates), H (process). |
| Command alias | `commands/code-review-chris.md` | Thin `/code-review-chris` entry that delegates to the skill. |
| Specialists (8) | `agents/review-*.md` | One reviewer per surface: `code-patterns`, `error-wire`, `architecture-guards`, `test-integrity`, `bdd`, `spec-conformance`, `security`, `admin-ui`. |
| Discipline | `skills/code-review-chris/references/review-charter.md` | The non-negotiable operating rules, the masking-gotcha doctrine, and the finding/report format. Step-0 read for every agent. |
| Tooling | `skills/code-review-chris/references/reviewer-tooling.md` | Detection commands and false-green recipes the charter cites. |
| Detectors (10) | `skills/code-review-chris/scripts/*.py` | Mechanized gates: disposition ledger, review completeness, spec-citation freshness, recovery audit, SDK-vs-spec drift, SSOT/duplication, import cycles, FIXME format, suggestion audit, and `bump_check.py`. Each ships a `--selftest` mode. |
| Reference corpus | `skills/code-review-chris/references/memory/*.md` | Repo-fact reference files — P1–P42 catalog, wire-envelope policy, BDD harness patterns/pitfalls, AdCP spec-grounding guides, and test-infra gotchas. |

## Requirements

- [Cursor](https://cursor.com) — agents, skills, and `/code-review-chris` are Cursor constructs.
- A local [salesagent](https://github.com/prebid/salesagent) working copy to review (open it as the workspace).
- `gh` CLI for PR-mode reviews (also used by the `review_completeness` detector).
- Python 3.10+ for the detectors (stdlib only). `recovery_audit` and `sdk_spec_drift`
  introspect the installed `adcp` SDK, so run those two via `uv run python` from the
  salesagent repo root; their spec snapshots are pinned to the repo's `adcp` version and
  hard-fail with instructions when the pin moves (`bump_check.py` is the refresh drill).

## Install

From this harness repository:

```bash
./install.sh
```

This symlinks the checkout to `~/.cursor/plugins/local/salesagent-review-harness`
so Cursor discovers the plugin (skills, agents, commands). **Reload Cursor** afterward
(or open Customize → Plugins).

This is a **Cursor plugin**, not a personal skill. It will **not** appear under
`~/.cursor/skills/` — look in `~/.cursor/plugins/local/` instead. A personal skill
is a single `SKILL.md` folder; this harness also ships 8 agents, detectors, and a
command, which Cursor loads together only from a plugin.

The orchestrator resolves `HARNESS_ROOT` automatically (the plugin symlink path).
Detectors and references are read from the plugin; the salesagent tree remains the
code under review.

## Use

Open a **salesagent** working copy as the Cursor workspace (not this harness repo).
Then invoke **`/code-review-chris` explicitly** — the skill sets
`disable-model-invocation: true`, so Cursor will not auto-start it from ambient
chat; you must type `/code-review-chris` (or clearly ask to run the code-review-chris skill).

```
/code-review-chris 1399                                              # PR by number
/code-review-chris https://github.com/prebid/salesagent/pull/1399    # PR by full URL
/code-review-chris src/core/tools/                                   # explicit path/glob
/code-review-chris                                                   # current working tree
```

| You want… | Invoke |
|---|---|
| Review a PR (first pass or re-review) | `/code-review-chris <N>` or `/code-review-chris <PR URL>` |
| Review only some paths | `/code-review-chris <path/glob>` |
| Review uncommitted local changes | `/code-review-chris` |

Do **not** invoke the eight `review-*` agents yourself for a normal run — the
orchestrator fans them out via Task. Specialists are for the harness to dispatch.

The orchestrator detects the mode, dispatches only the specialists the target
touches, consolidates with de-duplication and symmetric verification, and produces
one report. **Default is chat-only** — it drafts PR-thread replies but never posts
them, and proposes fixes but never applies remote mutations, unless you explicitly
opt in (e.g. “post to GitHub” / “comment on the PR”).

Optional reports land under `.cursor/reports/` in the salesagent workspace
(gitignored locally; add that path to salesagent's `.gitignore` if needed).

## Related

A lighter complementary Cursor skill, `salesagent-dual-review` (two independent
systemic/adversarial lenses), is **not** bundled here — this plugin is the
eight-specialist full harness.

## Notes

- **Pattern IDs:** bracketed citations in the charter and agents (e.g.
  `feedback_verify_before_asserting`) name the behavioral lesson a rule came from;
  the write-ups behind them are intentionally not bundled — every operative rule is
  stated inline. Files under `skills/code-review-chris/references/memory/` are the
  repo-fact reference corpus and ARE read directly.
- **Spec grounding:** `review-spec-conformance` grounds findings in the AdCP spec
  prose for the version the target repo pins, re-deriving the live version at run
  time rather than trusting a hardcoded pin.
- **Plugin layout:** see [Cursor Plugins](https://cursor.com/docs/plugins) —
  `.cursor-plugin/plugin.json` plus `skills/`, `agents/`, and `commands/`.
