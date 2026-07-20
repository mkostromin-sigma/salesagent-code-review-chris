#!/usr/bin/env python3
"""review_completeness.py — the readiness-verdict gate (T1).

The miss this exists for: a re-review rendered "ready to approve / meets the bar"
WITHOUT re-pulling the PR's review threads on the current head. A reviewer then
posted a review with several valid should-fix items on the same head. The prose
rule (charter Dimension A: pull all three endpoints) was skipped in the re-review
path because the re-review only re-checked CI + the prior findings, not comments.

This makes the pull mechanical and the gate un-skippable: run it IMMEDIATELY
before ANY readiness/approve/"meets-the-bar" verdict. It inventories all three
GitHub review surfaces + the GraphQL review threads on the CURRENT head, newest
first, no author filter, and exits non-zero when there is reviewer activity you
have not demonstrably addressed.

Exit codes:
  0  — no reviewer activity newer than --since, no unresolved review threads, and
        the live head still equals --head (nothing landed after your assessment).
  1  — NEW activity since --since, and/or UNRESOLVED (not-outdated) threads exist,
        and/or the live head MOVED past --head (commits landed after your verdict —
        often reviewer-requested fold-ins — that you have not reviewed).
        → you have something to reconcile; a readiness verdict is premature.
  2  — usage / gh error (cannot confirm state → also not ready).

Usage:
  review_completeness.py <pr> [--repo O/R] [--since ISO8601|<sha>] [--head <sha>]

--since: the moment your assessment is anchored to (e.g. the timestamp of your
  last posted review, or your prior verdict). Anything newer is, by definition,
  unaddressed by that assessment. Accepts an ISO timestamp or a git SHA (whose
  committer date is used).  If omitted, only the unresolved-threads check gates.
--head: the head SHA your verdict is about. If the live PR head has moved past it,
  the gate FAILS (exit 1) and prints the unreviewed delta (the commits + file-stat
  between --head and the live head) — a readiness verdict is stamped to a head, and
  a fold-in you requested is still an unreviewed diff once it lands.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def _gh_json(args: list[str]) -> Any:
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        print(f"gh invocation failed: {exc}", file=sys.stderr)
        sys.exit(2)
    if out.returncode != 0:
        print(f"gh error: {out.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return json.loads(out.stdout or "null")


def _resolve_since(since: str | None) -> str | None:
    """Accept an ISO timestamp as-is; resolve a git SHA to its committer date."""
    if not since:
        return None
    if "T" in since and (since.endswith("Z") or "+" in since):
        return since
    # treat as a git SHA
    out = subprocess.run(
        ["git", "show", "-s", "--format=%cI", since], capture_output=True, text=True
    )
    if out.returncode != 0:
        print(f"could not resolve --since {since!r} as a SHA; pass an ISO timestamp", file=sys.stderr)
        sys.exit(2)
    return out.stdout.strip()


def _head_delta(stamped: str, live: str) -> str:
    """Render the commits + file-stat that landed between the stamped head and the
    live head — the diff a head-advance verdict must reckon with. Falls back to a
    fetch-and-diff instruction when the SHAs are not in the local clone."""
    rng = f"{stamped}..{live}"
    log = subprocess.run(["git", "log", "--oneline", rng], capture_output=True, text=True)
    if log.returncode != 0:
        return (f"    (cannot diff {rng} locally — fetch the PR head, then:\n"
                f"       git log --oneline {rng} && git diff --stat {rng})")
    stat = subprocess.run(["git", "diff", "--stat", rng], capture_output=True, text=True)
    commits = log.stdout.strip() or "(no commits in range — force-push or rebase? re-fetch and re-check)"
    lines = [f"      {ln}" for ln in commits.splitlines()]
    lines += ["    files changed:"] + [f"      {ln}" for ln in stat.stdout.strip().splitlines()]
    return "    commits landed after your stamp:\n" + "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pr", type=int)
    ap.add_argument("--repo", default="prebid/salesagent")
    ap.add_argument("--since", default=None)
    ap.add_argument("--head", default=None, help="the head SHA your verdict is about")
    args = ap.parse_args()

    since = _resolve_since(args.since)
    repo = args.repo
    pr = args.pr

    live_head = _gh_json(["pr", "view", str(pr), "--repo", repo, "--json", "headRefOid"]).get("headRefOid")
    reviews = _gh_json(["api", f"repos/{repo}/pulls/{pr}/reviews", "--paginate"]) or []
    inline = _gh_json(["api", f"repos/{repo}/pulls/{pr}/comments?per_page=100", "--paginate"]) or []
    issue = _gh_json(["api", f"repos/{repo}/issues/{pr}/comments?per_page=100", "--paginate"]) or []

    threads_q = (
        '{ repository(owner:"%s", name:"%s"){ pullRequest(number:%d){'
        ' reviewThreads(first:100){ nodes{ isResolved isOutdated path'
        ' comments(first:1){ nodes{ author{login} createdAt } } } } } } }'
        % (repo.split("/")[0], repo.split("/")[1], pr)
    )
    threads_raw = _gh_json(["api", "graphql", "-f", f"query={threads_q}"])
    threads = (
        threads_raw.get("data", {}).get("repository", {}).get("pullRequest", {})
        .get("reviewThreads", {}).get("nodes", [])
        if isinstance(threads_raw, dict) else []
    )

    events: list[tuple[str, str, str, str]] = []
    for r in reviews:
        if r.get("state") == "PENDING":
            continue
        events.append((r.get("submitted_at", ""), "REVIEW", r.get("user", {}).get("login", "?"),
                       f"[{r.get('state')}]"))
    for c in inline:
        events.append((c.get("created_at", ""), "INLINE", c.get("user", {}).get("login", "?"),
                       f"{c.get('path')}:{c.get('line') or c.get('original_line')}"))
    for c in issue:
        events.append((c.get("created_at", ""), "PR-COMMENT", c.get("user", {}).get("login", "?"), ""))
    events.sort()

    print(f"review-completeness — {repo}#{pr}")
    print(f"live head: {live_head}")
    print(f"since: {since or '(none — only unresolved-threads gate applies)'}")
    print(f"activity: {len(events)} events across reviews/inline/discussion\n")

    head_moved = bool(args.head and live_head and args.head not in (live_head, live_head[: len(args.head)]))
    newer = [e for e in events if since and e[0] > since]
    unresolved = [t for t in threads if not t.get("isResolved") and not t.get("isOutdated")]

    if events:
        print("newest 8 events:")
        for ts, kind, who, extra in events[-8:]:
            mark = "  ← NEW" if (since and ts > since) else ""
            print(f"  {ts} {kind:11} @{who} {extra}{mark}")
        print()

    fail = False
    if head_moved:
        fail = True
        print(f"✗ HEAD MOVED past your stamp: verdict is about {args.head}, live head is {live_head}. "
              "A readiness verdict is stamped to a head; the commits below landed AFTER it and are "
              "UNREVIEWED (reviewer-requested fold-ins count) — audit this delta before any verdict:")
        print(_head_delta(args.head, live_head))
    if newer:
        fail = True
        authors = sorted({e[2] for e in newer})
        print(f"✗ {len(newer)} event(s) NEWER than --since (by {', '.join('@' + a for a in authors)}) "
              "— unaddressed by your assessment; reconcile each before a readiness verdict.")
    if unresolved:
        fail = True
        print(f"✗ {len(unresolved)} UNRESOLVED review thread(s) (not resolved, not outdated):")
        for t in unresolved[:12]:
            c = (t.get("comments", {}).get("nodes") or [{}])[0]
            print(f"    {t.get('path')}  last @{c.get('author', {}).get('login', '?')} {c.get('createdAt', '')}")

    if fail:
        print("\nNOT READY: reconcile every new/unresolved reviewer thread (diff-verify each is "
              "addressed at the current head), or answer it, before claiming ready/approve.")
        return 1

    print("No reviewer activity newer than --since and no unresolved threads. "
          "(Necessary, not sufficient — the code-quality preconditions still apply.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
