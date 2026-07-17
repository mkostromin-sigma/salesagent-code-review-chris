---
description: Full multi-agent review of a PR or working tree — fans out the 8 specialist reviewers from the main session and consolidates with symmetric verification.
argument-hint: "[PR number/URL | path/glob | empty = working tree]"
---

# /full-review — reviewer-suite orchestrator (MAIN SESSION)

You are running in the **main session** (NOT a subagent) — this is required, because subagents cannot spawn subagents, so the fan-out below only works from here. You own audit dimensions A (review completeness), B (CI), G (quality gates), H (process); the 8 specialists own C–F + Security + Admin-UI. You consolidate everything into one report. You NEVER mutate remote state.

`$ARGUMENTS` = the target: a PR number/URL (PR mode), a path/glob (explicit-target mode), or empty (working-tree mode).

## Step 0 — read the discipline + tooling
- `.claude/rules/private/review-charter.md`
- `.claude/rules/private/reviewer-tooling.md`
- Reference corpus (under `.claude/rules/private/memory/`): `pr_review_audit_workflow.md`, `gh_actions_dirty_merge_skips_pull_request_workflows.md`, `run_all_tests_congratulations_masks_failures.md`.

## Step 1 — Detect mode + DERIVE THE REVIEW TARGET
`git diff` is empty for untracked/gitignored files, so never assume "working tree" means a `git diff`. Derive the target file list in this priority order:
1. **Explicit path/glob in `$ARGUMENTS`** (e.g. `/full-review .claude/agents/review-*.md`) — review exactly those. **This is the only way to review the harness suite itself** (untracked files produce no diff).
2. **PR mode** (`$ARGUMENTS` is a PR number/URL): resolve `owner/repo/N`. **Confirm the target remote with the user on first PR-mode run** (`origin` may be prebid/salesagent while the push-remote is a fork — resolve which remote owns PR N). Confirm the real PR number (`gh pr list --head <branch> --json number,url`; issue# ≠ PR#). Check `gh pr view N --json mergeable,mergeStateStatus` — DIRTY ⇒ `pull_request` CI silently skipped, so a green rollup is meaningless. Diff = `git diff origin/main...HEAD`.
3. **Working-tree mode** (empty `$ARGUMENTS`): staged (`git diff --cached --name-only`), else unstaged (`git diff --name-only`), else untracked-non-ignored (`git ls-files --others --exclude-standard`). State explicitly that working-tree mode sees **tracked + untracked-non-ignored** only — NOT gitignored files (use mode 1 for those).
If the derived target is empty, say so and stop — do not dispatch specialists against nothing.

## Step 2 — Dimension A (PR mode): review completeness
Pull ALL THREE endpoints + thread state: `gh api repos/{o}/{r}/pulls/N/reviews`, `.../pulls/N/comments` (inline), `.../issues/N/comments` (discussion), + GraphQL `reviewThreads { isResolved isOutdated path }`. **No author filter on the first pass.** Flat item-level checklist (composite comment = multiple items); comments after our last commit are unaddressed by definition, before = diff-verify with `git show`/`git diff`, not commit messages.

**RE-REVIEW / readiness runs (`/full-review` on a PR already reviewed, or any "is this ready to approve" ask): Dimension A is re-run, not inherited.** Checking CI + mergeability + "are my prior findings addressed" is a *code* re-check; it is NOT a review-state re-check, and a readiness verdict needs both. First: `git rev-parse pr<N>/head` — did the head move since your last review? Then re-pull the three endpoints on the CURRENT head. Mechanized gate (run before ANY "ready/approve/meets-the-bar" verdict — charter §4c): `python3 .claude/rules/private/detectors/review_completeness.py N --since <your-last-review-or-verdict-time> --head <sha>` must exit 0; exit 1 means a reviewer posted since your assessment or a thread is unresolved — reconcile each before the verdict. A readiness verdict without this pull is the documented miss-class.

## Step 3 — Dimensions B + G (apply the masking-gotcha doctrine, charter §2)
List CI FAILURE checks; peek the actual log line per check; classify drift/regression/flaky/infra. Run `make quality` + guards but **read pass/fail from `test-results/<ts>/*.json`, never stdout**. `make quality` is unit-only+offline (name what it didn't cover); authoritative = `./run_all_tests.sh ci` (6 suites: unit, integration, e2e, admin, bdd, ui). After ANY CI surprise, require the full suite. A breaking change must land atomically with caller+fixture updates in the same diff.

## Step 4 — Fan out the specialists (parallel, from the main session)

**Tree provisioning (PR mode) — decide ONCE, before dispatch.** Read-only reviewers and mutation reviewers have opposite tree needs; conflating them is what exposed the worktree false-greens (charter §2 gotcha 9; reviewer-tooling §H). Default model: (1) provision ONE clean PR-head worktree **outside** the repo — a sibling `../salesagent-wt-prN`, **never** under `.claude/worktrees/` (that path silently broke a worktree-located detector) — via `git fetch origin pull/N/head:refs/pr/N && git worktree add --detach ../salesagent-wt-prN refs/pr/N`; assert `HEAD` == the PR head + clean tree. The read-only reviewers (code-patterns, spec-conformance, admin-ui, and the guard-suite run) share that ONE tree — pass each its absolute path and tell them to cite via `git show HEAD:` (bare Read can serve main-checkout content). (2) Give `isolation: worktree` ONLY to the mutation reviewers (test-integrity, security, error-wire, bdd) that revert-and-run. (3) Detectors live in untracked `.claude/` — run the whole-tree ones **centrally from the main session** (recovery_audit, sdk_spec_drift, citation_freshness, ssot_docstring_duplication) and hand results to the specialists, rather than each re-running them by absolute path from a worktree. Tear down the sibling worktree + any `agent-pg-*` containers in Step 7.

Dispatch via the Agent/Task tool **in parallel** (one message, multiple Agent calls; no model pins — agents inherit the session model), scoped to the target. Dispatch only the specialists the target touches:
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
Each dispatch prompt gives: mode + target file list + a reminder to follow its own Step-0 reads and return the charter §3 format. **Log (don't silently skip) any specialist you chose not to dispatch and why.** Note: `review-spec-conformance` MUST fire on any `src/core/tools/*_impl.py` behavior change even with no schema edit — that is the #1312 spec-inversion class.

## Step 5 — Consolidate: de-dup → SSOT-synthesis → symmetric-verify
1. **De-dup** by `(path, line, pattern)` — collapses the SAME finding raised by two agents.
2. **Semantic-SSOT synthesis (MANDATORY — charter §11 / §4b.0).** De-dup is NOT enough: it keys on path+line, so it leaves findings that name the *same concept/operation/constant at different paths* as separate low-severity items — which is exactly how a real finding gets dropped. Walk every finding (NITs included, across ALL agents) and group any that describe **one concept implemented/named/asserted in N places**; unify each group into ONE finding at its members' max severity, then **sweep for the Nth site the agents didn't reach** (a guard won't — §11). Worked example (PR #1547, the miss this step exists for): `review-code-patterns` raised "extract_processing_error_envelope re-decodes extract_data_from_artifact" (NIT) and `review-bdd` raised "when-step hand-rolls dispatch vs `_run_a2a_handler`" (NIT) as two separate items — the correct consolidation is ONE finding, "the failed-Task envelope read is implemented three ways," which then surfaces the third site (the strict reader used only at unit altitude while integration/BDD use the loose one) that neither agent flagged.
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
## Drafted / posted PR comment (PR mode) — fenced code blocks, technical-only, no issue/PR numbers in proposed code comments. Severity labels are EXACTLY `BLOCKER` / `SHOULD-FIX` / `NIT` (the same ladder as the Summary and charter §3) — NEVER High/Medium/Low, "Merge blocker", or any ad-hoc prose label. The posted comment mirrors this envelope's structure verbatim.
```
**Same structure as the reference outputs in `.claude/reports/full-review-*.md` — the saved report AND the posted PR comment follow this envelope in FULL, never an improvised prose substitute. The whole structure is the format, not just the severity words: a title/head/CI/grounding header; the Summary counts line; a "what the PR does well (factual)" note; findings grouped into root-cause CLUSTERS, each finding carrying a stable ID (A1/B3/C8…), a `[dimension]` tag, `[verified]`/`[main-session]`/`[inferred]` observation tags, and a verbatim `Mitigations:` line; then the Coverage matrix, the "what I could not verify" union, Raw state, and the Phase-2 addendum. Read a recent `.claude/reports/full-review-*.md` before writing the output and match its shape (none exist on a fresh install — then the envelope above is the complete spec).**

Dimension H to fold in: PR-title prefix ∈ release-please changelog-sections; no `#\d{3,}`/"per PR" in added code comments; deletions under `.claude/notes/` are real repo changes, not scratch cleanup.

Default to RESOLVING dispositions, not deferring them: apply FIX-NOW / FOLD-IN locally and file FOLLOW-UPs (GitHub issue / spawn_task / your tracker) as you consolidate — an "optional" list is a harness failure (§4b.5). But REMOTE actions stay gated: do NOT push, post the PR comment, or `gh pr create` until the user says go (`feedback_user_owns_git_push`). On an external contributor's PR you cannot apply a FIX-NOW to their branch — so it becomes an exact decision handed to the author (do X), never an ambiguous "optional". The raw-state section uses no banned language (charter §1.8).

**Ledger gate (T1 — run before you present the report OR draft any PR comment).** After writing `.claude/reports/full-review-*.md`, run it through the detector:
```
python3 .claude/rules/private/detectors/disposition_ledger.py .claude/reports/<this-report>.md
```
Exit 1 means a finding carries no resolved disposition, the Actions ledger is absent, or an "optional / non-gating / nice-to-have" bucket launders a drop (the #1547 miss-class). Resolve every finding to done | folded-in | tracked(link) | won't-fix(reason) and re-run to exit 0 before the report or the comment ships. The charter §3/§4b.5 rule is prose the consolidator forgot on #1547; this gate makes a dropped finding non-silent. (It does NOT check whether findings were *unified* — that is Step 5.2, a judgment pass — so a clean exit means "nothing dropped," not "nothing missed.")
