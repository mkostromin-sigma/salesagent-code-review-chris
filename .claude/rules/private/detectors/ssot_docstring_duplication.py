#!/usr/bin/env python3
"""SSOT-docstring-duplication detector — a re-implemented "canonical" symbol.

The trigger (an independent re-review of PR #1534): the PR added a NEW test file that re-implemented
``_call_mcp_tool_capturing_envelope`` — a helper that ALREADY exists at
``tests/integration/test_mcp_error_envelope.py`` whose docstring literally declares itself
"Single source of truth ... used by every wire test". Two copies, same name, bodies differing
only in identity construction / patches (below the R0801 clone threshold, so the duplication
baseline never saw it). Neither ``review-test-integrity`` (scoped to "does the test prove the
code") nor a diff-scoped DRY pass caught it: **the canonical twin lives OUTSIDE the diff**, so a
reviewer reading only the PR cannot know it exists. The one thing that catches it is a repo-wide
grep for the new symbol — which is what this does.

Same session, same shape in production: ``normalize_to_adcp_error`` (exceptions.py) docstrings
itself "Single source of truth for the wrapping applied at all three transport boundaries" while
REST's ``request_validation_error_handler`` and ``media_buy_create.py:4207`` each build the same
envelope shape independently. That one is a *shape* twin under a *different* name — this detector
cannot prove it, but it SURFACES the SSOT claim so the reviewer traces it (check C).

Three checks, one AST pass over src/ + tests/:

  A. SSOT-CONTRADICTED (high precision) — a def/class carrying an SSOT-claim docstring
     ("single source of truth", "canonical", "the one/only place", ...) whose NAME is defined in
     ≥2 distinct files. The claim is provably false; someone re-implemented it.
  B. DUP-HELPERS (worklist) — an underscore-prefixed, non-dunder, non-``test_`` helper name
     defined in ≥2 files under tests/. Candidate test-DRY the clone baseline misses.
  C. SSOT-CLAIMS-TO-VERIFY (anchor) — every SSOT-claim docstring whose name is UNIQUE. The claim
     may still be violated by a differently-named shape-twin; the detector can't
     prove it, so it hands the reviewer the list to trace by hand.

WORKLIST, not a verdict: B and C are leads a human adjudicates; only A is close to mechanical
(and even A can fire on a legitimately-overridden name). The point is that a re-implemented
"canonical" symbol stops being invisible to a diff-scoped review.

Usage:
  python3 ssot_docstring_duplication.py [root ...]   # scan (default roots: src tests)
  python3 ssot_docstring_duplication.py --selftest    # prove the logic on synthetic sources

Exit 1 if check A fires (contradicted claim); 0 if clean / selftest ok / only B|C leads; 2 on error.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

SSOT_CLAIM = re.compile(
    r"single source of truth|sole source|\bcanonical\b|the one place|the only place"
    r"|single home|one home|the one true|authoritative (?:copy|version|home)",
    re.IGNORECASE,
)
# helper closure / trivial names that recur everywhere and aren't DRY signal on their own
UBIQUITOUS = {"_call", "_run", "_go", "_inner", "_wrap", "_impl", "_make", "_get", "_do", "_fn"}


def _defs(source: str) -> list[tuple[str, int, bool]]:
    """Pure: every FunctionDef/AsyncFunctionDef/ClassDef → (name, lineno, has_ssot_docstring)."""
    out: list[tuple[str, int, bool]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node) or ""
            out.append((node.name, node.lineno, bool(SSOT_CLAIM.search(doc))))
    return out


def audit(files: dict[str, str], changed: set[str] | None = None) -> dict:
    """Pure: map {path: source} → the three worklists. Testable without a filesystem.

    ``changed`` (repo-relative paths changed vs a base ref) scopes the per-PR signal: a
    contradicted claim is "PR-relevant" when at least one of its definition sites is a changed
    file — i.e. this PR added or touched a copy of a symbol declared canonical elsewhere.
    """
    # name -> list[(path, lineno, is_ssot)]
    index: dict[str, list[tuple[str, int, bool]]] = {}
    for path, source in files.items():
        for name, lineno, is_ssot in _defs(source):
            index.setdefault(name, []).append((path, lineno, is_ssot))

    contradicted, verify, dup_helpers = [], [], []
    for name, sites in index.items():
        files_with = {p for p, _, _ in sites}
        ssot_sites = [(p, ln) for p, ln, is_ssot in sites if is_ssot]
        if ssot_sites and len(files_with) >= 2:
            touches = changed is not None and bool(files_with & changed)
            contradicted.append((name, ssot_sites, sorted(files_with), touches))
        elif ssot_sites:  # unique-named canonical claim → manual-verify anchor
            verify.append((name, ssot_sites[0]))
        # test-helper duplication net (independent of SSOT claim)
        test_files = {p for p, _, _ in sites if "/tests/" in f"/{p}" or p.startswith("tests/")}
        if (
            len(test_files) >= 2
            and name.startswith("_")
            and not name.startswith("__")
            and not name.startswith("test_")
            and name not in UBIQUITOUS
        ):
            dup_helpers.append((name, sorted(test_files)))
    return {
        "contradicted": sorted(contradicted),
        "verify": sorted(verify),
        "dup_helpers": sorted(dup_helpers),
        "scoped": changed is not None,
    }


def _report(r: dict) -> None:
    c, v, d = r["contradicted"], r["verify"], r["dup_helpers"]
    if c:
        print(f"✗ SSOT-CONTRADICTED ({len(c)}) — a symbol claims 'single source of truth' yet is "
              "defined in ≥2 files. The claim is false; the twin was re-implemented (the #1534 "
              "class). A diff-scoped review is blind to this when the twin is outside the diff.")
        for name, ssot_sites, files_with, touches in c:
            claim_at = ", ".join(f"{p}:{ln}" for p, ln in ssot_sites)
            mark = "  ⟵ a copy is in a changed file" if r["scoped"] and touches else ""
            print(f"    {name}  — SSOT-claim at {claim_at}; also defined in: {', '.join(files_with)}{mark}")
    if d:
        print(f"\n· DUP-HELPERS in tests/ ({len(d)}) — underscore helper defined in ≥2 test files; "
              "candidate test-DRY the clone baseline misses. Adjudicate: extract to tests/helpers/.")
        for name, files_with in d[:20]:
            print(f"    {name}  — {', '.join(files_with)}")
        if len(d) > 20:
            print(f"    … {len(d) - 20} more")
    if v:
        print(f"\n· SSOT-CLAIMS-TO-VERIFY ({len(v)}) — unique-named 'canonical' claims. The detector "
              "can't see a differently-named SHAPE twin (the #1534 shape-twin class); trace each by hand.")
        for name, (p, ln) in v[:25]:
            print(f"    {name}  — {p}:{ln}")
        if len(v) > 25:
            print(f"    … {len(v) - 25} more")
    if not (c or d or v):
        print("No SSOT claims and no duplicated test helpers found in the scanned roots.")


def selftest() -> int:
    canonical = (
        "class WireTests:\n"
        "    def _call_capturing_envelope(self, tool, params):\n"
        '        """Shared helper.\n\n        Single source of truth for the Client(mcp) wire pattern.\n        """\n'
        "        return None\n"
    )
    duplicate = (  # re-implements the same-named helper, no SSOT claim — the same-name twin shape
        "def _call_capturing_envelope(tool, params):\n"
        '    """Local copy."""\n'
        "    return None\n"
    )
    lone_claim = (  # unique-named canonical claim → verify anchor, NOT contradicted
        "def normalize_shape(exc):\n"
        '    """Single source of truth for the envelope shape."""\n'
        "    return exc\n"
    )
    clean = "def helper_one():\n    return 1\n"

    tree = {
        "tests/integration/test_canonical.py": canonical,
        "tests/integration/test_new.py": duplicate,
    }
    bad = audit(tree)
    # scoped: only the new file changed ⇒ the contradiction is PR-relevant (a copy is in the diff)
    scoped = audit(tree, changed={"tests/integration/test_new.py"})
    # scoped to an unrelated change ⇒ same contradiction exists but is NOT PR-relevant
    scoped_off = audit(tree, changed={"tests/integration/test_unrelated.py"})
    good = audit({"src/core/exceptions.py": lone_claim, "src/core/x.py": clean})

    ok = (
        len(bad["contradicted"]) == 1
        and bad["contradicted"][0][0] == "_call_capturing_envelope"
        and ("_call_capturing_envelope", ["tests/integration/test_canonical.py",
                                          "tests/integration/test_new.py"]) in bad["dup_helpers"]
        and scoped["contradicted"][0][3] is True          # touches a changed file
        and scoped_off["contradicted"][0][3] is False      # exists, but not PR-relevant
        and not good["contradicted"]              # unique name ⇒ not contradicted
        and len(good["verify"]) == 1              # ⇒ surfaced as a verify anchor
        and good["verify"][0][0] == "normalize_shape"
    )
    print("── BAD (re-implemented canonical helper) ──")
    _report(bad)
    print("\n── GOOD (unique canonical claim + clean) ──")
    _report(good)
    print("\nself-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _scan_roots(roots: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    cwd = Path.cwd()
    for root in roots:
        base = cwd / root
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            try:
                files[str(py.relative_to(cwd))] = py.read_text(encoding="utf-8")
            except OSError:
                continue
    return files


def _changed_files(base: str) -> set[str] | None:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    return {ln.strip() for ln in out.splitlines() if ln.strip().endswith(".py")}


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    base = None
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1] if i + 1 < len(argv) else None
    roots = [a for a in argv if not a.startswith("-") and a != base] or ["src", "tests"]
    files = _scan_roots(roots)
    if not files:
        print(f"ERROR: no .py files under {roots} (run from repo root).", file=sys.stderr)
        return 2
    changed = _changed_files(base) if base else None
    print(f"ssot-docstring-duplication — scanned {len(files)} files under {', '.join(roots)}"
          + (f"; changed vs {base}: {len(changed)}" if changed is not None else "") + "\n")
    r = audit(files, changed)
    _report(r)
    fire = (
        any(touches for *_, touches in r["contradicted"])
        if r["scoped"] else bool(r["contradicted"])
    )
    if fire:
        print("\nWorklist: resolve each SSOT-CONTRADICTED symbol — the 'single source of truth' "
              "claim is false. Extract to one shared home + import, or drop the claim if the split "
              "is deliberate. With --base, the '⟵ changed file' marks are the PR-relevant ones; "
              "DUP-HELPERS / SSOT-CLAIMS-TO-VERIFY are leads to trace, not failures.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
