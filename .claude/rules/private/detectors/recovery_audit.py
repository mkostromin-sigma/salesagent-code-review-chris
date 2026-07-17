#!/usr/bin/env python3
"""Recovery-audit detector — the graded-silent recovery taxonomy (nothing else checks it).

AdCP conformance storyboards grade the wire ERROR CODE only, not the ``recovery`` class,
so a wrong/incoherent recovery is "graded-silent": green ``make quality``, green storyboards,
nothing catches it. But the spec's Recovery Behavior table (transport-errors.mdx §Recovery
Behavior) makes ``recovery`` buyer-ACTIONABLE — transient=retry, correctable=surface+don't-
auto-retry, terminal=surface-to-human+don't-retry — so a wrong value misdirects the buyer
(e.g. ``terminal`` on a transient outage tells the buyer NOT to retry a retryable failure).

Audits every ``AdCPError`` subclass's ``(wire_code, recovery)`` two ways:
  1. INCOHERENCE   — one wire code emitted with >1 recovery across classes.
  2. SPEC-DIVERGENCE — a class's recovery differs from the spec's code->recovery classification.

This is a WORKLIST, not a verdict. The client uses an explicit ``recovery`` when present and
falls back to the code table only when it is absent, so a class MAY intentionally set a
recovery that differs from the code-based default. The reviewer adjudicates each hit; the point
is that NONE slip silently — which is exactly what happens under prose-only judgment (this
detector was built after a strong human review missed the ``SERVICE_UNAVAILABLE``/terminal case).

Ground truth: the spec ``CODE_RECOVERY`` map, transcribed verbatim from
``dist/docs/<pin>/building/operating/transport-errors.mdx`` §Recovery Behavior. The snapshot is
version-pinned; the detector self-checks against the installed SDK's spec version and HARD-FAILS
if the pin moved (re-transcribe then — a stale snapshot is itself a staleness bug, and a warning that
audits anyway is one the pin-bump ignored, which is exactly how this snapshot went stale once).

Usage:
  python3 recovery_audit.py            # audit src/core/exceptions.py (run from repo root, via `uv run`)
  python3 recovery_audit.py --selftest # prove the audit logic on synthetic rows

Exit 1 if any incoherence or spec-divergence is found (worklist); 0 if clean / selftest ok.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

SNAPSHOT_SPEC_VERSION = "3.1.1"  # version-literal-ok: pinned CODE_RECOVERY snapshot, self-checked (hard) in main()

# Verbatim spec code->recovery, transcribed from the enumMetadata `recovery` field of
# dist/schemas/<pin>/enums/error-code.json (the SDK MUST consume that block, not parse prose).
# Refresh on an adcp bump (main() hard-fails until this matches the pin):
#   gh api "repos/adcontextprotocol/adcp/contents/dist/schemas/<pin>/enums/error-code.json?ref=main" \
#     --jq '.content' | base64 -d | python3 -c \
#     'import json,sys; d=json.load(sys.stdin); m=d["enumMetadata"]; \
#      [print(f"    \"{c}\": \"{m[c][\"recovery\"]}\",") for c in sorted(d["enum"])]'
SPEC_CODE_RECOVERY: dict[str, str] = {
    "ACCOUNT_AMBIGUOUS": "correctable",
    "ACCOUNT_NOT_FOUND": "terminal",
    "ACCOUNT_PAYMENT_REQUIRED": "terminal",
    "ACCOUNT_SETUP_REQUIRED": "correctable",
    "ACCOUNT_SUSPENDED": "terminal",
    "ACTION_NOT_ALLOWED": "correctable",
    "AGENT_BLOCKED": "terminal",
    "AGENT_SUSPENDED": "terminal",
    "AUDIENCE_TOO_SMALL": "correctable",
    "AUTHORIZATION_REQUIRED": "correctable",
    "AUTH_INVALID": "terminal",
    "AUTH_MISSING": "correctable",
    "AUTH_REQUIRED": "correctable",
    "BILLING_NOT_PERMITTED_FOR_AGENT": "correctable",
    "BILLING_NOT_SUPPORTED": "correctable",
    "BILLING_OUT_OF_BAND": "terminal",
    "BRAND_REQUIRED": "correctable",
    "BUDGET_CAP_REACHED": "correctable",
    "BUDGET_EXCEEDED": "correctable",
    "BUDGET_EXHAUSTED": "terminal",
    "BUDGET_TOO_LOW": "correctable",
    "CAMPAIGN_SUSPENDED": "transient",
    "CATALOG_LIMIT_EXCEEDED": "correctable",
    "COMPLIANCE_UNSATISFIED": "correctable",
    "CONFIGURATION_ERROR": "terminal",
    "CONFLICT": "transient",
    "CREATIVE_DEADLINE_EXCEEDED": "correctable",
    "CREATIVE_INACCESSIBLE": "correctable",
    "CREATIVE_NOT_FOUND": "correctable",
    "CREATIVE_REJECTED": "correctable",
    "CREATIVE_VALUE_NOT_ALLOWED": "correctable",
    "CREDENTIAL_IN_ARGS": "terminal",
    "EVALUATOR_AGENT_NOT_ACCEPTED": "correctable",
    "FEED_FETCH_FAILED": "correctable",
    "FIELD_NOT_PERMITTED": "correctable",
    "FORMAT_DECLARATION_DIVERGENT": "correctable",
    "FORMAT_DECLARATION_V1_AMBIGUOUS": "correctable",
    "FORMAT_DECLARATION_V1_LOSSY_MULTI_SIZE": "correctable",
    "FORMAT_NOT_SUPPORTED": "correctable",
    "FORMAT_OPTION_UNRESOLVED": "correctable",
    "FORMAT_PROJECTION_FAILED": "correctable",
    "GOVERNANCE_DENIED": "correctable",
    "GOVERNANCE_UNAVAILABLE": "transient",
    "IDEMPOTENCY_CONFLICT": "correctable",
    "IDEMPOTENCY_EXPIRED": "correctable",
    "IDEMPOTENCY_IN_FLIGHT": "transient",
    "INVALID_FEED_FORMAT": "correctable",
    "INVALID_REQUEST": "correctable",
    "INVALID_STATE": "correctable",
    "IO_REQUIRED": "correctable",
    "ITEM_VALIDATION_FAILED": "correctable",
    "MEDIA_BUY_NOT_FOUND": "correctable",
    "MULTI_FINALIZE_UNSUPPORTED": "correctable",
    "NOT_CANCELLABLE": "correctable",
    "PACKAGE_NOT_FOUND": "correctable",
    "PAYMENT_TERMS_NOT_SUPPORTED": "correctable",
    "PERMISSION_DENIED": "correctable",
    "PIXEL_TRACKER_LOSSY_DOWNGRADE": "correctable",
    "PIXEL_TRACKER_UPGRADE_INFERRED": "correctable",
    "PLAN_NOT_FOUND": "correctable",
    "POLICY_VIOLATION": "correctable",
    "PRIVATE_FIELD_IN_PUBLIC_PLACEMENT": "correctable",
    "PRODUCT_EXPIRED": "correctable",
    "PRODUCT_NOT_FOUND": "correctable",
    "PRODUCT_UNAVAILABLE": "correctable",
    "PROPOSAL_EXPIRED": "correctable",
    "PROPOSAL_NOT_COMMITTED": "correctable",
    "PROPOSAL_NOT_FOUND": "correctable",
    "PROVENANCE_CLAIM_CONTRADICTED": "correctable",
    "PROVENANCE_DIGITAL_SOURCE_TYPE_MISSING": "correctable",
    "PROVENANCE_DISCLOSURE_MISSING": "correctable",
    "PROVENANCE_EMBEDDED_MISSING": "correctable",
    "PROVENANCE_REQUIRED": "correctable",
    "PROVENANCE_VERIFIER_NOT_ACCEPTED": "correctable",
    "RATE_LIMITED": "transient",
    "READ_ONLY_SCOPE": "correctable",
    "REFERENCE_NOT_FOUND": "correctable",
    "REQUOTE_REQUIRED": "correctable",
    "SCOPE_INSUFFICIENT": "correctable",
    "SERVICE_UNAVAILABLE": "transient",
    "SESSION_NOT_FOUND": "correctable",
    "SESSION_TERMINATED": "correctable",
    "SIGNAL_NOT_FOUND": "correctable",
    "SIGNAL_TARGETING_INCOMPATIBLE": "correctable",
    "STALE_RESPONSE": "transient",
    "TERMS_REJECTED": "correctable",
    "UNPRICEABLE_OUTPUT": "correctable",
    "UNSUPPORTED_FEATURE": "correctable",
    "UNSUPPORTED_GRANULARITY": "correctable",
    "UNSUPPORTED_PROVISIONING": "correctable",
    "VALIDATION_ERROR": "correctable",
    "VERSION_UNSUPPORTED": "correctable",
}


def audit(rows: list[tuple[str, str, str]], spec: dict[str, str]):
    """Pure: rows = [(class_name, wire_code, recovery)]. Returns (incoherent, divergent, unauditable)."""
    by_code: dict[str, set] = defaultdict(set)
    for _name, wire, rec in rows:
        by_code[wire].add(rec)
    incoherent = {w: sorted(r) for w, r in by_code.items() if len(r) > 1}
    divergent = [(n, w, rec, spec[w]) for n, w, rec in rows if w in spec and rec != spec[w]]
    unauditable = sorted({w for _n, w, _r in rows if w not in spec})
    return incoherent, divergent, unauditable


def _load_rows() -> list[tuple[str, str, str]]:
    sys.path.insert(0, str(Path.cwd()))
    import src.core.exceptions as ex  # noqa: PLC0415

    mapping = ex.ERROR_CODE_MAPPING

    def wire(code: str) -> str:
        return mapping.get(code, code)

    rows: list[tuple[str, str, str]] = []

    def walk(cls) -> None:
        for sub in cls.__subclasses__():
            rows.append((sub.__name__, wire(sub._default_error_code), sub._default_recovery))
            walk(sub)

    base = ex.AdCPError
    rows.append((f"{base.__name__} (base)", wire(base._default_error_code), base._default_recovery))
    walk(base)
    return rows


def selftest() -> int:
    rows = [
        ("Good", "SERVICE_UNAVAILABLE", "transient"),
        ("BadSpec", "SERVICE_UNAVAILABLE", "terminal"),        # divergence + (with Good) incoherence
        ("OkValidation", "VALIDATION_ERROR", "correctable"),   # matches spec — must NOT flag
        ("Unknown", "MY_CUSTOM_CODE", "terminal"),             # unauditable, not divergent
    ]
    inc, div, un = audit(rows, SPEC_CODE_RECOVERY)
    ok = (
        "SERVICE_UNAVAILABLE" in inc
        and any(d[0] == "BadSpec" for d in div)
        and not any(d[0] == "OkValidation" for d in div)
        and "MY_CUSTOM_CODE" in un
    )
    print("incoherent :", inc)
    print("divergent  :", [(d[0], d[1], d[2], "spec=" + d[3]) for d in div])
    print("unauditable:", un)
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    try:
        import adcp  # noqa: PLC0415  # type: ignore[import-not-found]

        pin = adcp.get_adcp_spec_version()
    except Exception:
        pin = None
    try:
        rows = _load_rows()
    except Exception as exc:
        print(f"ERROR: could not import src.core.exceptions (run from repo root via `uv run`): {exc}", file=sys.stderr)
        return 2
    if pin and pin != SNAPSHOT_SPEC_VERSION:
        print(
            f"STALE SNAPSHOT (hard fail): spec pin is {pin} but the embedded CODE_RECOVERY snapshot is "
            f"{SNAPSHOT_SPEC_VERSION}. A stale table makes every divergence verdict untrustworthy, so this "
            f"is a gate, not a warning (the ignored-warning miss-class) — re-transcribe SPEC_CODE_RECOVERY "
            f"from error-code.json@{pin} (refresh cmd at the snapshot), bump SNAPSHOT_SPEC_VERSION, re-run.",
            file=sys.stderr,
        )
        return 2
    inc, div, un = audit(rows, SPEC_CODE_RECOVERY)
    if not inc and not div:
        print(f"No recovery incoherences or spec-divergences ({len(rows)} classes audited).")
        return 0
    if inc:
        print("=== INCOHERENCE: one wire code, multiple recovery classes ===")
        for w, recs in sorted(inc.items()):
            print(f"  {w}: {recs}")
            for line in sorted(f"{n}={r}" for n, ww, r in rows if ww == w):
                print(f"      {line}")
    if div:
        print("\n=== SPEC-DIVERGENCE: class recovery != spec CODE_RECOVERY (adjudicate — some may be intentional) ===")
        for n, w, rec, specrec in sorted(div):
            print(f"  {n}: {w} recovery={rec}  (spec: {specrec})")
    if un:
        print(f"\n({len(un)} wire code(s) not in the spec table, not auditable: {', '.join(un)})")
    print(
        "\nWorklist — adjudicate each: an explicit recovery MAY intentionally differ from the code-based "
        "fallback, but flag any that misdirect the buyer (e.g. terminal on a retryable/correctable code). "
        "Recovery is buyer-actionable (transport-errors.mdx §Recovery Behavior) yet storyboard-ungraded, "
        "so nothing else catches these."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
