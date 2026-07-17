#!/usr/bin/env python3
"""Citation-freshness detector — stale version citations, in repo code AND in the
harness's own artifacts (the harness rots too).

Flags spec/SDK version literals that drift from the pinned AdCP version, across BOTH
`src/` (repo code) and the untracked review harness (agents / charter / skills). The
grounded exception: a line marked ``# spec-introduced:`` legitimately cites the version
where a feature ENTERED the spec (NOT the pin) — those are skipped [ref: memory
reference_adcp_sdk_spec_mapping.md §6].

This is a DETECTOR, not a proof: it produces a triage worklist (complete over the
version-literal pattern), and the reviewing agent adjudicates each hit (charter §1.5).

Usage:
  python3 citation_freshness.py [ROOT ...]   # scan (default: src + the harness dirs)
  python3 citation_freshness.py --selftest   # prove the matcher on pos + neg fixtures

Exit 1 if any candidate-stale citation is found (or a self-test case fails); else 0.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

# A spec/SDK version-shaped token: 3.1.0, 3.1.0-beta.3, 4.3.0, 3.0.0-beta.3, 3.1.0-rc.13.
SPEC_TOKEN = re.compile(r"\b\d+\.\d+\.\d+(?:-(?:beta|rc|alpha)(?:\.\d+)?)?\b")
# Only treat a token as a spec/SDK citation when the line is ABOUT adcp/the spec —
# kills generic-semver noise (unrelated library versions, sample numbers).
CONTEXT = re.compile(r"spec|adcp|dist/(?:docs|compliance|schemas)|get_adcp_spec_version", re.I)
# Grounded exceptions: a feature's introduction tag ("entered the spec at X", not the
# pin), or an explicit intentional-reference pragma (a historical/forensic mention).
EXEMPT = re.compile(r"spec-introduced|version-literal-ok", re.I)

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "worktrees",
    "htmlcov", "test-results", "dist", "build", ".mypy_cache", ".ruff_cache",
}
SKIP_SUFFIX = {
    ".pyc", ".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".map", ".min.js", ".min.css",
}


def scan_line(line: str, spec_pin: str, sdk_pin: str) -> list[str]:
    """Pure matcher: return the stale version tokens on this line, or []..

    A token is stale iff it is version-shaped, the line is adcp/spec context, the
    token is neither the spec pin nor the SDK pin, and the line is not a grounded
    ``# spec-introduced:`` citation.
    """
    if EXEMPT.search(line):
        return []
    if not CONTEXT.search(line):
        return []
    fresh = {spec_pin, sdk_pin}
    return [tok for tok in SPEC_TOKEN.findall(line) if tok not in fresh]


def derive_pins() -> tuple[str, str]:
    """Source of truth: the installed SDK. Fall back to the repo's version guard/doc."""
    try:
        out = subprocess.run(
            ["uv", "run", "python", "-c",
             "import adcp; print(adcp.get_adcp_spec_version()); print(adcp.get_adcp_sdk_version())"],
            capture_output=True, text=True, timeout=90,
        )
        lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        if len(lines) >= 2 and SPEC_TOKEN.fullmatch(lines[-2]) and SPEC_TOKEN.fullmatch(lines[-1]):
            return lines[-2], lines[-1]
    except Exception:
        pass
    spec = ""
    guard = Path("tests/unit/test_adcp_spec_version.py")
    if guard.exists():
        m = re.search(r'EXPECTED_SPEC_VERSION\s*=\s*"([^"]+)"', guard.read_text())
        if m:
            spec = m.group(1)
    sdk = ""
    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        m = re.search(r'adcp==([\d.]+(?:-\w+(?:\.\d+)?)?)', pyproject.read_text())
        if m:
            sdk = m.group(1)
    return spec, sdk


def _skipped_suffix(p: Path) -> bool:
    return p.suffix in SKIP_SUFFIX or p.name.endswith((".min.js", ".min.css"))


def iter_files(root: Path):
    # A file root scans just that file (rglob on a file yields nothing — the old
    # single-file no-op). A dir root scans its tree, skipping SKIP_DIRS that appear
    # BELOW the root only: the skip is computed on the path RELATIVE to root, so
    # invoking the scan from inside a `.claude/worktrees/agent-X/…` path (whose
    # ABSOLUTE parts contain "worktrees") is no longer a silent no-op.
    if root.is_file():
        if not _skipped_suffix(root):
            yield root
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if _skipped_suffix(p):
            continue
        yield p


def scan(roots: list[Path], spec_pin: str, sdk_pin: str) -> list[tuple[Path, int, str, list[str]]]:
    hits: list[tuple[Path, int, str, list[str]]] = []
    self_path = Path(__file__).resolve()
    for root in roots:
        if not root.exists():
            continue
        for f in iter_files(root):
            if f.resolve() == self_path:  # never flag our own fixtures/comments
                continue
            try:
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                stale = scan_line(line, spec_pin, sdk_pin)
                if stale:
                    hits.append((f, i, line.strip()[:160], stale))
    return hits


def selftest() -> int:
    spec, sdk = "3.1.0-beta.3", "5.7.0"
    cases = [
        # (line, should_flag)
        ("Grounds behavior in spec PROSE for the pinned version (3.0.1) and the", True),
        ('    "adcp==4.3.0",  # exact pin', True),
        ("WebFetch .../dist/docs/3.0.0-beta.3/building/implementation/x.mdx", True),
        ("storyboards live at dist/compliance/3.0.1/*.yaml", True),
        ('    "adcp==5.7.0",  # current pin', False),          # == sdk pin
        ("targets AdCP spec 3.1.0-beta.3 via the SDK", False),  # == spec pin
        ("# spec-introduced: 3.0.0 error-handling.mdx two-layer envelope", False),  # grounded
        ("the unrelated lib bumped to 2.4.1 last week", False),  # no adcp/spec context
        ("no version token on this adcp line at all", False),
        ("repo HEAD spec = 3.1.0-rc.13 (drifting anchor)", True),  # not the pin, spec context
        ("we used to pin adcp 3.0.1 here  # version-literal-ok", False),  # intentional pragma
    ]
    failures = 0
    for line, should in cases:
        got = bool(scan_line(line, spec, sdk))
        status = "ok" if got == should else "FAIL"
        if got != should:
            failures += 1
        print(f"  [{status}] flag={got!s:5} expect={should!s:5} | {line[:70]}")

    # File-iteration cases — guard the no-op class the matcher-only test missed:
    # a scan invoked from inside a `worktrees/` path, and a single-file root.
    total = len(cases)
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "worktrees" / "proj" / "src"
        base.mkdir(parents=True)
        stale = "cites adcp spec 3.0.1 in prose"  # stale vs the (spec, sdk) below
        (base / "x.py").write_text(f"# {stale}\n")
        (base / "skip.pyc").write_text(f"# {stale}\n")  # suffix-skipped
        iter_cases: list[tuple[str, bool]] = [
            ("dir root under worktrees/ yields the .py file",
             any(p.name == "x.py" for p in iter_files(base))),
            ("dir root under worktrees/ skips the .pyc",
             not any(p.name == "skip.pyc" for p in iter_files(base))),
            ("file root yields itself",
             [p.name for p in iter_files(base / "x.py")] == ["x.py"]),
            ("scan() from a worktrees/ root is NOT a no-op",
             bool(scan([base], spec, sdk))),
        ]
        for label, ok in iter_cases:
            total += 1
            status = "ok" if ok else "FAIL"
            if not ok:
                failures += 1
            print(f"  [{status}] {label}")

    print(f"\nself-test: {total - failures}/{total} passed")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    roots = [Path(a) for a in argv if not a.startswith("-")]
    if not roots:
        roots = [Path("src"), Path(".claude/agents"), Path(".claude/rules/private"),
                 Path(".claude/skills")]
    spec_pin, sdk_pin = derive_pins()
    if not spec_pin:
        print("ERROR: could not derive the spec pin (adcp import + guard/doc fallback both failed).",
              file=sys.stderr)
        return 2
    print(f"Derived pin: spec={spec_pin}  sdk={sdk_pin or '(unknown)'}")
    print(f"Scanning: {', '.join(str(r) for r in roots)}\n")
    hits = scan(roots, spec_pin, sdk_pin)
    if not hits:
        print("No candidate-stale version citations found.")
        return 0
    for f, i, line, stale in hits:
        print(f"{f}:{i}: stale {stale} (pin spec={spec_pin} sdk={sdk_pin}) | {line}")
    print(f"\n{len(hits)} candidate-stale citation(s). Triage each: is it the pin, "
          f"a `# spec-introduced:` citation (add the marker), or genuinely stale?")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
