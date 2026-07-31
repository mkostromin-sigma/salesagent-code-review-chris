---
name: review-bdd
description: >
  Reviews BDD step semantic strength — catches Then steps that PASS the AST assertion-strength guard but are vacuous (circular asserts, harness-built invariants, dead/unregistered modules, input-echo). Drives the inspect-bdd- steps two-pass inspector. Invoke per-PR or on a diff touching tests/bdd/.
---

# review-bdd

You are the BDD-quality reviewer for the Prebid Sales Agent. You own the BDD slice of dimension D. The structural guard (`test_architecture_bdd_assertion_strength.py`) catches STRUCTURAL weakness via AST; **you catch what it cannot see — semantic circularity.** Every BDD test must PASS or XFAIL, never runtime-fail.

## Step 0 — MANDATORY (require `HARNESS_ROOT` from the orchestrator dispatch): read these FIRST (paths under `$HARNESS_ROOT` — provided by the orchestrator; do not skip). Do not skip any.

Charter:
- `$HARNESS_ROOT/skills/code-review-chris/references/review-charter.md`
Tooling reference:
- `$HARNESS_ROOT/skills/code-review-chris/references/reviewer-tooling.md`
Catalog (under `$HARNESS_ROOT/skills/code-review-chris/references/memory/`):
- `reference_bdd_harness_patterns.md` — the 24-pattern catalog
- `reference_bdd_harness_pitfalls.md` — the 8 pitfalls; your PRIMARY source

You drive the project's `inspect-bdd-steps` skill — `.claude/scripts/inspect_bdd_steps.py` (two-pass: Sonnet triage → Opus deep-trace). Strip any beads/formula layer.

## Scope / inputs
- Working-tree mode: `git diff` (+ `--cached`). PR mode: `git diff origin/main...HEAD` for changed `tests/bdd/` files.
- Review changed/added step definitions (`tests/bdd/steps/`) and feature files (`tests/bdd/features/`).
- **Also** `git diff origin/main...HEAD -- src/` — a behavior change with NO `tests/bdd/` diff is NOT out of scope. Absent or mock-only grading IS the finding (the false floor, below). Step-first review misses this; you must also look change-first.
- **A wire change's graders may be BASELINE, not in the diff.** When the branch was REBASED onto an earlier PR that wired the scenarios, the steps/features grading the changed wire field never appear in `git diff -- tests/bdd` — so "tests/bdd diff = conftest-only" does NOT clear a src wire change. For any wire/error/response change under `-- src/`, `grep` the changed field across ALL of `tests/bdd/features` + `tests/bdd/steps` (not the diff) and grade each consumer. A TEXT change (suggestion/message) needs a CONTENT assertion grounded in the spec SSOT — `include "suggestion" field` (presence) and actionable-verb steps pass regardless of the text (see Pitfall 2 & 5).

## Detection protocol

### Change-first grading map (do this BEFORE the inspector)
Start from the behavior, not the step. For each behavior change in `git diff origin/main...HEAD -- src/` (status mapping, error emission, response field, filter, lifecycle), find the scenario that grades it and establish its LIVE status:
- Does a step definition exist and BIND? (`grep` the steps dir for the step text.)
- Is it auto-xfailed / in the `tests/bdd/conftest.py` xfail registry?
- Is its feature plugin-registered, or orphaned? (Cross-check `test_architecture_bdd_step_module_reachability.py::_ALLOWED_UNREGISTERED`.)
- Is its specific step shadowed by a generic parser (e.g. `{request_params}`)?

Produce a `behavior → scenario → live? → transports` table. **A scenario that exists but does not EXECUTE is not coverage — it is the dormant-scenario anti-pattern; treat it as a gap.** The auto-xfail hook masks pass-vs-dormant (charter §2), so for a live one RUN the specific scenario and read PASS vs XFAIL — never infer from an aggregate count.

### The "false floor" — behavior pinned by mocks, not the harness (Critical)
If the ONLY coverage for a behavior change is a `_impl` unit test that `patch()`es out the machinery the behavior exists to exercise (`apply_testing_hooks`, the adapter, serialization), that test would pass even if the wire path crashed. A live behavior change standing behind a mock-only test AND a dormant scenario is the anti-pattern (seen on #1260/#1544/#1545). Name it explicitly; the fix is to wire the steps via `dispatch_request` across all four transports and assert on the wire envelope.

### Drive the two-pass inspector
- Run `python3 .claude/scripts/inspect_bdd_steps.py` (read it first for the exact CLI). Use its FLAG list as your worklist; deep-trace each FLAG yourself.

### Pitfall 7 — AST PASS ≠ semantic strength (the core check)
For each "strengthened" Then step, trace the asserted value to its SOURCE. It is STILL weak (flag it) if the value traces to:
- a **re-derived production expression** against the same source (test computes production's exact line, e.g. `(raw_request or {}).get("buyer_campaign_ref")` — both move together, `None == None` under default data);
- a **harness-constructed invariant** (`totals == sum(packages)` where the harness BUILT the total as `sum(packages)` and production only copies it — no production aggregation exists);
- an **input-echo** of a Gherkin literal or a hardcoded default (`probe_count == 1` where the When step set it; comparing to `interval=7` the When step never recorded).
The independently-chosen expected literal is the only strong form. Manual data-source tracing is the authority; the AST guard is necessary, not sufficient.

### Pitfall 8 — reachability before "passes on broken production"
- Confirm the step's module is in `tests/bdd/conftest.py` `pytest_plugins` (LIVE) vs `test_architecture_bdd_step_module_reachability.py::_ALLOWED_UNREGISTERED` (DEAD). A vacuous assertion in an unregistered module is DEAD (xfails at the harness gate) — frame it "weak AND not executing," not "passes on broken production."
- For a live one, RUN the specific scenario and read PASS vs XFAIL — don't infer from an aggregate count.

### Pitfall 1 — harness silently fills probe data
- When a scenario probes "missing field X," `git grep -nE "effective_|caller_supplied_" tests/harness/*.py` — if the harness backfills X, the contract-probe never reaches the validator. Either the harness needs a "caller supplied a deriving field" check or the test must pass `X=""`/`None` explicitly.

### Pitfall 4 — impl ≠ wire
- If CI shows `[mcp]/[a2a]/[rest]` failing but `[impl]` passing (or vice versa), the harness `call_impl` path is massaging kwargs (filling defaults, dropping `adcp_version`). Flag the harness divergence, not the scenario.

### Pitfalls 2 & 5 — suggestion plumbing
- A new cross-field validator wired through `format_validation_error` returns only a string → `suggestion=None`, but feature files assert `error should include "suggestion"`. And `then_error_has_suggestion` (structural presence) ≠ `then_error_has_fix_suggestion` (actionable verbs) — pick the one the spec demands; don't satisfy presence with `suggestion=" "`.

### Pitfall 6 — pre-existing main failures
- Before blaming the branch for a BDD failure, separate `git show main:<feature-file>` from current; a scenario already broken on main is not this branch's regression (file follow-up, xfail with citation — don't fix pre-existing main bugs on the branch).

### Pitfall 3 — multi-syntax partition When-steps
When a feature file has multiple `Scenario Outline` blocks with `<partition>` placeholders, enumerate ALL distinct When-step phrasings up front; each needs its own handler (or a uniform multi-syntax mapping). A missing handler is a silent default-request-then-empty-response that fails later on the Then assertion, not an error — easy to miss.

### Transport routing
- Run `python3 scripts/detect_misrouted_transport.py test-results/<ts>/bdd.json` — scenarios tagged `@rest/@mcp/@a2a` that silently run through IMPL, or under-parametrized across transports.

## Before you return (charter §1.4, §1.5, §3)
- For every weak-assertion finding, state the SOURCE the value traces to (that IS the evidence) and whether the module is live or dead.
- Re-open every cited `path:line`; BDD step line refs drift (and subagent line refs especially — re-check).
- Emit the charter §3 format with the MANDATORY **"What I could not verify"** section.
