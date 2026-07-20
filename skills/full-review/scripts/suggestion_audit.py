#!/usr/bin/env python3
"""Suggestion-audit detector — the wire-VALUE sibling of recovery_audit.py.

A buyer-facing ``suggestion`` reaches the wire two ways, and BOTH are audited here:
  A. a module-level ``*_SUGGESTION`` constant passed at an explicit ``suggestion=``
     raise/handler site (e.g. the REST validation handler, the A2A auth path); and
  B. a per-class ``_default_suggestion`` ClassVar on an ``AdCPError`` subclass (the
     value emitted when a raise passes no explicit suggestion) — the SAME emission
     surface recovery_audit walks for ``_default_recovery``.

Auditing only (A) is how a divergence hides in plain sight: the constant scan catches
a wrong ``*_SUGGESTION`` only if it happens to be a named constant, and grounds it by
the CODE its NAME implies — a heuristic. Surface (B) grounds the ACTUAL emitted value
against the enum for the class's ACTUAL wire code, and catches a ``_default_suggestion``
set to a bare literal that no constant scan would ever see.

Failure modes, none caught by ``make quality`` nor the storyboards (which grade the
error CODE, and suggestion PRESENCE at most — never the text):
  - CROSS-CONTAMINATION — carries ANOTHER code's canonical text (the drift that shipped
    once: a VALIDATION_ERROR value holding INVALID_REQUEST's hint). The arch
    enum-conformance test catches this only for the constants it lists.
  - DIVERGENCE — the code IS in the enum but the text differs & matches no code (drift,
    or an intentional app-specific hint — adjudicate).
  - UNGROUNDED — the code has no enum suggestion (app-specific — verify intentional).
  - NO-WIRE-ORACLE — a grounded constant with no ``wire == pinned enum`` test in tests/
    (a future drift reaches the buyer silently). ``assert wire == THE_CONSTANT`` is a
    lockstep tautology (charter §4c-2); the oracle must be ``wire == pinned enum``
    (tests/helpers/pinned_spec.py::pinned_error_code_suggestion).

Grounds against the repo's pinned error-code.json ``enumMetadata`` (the same fixture the
arch test uses — moves with the repo pin, no separate snapshot to rot).

WORKLIST, not a verdict: an app-specific suggestion MAY intentionally diverge. The
reviewer adjudicates each; the point is none slip silently under prose-only judgment.

Usage:
  python3 suggestion_audit.py            # audit (run from repo root via `uv run`)
  python3 suggestion_audit.py --selftest # prove the audit logic on synthetic rows

Exit 1 if any finding (worklist); 0 if clean / selftest ok.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SUFFIX = "_SUGGESTION"
_ENUM_REL = "tests/fixtures/adcp_schemas_pinned/enums/error-code.json"


def _by_text(enum_sugg: dict[str, str]) -> dict[str, list[str]]:
    by_text: dict[str, list[str]] = {}
    for code, text in enum_sugg.items():
        by_text.setdefault(text, []).append(code)
    return by_text


def _classify(code_key: str, val: str, by_text: dict[str, list[str]], enum_sugg: dict[str, str]):
    """Classify one (code, suggestion) against the enum. Shared by both surfaces.

    Returns a tuple whose head is the category:
      ('grounded',) | ('cross', other_codes) | ('diverge', enum_text) | ('unground',)
    """
    text_codes = sorted(by_text.get(val, []))
    if code_key in text_codes:
        return ("grounded",)
    if text_codes:
        return ("cross", text_codes)
    if code_key in enum_sugg:
        return ("diverge", enum_sugg[code_key])
    return ("unground",)


def audit(consts: dict[str, str], enum_sugg: dict[str, str]):
    """Surface A: module ``*_SUGGESTION`` constants, grounded by the code the NAME implies.

    Returns (grounded, cross, diverge, unground).
    """
    by_text = _by_text(enum_sugg)
    grounded, cross, diverge, unground = [], [], [], []
    for name, val in sorted(consts.items()):
        implied = name[: -len(_SUFFIX)]
        cat = _classify(implied, val, by_text, enum_sugg)
        if cat[0] == "grounded":
            grounded.append((name, implied, val))
        elif cat[0] == "cross":
            cross.append((name, implied, val, cat[1]))
        elif cat[0] == "diverge":
            diverge.append((name, implied, val, cat[1]))
        else:
            unground.append((name, implied, val))
    return grounded, cross, diverge, unground


def audit_class_defaults(rows: list[tuple[str, str, str]], enum_sugg: dict[str, str]):
    """Surface B: per-class ``_default_suggestion``, grounded against the enum for the
    class's ACTUAL wire code. rows = [(class_name, wire_code, suggestion)].

    Returns (grounded, cross, diverge, unground).
    """
    by_text = _by_text(enum_sugg)
    grounded, cross, diverge, unground = [], [], [], []
    for cls, wire, val in sorted(rows):
        cat = _classify(wire, val, by_text, enum_sugg)
        if cat[0] == "grounded":
            grounded.append((cls, wire, val))
        elif cat[0] == "cross":
            cross.append((cls, wire, val, cat[1]))
        elif cat[0] == "diverge":
            diverge.append((cls, wire, val, cat[1]))
        else:
            unground.append((cls, wire, val))
    return grounded, cross, diverge, unground


def _load_constants() -> dict[str, str]:
    sys.path.insert(0, str(Path.cwd()))
    import src.core.exceptions as ex  # noqa: PLC0415

    return {
        name: getattr(ex, name)
        for name in dir(ex)
        if name.endswith(_SUFFIX) and isinstance(getattr(ex, name), str)
    }


def _load_class_rows() -> list[tuple[str, str, str]]:
    """Walk the AdCPError subclass tree for every non-empty ``_default_suggestion``,
    paired with the class's WIRE code (post ``translate_error_code``)."""
    sys.path.insert(0, str(Path.cwd()))
    import src.core.exceptions as ex  # noqa: PLC0415

    rows: list[tuple[str, str, str]] = []

    def walk(cls) -> None:
        for sub in cls.__subclasses__():
            s = getattr(sub, "_default_suggestion", None)
            if s:
                rows.append((sub.__name__, ex.translate_error_code(sub._default_error_code), s))
            walk(sub)

    base = ex.AdCPError
    base_s = getattr(base, "_default_suggestion", None)
    if base_s:
        rows.append((f"{base.__name__} (base)", ex.translate_error_code(base._default_error_code), base_s))
    walk(base)
    return rows


def _load_enum() -> dict[str, str]:
    meta = json.loads((Path.cwd() / _ENUM_REL).read_text())["enumMetadata"]
    return {c: e["suggestion"] for c, e in meta.items() if isinstance(e, dict) and e.get("suggestion")}


def _has_wire_oracle(code: str) -> bool:
    """True if some test grounds this code's wire suggestion in the spec SSOT.

    Searches the working tree (not the git index) so uncommitted oracles count.
    """
    out = subprocess.run(
        ["grep", "-rll", f'pinned_error_code_suggestion("{code}")', "tests"],
        capture_output=True,
        text=True,
    )
    return bool(out.stdout.strip())


def selftest() -> int:
    enum = {
        "VALIDATION_ERROR": "review error details and fix field values",
        "INVALID_REQUEST": "check request parameters and fix",
        "VERSION_UNSUPPORTED": "upgrade the client",
        "POLICY_VIOLATION": "review the policy and adjust the request",
    }
    consts = {
        "VALIDATION_ERROR_SUGGESTION": "review error details and fix field values",  # grounded — must NOT flag
        "INVALID_REQUEST_SUGGESTION": "check request parameters and fix",  # grounded — must NOT flag
        "VERSION_UNSUPPORTED_SUGGESTION": "check request parameters and fix",  # CROSS (holds INVALID_REQUEST's text)
        "POLICY_VIOLATION_SUGGESTION": "some bespoke non-matching hint",  # DIVERGE (own code in enum, no code matches)
        "AUTH_REQUIRED_SUGGESTION": "Provide valid credentials.",  # UNGROUND (implied code absent from enum)
    }
    class_rows = [
        ("GoodErr", "VALIDATION_ERROR", "review error details and fix field values"),  # grounded — must NOT flag
        ("LiteralDriftErr", "POLICY_VIOLATION", "check request parameters and fix"),  # CROSS (INVALID_REQUEST's text, bare literal)
        ("AuthErr", "AUTH_REQUIRED", "Provide creds."),  # UNGROUND (code absent from enum)
    ]
    cg, cc, cd, cu = audit(consts, enum)
    kg, kc, kd, ku = audit_class_defaults(class_rows, enum)
    ok = (
        {x[0] for x in cg} == {"VALIDATION_ERROR_SUGGESTION", "INVALID_REQUEST_SUGGESTION"}
        and {x[0] for x in cc} == {"VERSION_UNSUPPORTED_SUGGESTION"}
        and {x[0] for x in cd} == {"POLICY_VIOLATION_SUGGESTION"}
        and {x[0] for x in cu} == {"AUTH_REQUIRED_SUGGESTION"}
        and {x[0] for x in kg} == {"GoodErr"}
        and {x[0] for x in kc} == {"LiteralDriftErr"}
        and {x[0] for x in ku} == {"AuthErr"}
        and not kd
    )
    print("constants — grounded/cross/diverge/unground:", *(sorted(x[0] for x in s) for s in (cg, cc, cd, cu)))
    print("classes   — grounded/cross/diverge/unground:", *(sorted(x[0] for x in s) for s in (kg, kc, kd, ku)))
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    try:
        consts = _load_constants()
        class_rows = _load_class_rows()
        enum_sugg = _load_enum()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: run from repo root via `uv run` (needs src.core.exceptions + {_ENUM_REL}): {exc}", file=sys.stderr)
        return 2

    c_grounded, c_cross, c_diverge, c_unground = audit(consts, enum_sugg)
    _, k_cross, k_diverge, k_unground = audit_class_defaults(class_rows, enum_sugg)
    no_oracle = [(name, code) for name, code, _ in c_grounded if not _has_wire_oracle(code)]

    findings = c_cross or c_diverge or c_unground or no_oracle or k_cross or k_diverge or k_unground
    if not findings:
        print(f"All {len(consts)} constant(s) and {len(class_rows)} class-default(s) grounded and wire-pinned.")
        return 0

    if c_cross or c_diverge or c_unground:
        print("=== SURFACE A — module *_SUGGESTION constants ===")
        for name, implied, val, codes in c_cross:
            print(f"  CROSS    {name} (for {implied}) = {val!r} — that is {', '.join(codes)}'s canonical suggestion")
        for name, implied, val, specval in c_diverge:
            print(f"  DIVERGE  {name} = {val!r}  (enum {implied}: {specval!r})")
        for name, implied, val in c_unground:
            print(f"  UNGROUND {name} (for {implied}) = {val!r}  (no enum suggestion for that code)")
    if k_cross or k_diverge or k_unground:
        print("\n=== SURFACE B — per-class _default_suggestion (the actual wire-emission surface) ===")
        for cls, wire, val, codes in k_cross:
            print(f"  CROSS    {cls} emits {wire} with {val!r} — that is {', '.join(codes)}'s canonical suggestion")
        for cls, wire, val, specval in k_diverge:
            print(f"  DIVERGE  {cls} emits {wire} with {val!r}  (enum {wire}: {specval!r})")
        for cls, wire, val in k_unground:
            print(f"  UNGROUND {cls} emits {wire} with {val!r}  (no enum suggestion for that code)")
    if no_oracle:
        print("\n=== NO WIRE ORACLE: grounded constant with no `wire == pinned_error_code_suggestion(code)` test ===")
        print("    (a future text drift would reach the buyer with nothing red — add a wire-content oracle)")
        for name, implied in no_oracle:
            print(f"  {name} (for {implied})")
    print(
        "\nWorklist — adjudicate each. Suggestion TEXT is buyer-facing but code-graded-only + presence-graded-only, "
        "so nothing else catches a wrong/undrifted-but-unpinned value. Ground the wire in the spec SSOT "
        "(pinned enum), never in the constant it is derived from (that is a lockstep tautology)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
