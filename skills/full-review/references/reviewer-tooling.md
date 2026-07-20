# Reviewer Tooling Reference — detection commands & masking-gotcha recipes

Companion to `review-charter.md` (its §2 cites this file). Every recipe below is point-in-time — verified against the codebase when written; if an infra-reshaping PR has merged since, re-verify against the current code before relying on a recipe.

## A. Suite verdict — never the terminal tail
- Authoritative record: per-suite JSON. `ls -dt test-results/*/ | head -1` → parse each `{unit,integration,e2e,admin,bdd}.json` `summary`; enumerate any test whose outcome ∉ {passed, skipped, xfailed, xpassed}.
- tox prints its own `congratulations :)` banner whenever ITS envs exit 0 — the coverage env succeeds if coverage data exists, regardless of suite failures. `run_all_tests.sh`'s final `ALL PASSED`/`FAILED:` line is computed from the JSON, but read the JSON yourself anyway.
- `make quality` = unit-only + OFFLINE: skips tests/harness, tests/admin, tests/e2e, live integration, network-gated schema-alignment tests, and the security audit. Authoritative local gate: `./run_all_tests.sh ci`.
- CI does NOT run `tests/admin/`, and its unit job omits `tests/harness/` — a green PR rollup ≠ suite green.

## B. Run provenance — assert the tree before trusting any run
```bash
git checkout -- .duplication-baseline   # make quality dirties it; discard BEFORE switching
git checkout <branch>
git rev-parse --short HEAD              # MUST equal the expected SHA — ABORT on mismatch
git status --porcelain                  # MUST be empty
```
Identical test counts across "different" branches = wrong-tree tell.

## C. agent-db / integration infra
- A WALL of identical `connection refused` ERRORs = infra, not test failures (and not passes — the tests never ran). The historical hardcoded-port bug is RESOLVED (dynamic `find_port` 50000-60000, per-worktree containers), but a stale `eval` can still desync the env: re-run `eval $(.claude/skills/agent-db/agent-db.sh up)`; truth is `docker ps --format '{{.Names}}\t{{.Ports}}' | grep agent-pg`.
- Persistent agent-db accumulates schema → moved/new integration tests can pass locally and fail fresh-CI (`UndefinedTable`). Verify them on a FRESH DB.
- Non-reproducing DB failures while a background full run is active → prove with a serial re-run before calling regression.
- `timeout` is often not installed on macOS — don't wrap test commands in it.

## D. git/commit false-greens
- A backgrounded compound command reports the LAST stage's exit. Verify `git rev-parse HEAD` advanced + `git status` clean — never the task's exit code.
- Commit aborts with "files were modified by this hook" + ` M uv.lock` → a uv-run hook re-resolved the lock: `git checkout origin/main -- uv.lock && UV_FROZEN=1 git commit ...`. (No black hook exists since #1370; the sole formatter hook is ruff-format running from uv.lock.)
- After `git mv` + content edits: `git diff --cached --stat` MUST show real insertions/deletions — a "100% rename, 0 insertions/0 deletions" means a later `git add` was aborted and the content never staged.
- CI "not running" after a push → `gh pr view N --json mergeable,mergeStateStatus` — DIRTY/CONFLICTING silently skips `pull_request` workflows (`pull_request_target` ones still run).
- Phantom import/mypy errors after branch switches → verify the env first (`uv run python -c "import <suspect>"`); repair with `uv sync --reinstall`.

## E. Static-analysis blind spots
- ruff config IGNORES F821 (missing imports) and selects no C901/PLR09xx — verify imports by usage-grep; probe complexity with targeted `ruff check --select C90,PLR091 --statistics` runs.
- tox 4 execs `commands` as argv with NO shell — `$(...)`/`<`/`|` are literal tokens. Verify any tox.ini line by RUNNING the env, or `tox config -e <env> -k commands`.
- Line-keyed guard allowlists break on ANY line-count change in a covered file — re-derive AFTER formatting converges; run the owning guard locally before judging.

## F. Review evidence commands
- Commenter inventory FIRST (no author filter): `gh api repos/O/R/pulls/N/reviews`, `.../pulls/N/comments`, `.../issues/N/comments` (+ GraphQL `reviewThreads` for `isResolved`/`isOutdated`).
- Provenance before "pre-existing": `git log -G'<regex>' $(git merge-base origin/main HEAD)..HEAD -- <paths>` (empty = untouched by the PR) + byte-identical site-set diff (grep at base vs head, strip line numbers, sort, diff) + `git blame` to the introducing commit.
- Guard verdicts: rebase the PR onto target main + `make quality` — the guard prints surviving violations. Static counting = triage only.
- Production reachability of a symbol: `git grep "<name>(" src/` (open paren finds call sites, not imports).
- Advisory-on-success allowlist sites: `grep -rn "structural-guard: advisory per" src/` (count drifts; the marker is the source of truth).
- Wire-envelope assertions: `assert_envelope_shape(target, code, *, recovery, message_substr=None, check_mcp_tool_error=False)` from `tests/helpers/envelope_assertions.py` — `recovery` REQUIRED; no `check_backward_compat`; no `field` param.

## G. AST queries
- ast-grep is configured (`sgconfig.yml` at repo root, `.ast-grep/rules/`); agent-index `.pyi` stubs are present for live queries.
- One-off structural search: `ast-grep run -p '<pattern>' src/` ; rule-form: `ast-grep scan --inline-rules '<yaml rule>'` — prefer over regex-grep when matching call shapes (e.g. `Error(code=$_)`, `session.add($_)`) so string/comment hits don't pollute counts.

## H. Worktree hygiene (reviewing inside an isolated checkout)
When you review in a git worktree — a Cursor isolated worktree / `best-of-n-runner` checkout or an orchestrator-provisioned sibling (`../salesagent-wt-prN`) — three things bite; all three have surfaced live during a single multi-agent PR re-review.
- **The Read tool can serve MAIN-checkout content, not your worktree's** (charter §2, gotcha 9). `git rev-parse HEAD` showing the PR head does NOT guarantee Read follows it. → Cite from `git show HEAD:<path>` or `git grep <re> <sha>`; before trusting any bare Read, grep a **sentinel** line you KNOW the PR changed and confirm it's present. If it isn't, you're reading the wrong tree — stop and use `git show`.
- **Detectors are NOT in your worktree** — they live in the harness plugin, so a salesagent-relative path 404s. Invoke by ABSOLUTE harness path with cwd = the tree to scan: `cd <worktree> && python3 $HARNESS_ROOT/skills/full-review/scripts/X.py src` (or pass explicit file args). `citation_freshness` scans correctly from a worktree path (its `SKIP_DIRS` skip is relative-to-root, and a file-arg root is honored); the `recovery_audit`/`sdk_spec_drift` snapshots hard-fail if the adcp pin ≠ their pinned spec version — re-transcribe on a bump (refresh cmd in each detector's docstring; `bump_check.py` is the one-command drill).
- **Tear down your agent-db before returning** — `.claude/skills/agent-db/agent-db.sh down` in the **salesagent** checkout (or the orchestrator sweeps leftover `agent-pg-*` containers at the end). A left-running container holds a port for the rest of the run.
