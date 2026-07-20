#!/usr/bin/env python3
"""FIXME-format detector — reviewer-tier tooling. NOT a repo guard.

CLAUDE.md asks that an allowlisted violation carry a ``# FIXME(#<gh-issue>)`` comment
(a GitHub issue/PR number, never a beads id — beads ids don't resolve for outside
contributors). This detector LISTS `# FIXME(...)` comment markers whose argument is not
``#<digits>`` (beads ids like ``salesagent-9f2``, the ``#gh-issue`` placeholder, empty),
so the review-architecture-guards agent can flag any the diff under review ADDS.

Why a detector and not a `tests/unit/test_architecture_*.py` guard: the review harness is
reviewer-side, untracked tooling. A repo guard on ``make quality`` would fail every other
contributor's build — this tooling reviews others' code, it never gates their CI.
If repo-level enforcement is ever wanted, that is a SEPARATE, explicit contribution to the
project (normal PR + buy-in), not part of this harness.

Scope — false-positive-free via ``tokenize``: only COMMENT tokens whose text begins with
``FIXME(`` count (excludes mid-comment references like ``# see FIXME(#123) above``, prose
about the convention, and FIXME refs inside strings/docstrings such as
``pytest.xfail("... FIXME(salesagent-x)")``).

Usage:
  python3 fixme_format.py [ROOT ...]   # list non-compliant markers (default: src + tests)
  python3 fixme_format.py --selftest   # prove the matcher on pos + neg fixtures

Exit 1 if any non-compliant marker exists (informational worklist); 0 if none / selftest ok.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

_MARKER = re.compile(r"FIXME\(([^)]*)\)")
_GH_ISSUE = re.compile(r"^#\d+$")


def marker_violations(source: str) -> list[tuple[int, str]]:
    """Return ``(lineno, marker_arg)`` for each non-compliant FIXME comment marker.

    A marker is a COMMENT token whose body (after leading ``#`` + whitespace) begins with
    ``FIXME(``. Compliant iff its argument matches ``#<digits>``.
    """
    out: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                continue
            body = tok.string.lstrip("#").strip()
            if not body.startswith("FIXME("):
                continue
            m = _MARKER.match(body)
            if m and not _GH_ISSUE.match(m.group(1).strip()):
                out.append((tok.start[0], m.group(1).strip()))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return out
    return out


def _git_tracked_py(repo: Path, roots: list[Path]) -> list[Path]:
    """Git-tracked .py under *roots* — hermetic, so gitignored local files never count."""
    try:
        listed = subprocess.check_output(
            ["git", "ls-files", *[str(r) for r in roots]], cwd=repo, text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [repo / ln for ln in listed.split() if ln.endswith(".py")]


def scan(roots: list[Path]) -> list[tuple[str, int, str]]:
    repo = Path.cwd()
    hits: list[tuple[str, int, str]] = []
    for f in _git_tracked_py(repo, roots):
        rel_path = str(f.relative_to(repo))
        for lineno, arg in marker_violations(f.read_text(encoding="utf-8", errors="ignore")):
            hits.append((rel_path, lineno, arg))
    return hits


def selftest() -> int:
    flagged = "\n".join(
        [
            "x = 1  # FIXME(salesagent-9f2): migrate to repository",
            "y = 2  # FIXME(#gh-issue): unfilled placeholder",
            "z = 3  ## FIXME(beads-y9k): double-hash marker",
            "w = 4  # FIXME(): empty argument",
        ]
    )
    clean = "\n".join(
        [
            "a = 1  # FIXME(#1566): tracked on GitHub",
            "b = 2  # see FIXME(#1442) above — a reference, not a marker",
            's = "pytest.xfail: FIXME(salesagent-9vgz.1)"  # inside a string',
            "# this module mentions FIXME(#gh-issue) as an example, not a marker",
            "c = 5  # TODO(salesagent-x): a TODO is not a FIXME marker",
        ]
    )
    n_flagged = len(marker_violations(flagged))
    n_clean = len(marker_violations(clean))
    ok = n_flagged == 4 and n_clean == 0
    print(f"  flagged fixture: {n_flagged}/4 non-compliant markers detected")
    print(f"  clean fixture:   {n_clean}/0 false positives")
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    roots = [Path(a) for a in argv if not a.startswith("-")] or [Path("src"), Path("tests")]
    hits = scan(roots)
    if not hits:
        print("No non-compliant FIXME markers found.")
        return 0
    by_file: dict[str, list[tuple[int, str]]] = {}
    for f, lineno, arg in hits:
        by_file.setdefault(f, []).append((lineno, arg))
    for f in sorted(by_file):
        for lineno, arg in sorted(by_file[f]):
            print(f"{f}:{lineno}: # FIXME({arg}) — not a GitHub issue ref")
    print(
        f"\n{len(hits)} non-compliant marker(s) across {len(by_file)} file(s). "
        "During review, flag any the DIFF adds (a new beads-id / `#gh-issue` marker); "
        "pre-existing ones are debt, not this PR's concern."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
