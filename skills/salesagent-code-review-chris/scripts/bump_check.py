#!/usr/bin/env python3
"""bump-check — one command to run every harness freshness detector + its self-test.

Run on every `adcp` version bump (and after any error-code / ERROR_CODE_MAPPING / schema change).
The harness embeds two version-pinned spec snapshots (recovery_audit's CODE_RECOVERY table and
sdk_spec_drift's error-code enum); when the SDK pin moves they go stale silently unless something
checks. This is that check.

Two signals are ACTIONABLE (they mean the harness itself is broken or out of date):
  • a detector SELF-TEST fails  → the detector's own logic is broken; fix before trusting anything.
  • a STALE-SNAPSHOT warning     → the SDK pin moved past a snapshot; re-fetch it (each file's
                                    docstring carries the exact refresh command).

Everything else the detectors print (recovery divergences, forced codes, FIXME markers) is a
STANDING count — compare it to your known baseline; a change is worth investigating, but it is
not a per-run alarm (these are pre-existing, adjudicated items).

Usage: uv run python $HARNESS_ROOT/skills/salesagent-code-review-chris/scripts/bump_check.py
  (run from the salesagent repo root so `uv` / `adcp` resolve correctly)
Exit: 2 = a self-test failed · 1 = a snapshot is stale · 0 = self-tests pass and snapshots fresh.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Plugin root = .../skills/salesagent-code-review-chris/scripts → parents[2]
HARNESS_ROOT = HERE.parents[2]

# (name, needs_uv [imports adcp/src], scan_args). citation_freshness is harness-scoped here —
# src + skills citations are a per-PR-diff concern, not a harness-freshness one.
DETECTORS = [
    ("citation_freshness", False, [
        str(HARNESS_ROOT / "agents"),
        str(HARNESS_ROOT / "skills" / "salesagent-code-review-chris" / "references"),
    ]),
    ("recovery_audit", True, []),
    ("sdk_spec_drift", True, []),
    ("fixme_format", False, []),
]


def _run(name: str, uv: bool, args: list[str]) -> subprocess.CompletedProcess:
    cmd = (["uv", "run", "python"] if uv else ["python3"]) + [str(HERE / f"{name}.py"), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def _headline(out: str) -> str:
    return next((ln for ln in out.splitlines() if ln.strip()), "(no output)")


def main() -> int:
    try:
        pin = subprocess.run(
            ["uv", "run", "python", "-c",
             "import adcp; print(adcp.get_adcp_sdk_version(), adcp.get_adcp_spec_version())"],
            capture_output=True, text=True, timeout=120,
        ).stdout.strip()
    except Exception:
        pin = ""
    print(f"bump-check — pinned adcp/spec: {pin or '(could not derive)'}\n")

    print("── self-tests (is each detector's own logic intact?) ──")
    selftest_fail = []
    for name, uv, _args in DETECTORS:
        r = _run(name, uv, ["--selftest"])
        ok = r.returncode == 0
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            selftest_fail.append(name)
    if selftest_fail:
        print(f"\nSTOP (exit 2): self-test failed for {', '.join(selftest_fail)} — the detector is broken; "
              "fix it before trusting any scan.")
        return 2

    print("\n── scans ──")
    stale = []
    for name, uv, args in DETECTORS:
        r = _run(name, uv, args)
        out = r.stdout + r.stderr
        is_stale = "WARNING" in out and "stale" in out.lower()
        if is_stale:
            stale.append(name)
        tag = "STALE" if is_stale else "ctx "
        print(f"  {tag} {name}: {_headline(r.stdout)}")

    print("\n── summary ──")
    if stale:
        print(f"ATTENTION (exit 1): snapshot(s) stale after a pin move — {', '.join(stale)}. "
              "Re-fetch per each file's docstring refresh command, then re-run.")
        return 1
    print("Self-tests pass and both spec snapshots are fresh against the current pin.")
    print("Standing counts above are context — compare to your baseline; a CHANGED count "
          "(new divergence / forced code / FIXME) is what to investigate on a bump.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
