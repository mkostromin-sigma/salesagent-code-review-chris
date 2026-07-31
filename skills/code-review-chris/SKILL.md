---
name: code-review-chris
description: >-
  Full multi-agent review of a Prebid Sales Agent PR or working tree. Fans out
  eight specialist Cursor agents (code-patterns, error-wire, architecture-guards,
  test-integrity, bdd, spec-conformance, security, admin-ui), consolidates with
  symmetric verification and a disposition-ledger gate. Default output is
  chat-only — never post to GitHub unless the user explicitly opts in. Use when
  the user invokes /code-review-chris, asks for a full multi-agent review, or wants
  the salesagent review harness before push/merge.
disable-model-invocation: true
---

# /code-review-chris — reviewer-suite orchestrator (MAIN SESSION)

You are running in the **main session** (NOT a subagent) — this is required, because subagents cannot spawn subagents, so the fan-out below only works from here. You own audit dimensions A (review completeness), B (CI), G (quality gates), H (process); the 8 specialists own C–F + Security + Admin-UI. You consolidate everything into one report. You NEVER mutate remote state.

The review **target argument** is whatever the user passed after `/code-review-chris` or in the same message: a PR number/URL (PR mode), a path/glob (explicit-target mode), or empty (working-tree mode).

## Output destination (HARD GATE)

**Default: local chat only.** Deliver the full review report in the conversation. Do not publish anything to GitHub.

Never create, edit, submit, comment, approve, resolve, label, request reviewers, or otherwise mutate anything on GitHub unless the user explicitly opts in with a clear publish instruction in the same turn (examples: "post to GitHub", "comment on the PR", "publish findings"). Reviewing a PR, naming a PR number, or "ready for review" language is **not** permission to post.

You may **draft** PR-thread replies and **propose** fixes, but never apply remote mutations or push until the user says go.

## Step 0a — resolve HARNESS_ROOT

Before any other work, resolve the plugin root and fail loudly if assets are missing:

1. Prefer `~/.cursor/plugins/local/salesagent-review-harness` if it exists and contains `skills/code-review-chris/references/review-charter.md`.
2. Else, if this skill's files are reachable, take the directory two levels above `skills/code-review-chris/` (the plugin / git checkout root).
3. Else Glob for `review-charter.md` under known plugin/skill paths and derive the root from that hit.

Set `HARNESS_ROOT` to that absolute path. Verify these exist:

- `$HARNESS_ROOT/skills/code-review-chris/references/review-charter.md`
- `$HARNESS_ROOT/skills/code-review-chris/references/reviewer-tooling.md`
- `$HARNESS_ROOT/skills/code-review-chris/scripts/disposition_ledger.py`
- `$HARNESS_ROOT/agents/review-code-patterns.md`

If any are missing, stop and tell the user to run `./install.sh` from the harness repo.

Pass `HARNESS_ROOT=<abs>` in every specialist dispatch prompt.

## Step 0 — read the discipline + tooling

Read completely:

- `$HARNESS_ROOT/skills/code-review-chris/references/review-charter.md`
- `$HARNESS_ROOT/skills/code-review-chris/references/reviewer-tooling.md`
- Reference corpus under `$HARNESS_ROOT/skills/code-review-chris/references/memory/`: `pr_review_audit_workflow.md`, `gh_actions_dirty_merge_skips_pull_request_workflows.md`, `run_all_tests_congratulations_masks_failures.md`.

This harness reviews a **salesagent** working copy. Prefer `AGENTS.md` as the target repo source of truth; also read `CLAUDE.md` / `tests/CLAUDE.md` when present.

## Step 1 — Detect mode + DERIVE THE REVIEW TARGET

`git diff` is empty for untracked/gitignored files, so never assume "working tree" means a `git diff`. Derive the target file list in this priority order:

1. **Explicit path/glob in the user argument** (e.g. `/code-review-chris agents/review-*.md` or a salesagent path) — review exactly those. **This is the only way to review the harness suite itself** when those files produce no diff in salesagent.
2. **PR mode** (argument is a PR number/URL): resolve `owner/repo/N`. **Confirm the target remote with the user on first PR-mode run** (`origin` may be prebid/salesagent while the push-remote is a fork — resolve which remote owns PR N). Confirm the real PR number (`gh pr list --head <branch> --json number,url`; issue# ≠ PR#). Check `gh pr view N --json mergeable,mergeStateStatus` — DIRTY ⇒ `pull_request` CI silently skipped, so a green rollup is meaningless. Diff = `git diff origin/main...HEAD` (or `upstream/main...HEAD` when that is the real base).
3. **Working-tree mode** (empty argument): staged (`git diff --cached --name-only`), else unstaged (`git diff --name-only`), else untracked-non-ignored (`git ls-files --others --exclude-standard`). State explicitly that working-tree mode sees **tracked + untracked-non-ignored** only — NOT gitignored files (use mode 1 for those).

If the derived target is empty, say so and stop — do not dispatch specialists against nothing.

## Step 2 — Dimension A (PR mode): review completeness

Pull ALL THREE endpoints + thread state: `gh api repos/{o}/{r}/pulls/N/reviews`, `.../pulls/N/comments` (inline), `.../issues/N/comments` (discussion), + GraphQL `reviewThreads { isResolved isOutdated path }`. **No author filter on the first pass.** Flat item-level checklist (composite comment = multiple items); comments after our last commit are unaddressed by definition, before = diff-verify with `git show`/`git diff`, not commit messages.

**RE-REVIEW / readiness runs** (`/code-review-chris` on a PR already reviewed, or any "is this ready to approve" ask): Dimension A is re-run, not inherited. First: did the head move since your last review? Then re-pull the three endpoints on the CURRENT head. Mechanized gate (charter §4c):

```
python3 $HARNESS_ROOT/skills/code-review-chris/scripts/review_completeness.py N --since <your-last-review-or-verdict-time> --head <sha>
```

must exit 0; exit 1 means a reviewer posted since your assessment or a thread is unresolved — reconcile each before the verdict.

## Step 3 — Dimensions B + G (masking-gotcha doctrine, charter §2)

List CI FAILURE checks; peek the actual log line per check; classify drift/regression/flaky/infra. Run `make quality` + guards but **read pass/fail from `test-results/<ts>/*.json`, never stdout**. `make quality` is unit-only+offline (name what it didn't cover); authoritative = `./run_all_tests.sh ci` (6 suites: unit, integration, e2e, admin, bdd, ui). After ANY CI surprise, require the full suite. A breaking change must land atomically with caller+fixture updates in the same diff.

## Step 4 — Fan out the specialists (parallel, from the main session)

**Tree provisioning (PR mode) — decide ONCE, before dispatch.** Read-only reviewers and mutation reviewers have opposite tree needs; conflating them is what exposed the worktree false-greens (charter §2 gotcha 9; reviewer-tooling §H). Default model:

1. Provision ONE clean PR-head worktree **outside** the repo — a sibling `../salesagent-wt-prN` — via `git fetch <remote> pull/N/head:refs/pr/N && git worktree add --detach ../salesagent-wt-prN refs/pr/N`; assert `HEAD` == the PR head + clean tree. The read-only reviewers (code-patterns, spec-conformance, admin-ui, and the guard-suite run) share that ONE tree — pass each its absolute path and tell them to cite via `git show HEAD:` (bare Read can serve main-checkout content).
2. For mutation reviewers (test-integrity, security, error-wire, bdd) that revert-and-run: give each an isolated sibling worktree or a Cursor `best-of-n-runner` / isolated checkout — **never** Claude-style `isolation: worktree` flags. Do not put worktrees under paths that hide harness detectors.
3. Detectors live in `$HARNESS_ROOT/skills/code-review-chris/scripts/` — run the whole-tree ones **centrally from the main session** (`recovery_audit`, `sdk_spec_drift`, `citation_freshness`, `ssot_docstring_duplication`) and hand results to the specialists. Tear down sibling worktrees + any `agent-pg-*` containers in Step 7.

Dispatch via the **Task** tool **in parallel** (one message, multiple Task calls; no model pins — agents inherit the session model), with `subagent_type` set to the specialist name below. Dispatch only the specialists the target touches:

| Specialist (subagent_type) | Dispatch when the target includes |
|---|---|
| `review-code-patterns` | any `src/` Python (near-universal) |
| `review-error-wire` | error paths, dispatchers, adapters, transport boundaries, error tests |
| `review-architecture-guards` | `src/`, `tests/`, or `alembic/` (near-universal) |
| `review-test-integrity` | any `tests/` outside `tests/bdd/` |
| `review-bdd` | `tests/bdd/` |
| `review-spec-conformance` | `src/core/schemas/`, **`src/core/tools/` (AdCP tool _impls)**, error codes, or any protocol-behavior change |
| `review-security` | auth/identity/tenant/webhook/outbound-URL/admin-route code |
| `review-admin-ui` | `src/admin/`, `templates/`, `static/`, route decorators, or `docs/adapters/` |

Each dispatch prompt MUST include:

- `HARNESS_ROOT=<absolute path>`
- mode + target file list
- absolute path of any shared PR worktree
- reminder to follow its own Step-0 reads and return the charter §3 format

**Log (don't silently skip) any specialist you chose not to dispatch and why.** Note: `review-spec-conformance` MUST fire on any `src/core/tools/*_impl.py` behavior change even with no schema edit — that is the #1312 spec-inversion class.

## Step 5 — Consolidate: de-dup → SSOT-synthesis → symmetric-verify

1. **De-dup** by `(path, line, pattern)` — collapses the SAME finding raised by two agents.
2. **Semantic-SSOT synthesis (MANDATORY — charter §11 / §4b.0).** De-dup is NOT enough: it keys on path+line, so it leaves findings that name the *same concept/operation/constant at different paths* as separate low-severity items — which is exactly how a real finding gets dropped. Walk every finding (NITs included, across ALL agents) and group any that describe **one concept implemented/named/asserted in N places**; unify each group into ONE finding at its members' max severity, then **sweep for the Nth site the agents didn't reach** (a guard won't — §11). Worked example (PR #1547): `review-code-patterns` raised "extract_processing_error_envelope re-decodes extract_data_from_artifact" (NIT) and `review-bdd` raised "when-step hand-rolls dispatch vs `_run_a2a_handler`" (NIT) as two separate items — the correct consolidation is ONE finding, "the failed-Task envelope read is implemented three ways," which then surfaces the third site that neither agent flagged.
3. **Symmetric-verify.** Surface specialist disagreements rather than picking the more confident; spot-check both "found" findings (re-open the line) AND "clean" verdicts (sample claimed-scanned files). An empty result is a hypothesis, not "clean".

## Step 6 — Phase-2 audit (default ON for substrate / multi-fix targets)

Re-check Phase-1's consolidated output before trusting it (catches BLOCKERs the first pass introduced/missed). Skip only for a small single-purpose target, and say so.

## Step 7 — Report (charter §3 envelope)

```
# Review: <PR #N @ head-sha | target=<paths> @ SHA>
Diff range / target: <...>   mergeStateStatus: <...> (PR mode)
## Summary: <n> BLOCKER / <n> SHOULD-FIX / <n> NIT · specialists run: <list> · skipped: <list+why>
## Findings by severity (BLOCKER > SHOULD-FIX > NIT)   — de-duped, per-finding evidence + Disposition (§3)
## Actions (charter §4b.5) — every finding resolved: done | folded-in | tracked(issue/task link) | won't-fix(reason). NO "optional/non-blocking" bucket; default is do-the-work; deferral only for scope (→tracked) or correctness (→declined).
## Coverage matrix (dimension → owner → run?)
## Dimension A checklist (PR mode) — each reviewer item: addressed (diff proof) | unaddressed
## What I could not verify — union of all specialists' gaps + yours
## Raw state — origin head, local-only commits (git log @{u}..HEAD), CI's last verdict. NO "ready/clean/looks good".
## Drafted PR comment (PR mode) — fenced code blocks, technical-only, no issue/PR numbers in proposed code comments. Severity labels are EXACTLY `BLOCKER` / `SHOULD-FIX` / `NIT`. Do not post unless the user explicitly opted in.
```

**Same structure as reference outputs in `.cursor/reports/code-review-chris-*.md` when present** — the saved report AND any drafted PR comment follow this envelope in FULL. Read a recent `.cursor/reports/code-review-chris-*.md` before writing the output and match its shape (none exist on a fresh install — then the envelope above is the complete spec).

Dimension H to fold in: PR-title prefix ∈ release-please changelog-sections; no `#\d{3,}`/"per PR" in added code comments; deletions under salesagent `.claude/notes/` are real repo changes, not scratch cleanup.

Default to RESOLVING dispositions, not deferring them: apply FIX-NOW / FOLD-IN locally and file FOLLOW-UPs as you consolidate — an "optional" list is a harness failure (§4b.5). REMOTE actions stay gated: do NOT push, post the PR comment, or `gh pr create` until the user says go. On an external contributor's PR you cannot apply a FIX-NOW to their branch — so it becomes an exact decision handed to the author (do X), never an ambiguous "optional". The raw-state section uses no banned language (charter §1.8).

**Ledger gate (T1 — run before you present the report OR draft any PR comment).** After writing `.cursor/reports/code-review-chris-*.md` (create `.cursor/reports/` under the salesagent workspace if needed), run:

```
python3 $HARNESS_ROOT/skills/code-review-chris/scripts/disposition_ledger.py .cursor/reports/<this-report>.md
```

Exit 1 means a finding carries no resolved disposition, the Actions ledger is absent, or an "optional / non-gating / nice-to-have" bucket launders a drop (the #1547 miss-class). Resolve every finding to done | folded-in | tracked(link) | won't-fix(reason) and re-run to exit 0 before the report ships. (It does NOT check whether findings were *unified* — that is Step 5.2 — so a clean exit means "nothing dropped," not "nothing missed.")
