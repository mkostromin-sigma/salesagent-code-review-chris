#!/usr/bin/env python3
r"""SDK-vs-spec drift detector — derived-authority lag (the SDK trails the published spec).

The installed `adcp` SDK ships ~36 `STANDARD_ERROR_CODES`; the PUBLISHED spec error-code
enum is much larger (80 at the pinned snapshot). Codes the spec defines but the SDK lacks
CANNOT be emitted as a wire code here (a build-time assert requires every wire code to be
SDK-standard), so we are FORCED to map them to a less-precise SDK code — inheriting the
target's semantics (this is exactly what makes `CONFIGURATION_ERROR`→`SERVICE_UNAVAILABLE`
carry the wrong recovery; see recovery_audit). The SDK is a DERIVED authority; grounding
against it instead of the published spec is the root miss.

This runs primarily on an `adcp` BUMP (and on any error-code / mapping change). It reports:
  A) OUR codes that are spec-standard but SDK-lacks — the standing forced-mapping gap.
  B) our `ERROR_CODE_MAPPING` keys that are spec-standard, split:
       B1 = SDK ALSO has it now  → the SDK caught up; REMOVE the mapping, emit the code (ACTIONABLE).
       B2 = SDK still lacks it    → still forced upstream; watch for it to move to B1 on the next bump.
  info) raw |spec \ SDK| drift + any SDK code absent from the spec enum.

Ground truth: the spec error-code enum, snapshotted from `dist/schemas/<pin>/enums/error-code.json`.
Refresh on bump:
  gh api "repos/adcontextprotocol/adcp/contents/dist/schemas/<pin>/enums/error-code.json?ref=main" \
    --jq '.content' | base64 -d | python3 -c 'import json,sys; print(json.load(sys.stdin)["enum"])'
The detector self-checks its snapshot version against the installed SDK pin and HARD-FAILS on
drift (a stale enum misreports the buckets; a warning that analyzes anyway is one the pin-bump
ignored — which is how the snapshot went stale once).

Usage:
  python3 sdk_spec_drift.py            # analyze (run from repo root, via `uv run`)
  python3 sdk_spec_drift.py --selftest # prove the set logic on synthetic inputs

Exit 2 if the snapshot is stale (pin moved); exit 1 if a B1 (now-removable) mapping exists; else 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

SNAPSHOT_SPEC_VERSION = "3.1.1"  # version-literal-ok: pinned error-code enum snapshot, self-checked (hard) in main()

# Verbatim spec error-code enum (dist/schemas/<pin>/enums/error-code.json — see refresh cmd above).
# Refresh on an adcp bump (main() hard-fails until this matches the pin):
#   gh api "repos/adcontextprotocol/adcp/contents/dist/schemas/<pin>/enums/error-code.json?ref=main" \
#     --jq '.content' | base64 -d | python3 -c \
#     'import json,sys; [print(f"    \"{c}\",") for c in sorted(json.load(sys.stdin)["enum"])]'
SPEC_ERROR_CODES: frozenset[str] = frozenset({
    "ACCOUNT_AMBIGUOUS",
    "ACCOUNT_NOT_FOUND",
    "ACCOUNT_PAYMENT_REQUIRED",
    "ACCOUNT_SETUP_REQUIRED",
    "ACCOUNT_SUSPENDED",
    "ACTION_NOT_ALLOWED",
    "AGENT_BLOCKED",
    "AGENT_SUSPENDED",
    "AUDIENCE_TOO_SMALL",
    "AUTHORIZATION_REQUIRED",
    "AUTH_INVALID",
    "AUTH_MISSING",
    "AUTH_REQUIRED",
    "BILLING_NOT_PERMITTED_FOR_AGENT",
    "BILLING_NOT_SUPPORTED",
    "BILLING_OUT_OF_BAND",
    "BRAND_REQUIRED",
    "BUDGET_CAP_REACHED",
    "BUDGET_EXCEEDED",
    "BUDGET_EXHAUSTED",
    "BUDGET_TOO_LOW",
    "CAMPAIGN_SUSPENDED",
    "CATALOG_LIMIT_EXCEEDED",
    "COMPLIANCE_UNSATISFIED",
    "CONFIGURATION_ERROR",
    "CONFLICT",
    "CREATIVE_DEADLINE_EXCEEDED",
    "CREATIVE_INACCESSIBLE",
    "CREATIVE_NOT_FOUND",
    "CREATIVE_REJECTED",
    "CREATIVE_VALUE_NOT_ALLOWED",
    "CREDENTIAL_IN_ARGS",
    "EVALUATOR_AGENT_NOT_ACCEPTED",
    "FEED_FETCH_FAILED",
    "FIELD_NOT_PERMITTED",
    "FORMAT_DECLARATION_DIVERGENT",
    "FORMAT_DECLARATION_V1_AMBIGUOUS",
    "FORMAT_DECLARATION_V1_LOSSY_MULTI_SIZE",
    "FORMAT_NOT_SUPPORTED",
    "FORMAT_OPTION_UNRESOLVED",
    "FORMAT_PROJECTION_FAILED",
    "GOVERNANCE_DENIED",
    "GOVERNANCE_UNAVAILABLE",
    "IDEMPOTENCY_CONFLICT",
    "IDEMPOTENCY_EXPIRED",
    "IDEMPOTENCY_IN_FLIGHT",
    "INVALID_FEED_FORMAT",
    "INVALID_REQUEST",
    "INVALID_STATE",
    "IO_REQUIRED",
    "ITEM_VALIDATION_FAILED",
    "MEDIA_BUY_NOT_FOUND",
    "MULTI_FINALIZE_UNSUPPORTED",
    "NOT_CANCELLABLE",
    "PACKAGE_NOT_FOUND",
    "PAYMENT_TERMS_NOT_SUPPORTED",
    "PERMISSION_DENIED",
    "PIXEL_TRACKER_LOSSY_DOWNGRADE",
    "PIXEL_TRACKER_UPGRADE_INFERRED",
    "PLAN_NOT_FOUND",
    "POLICY_VIOLATION",
    "PRIVATE_FIELD_IN_PUBLIC_PLACEMENT",
    "PRODUCT_EXPIRED",
    "PRODUCT_NOT_FOUND",
    "PRODUCT_UNAVAILABLE",
    "PROPOSAL_EXPIRED",
    "PROPOSAL_NOT_COMMITTED",
    "PROPOSAL_NOT_FOUND",
    "PROVENANCE_CLAIM_CONTRADICTED",
    "PROVENANCE_DIGITAL_SOURCE_TYPE_MISSING",
    "PROVENANCE_DISCLOSURE_MISSING",
    "PROVENANCE_EMBEDDED_MISSING",
    "PROVENANCE_REQUIRED",
    "PROVENANCE_VERIFIER_NOT_ACCEPTED",
    "RATE_LIMITED",
    "READ_ONLY_SCOPE",
    "REFERENCE_NOT_FOUND",
    "REQUOTE_REQUIRED",
    "SCOPE_INSUFFICIENT",
    "SERVICE_UNAVAILABLE",
    "SESSION_NOT_FOUND",
    "SESSION_TERMINATED",
    "SIGNAL_NOT_FOUND",
    "SIGNAL_TARGETING_INCOMPATIBLE",
    "STALE_RESPONSE",
    "TERMS_REJECTED",
    "UNPRICEABLE_OUTPUT",
    "UNSUPPORTED_FEATURE",
    "UNSUPPORTED_GRANULARITY",
    "UNSUPPORTED_PROVISIONING",
    "VALIDATION_ERROR",
    "VERSION_UNSUPPORTED",
})


def analyze(spec: set[str], sdk: set[str], mapping_keys: set[str], our_codes: set[str]) -> dict:
    """Pure set analysis. Returns the flag buckets."""
    forced = sorted((our_codes & spec) - sdk)               # A: we reference it, spec has it, SDK can't emit it
    map_spec = mapping_keys & spec
    return {
        "forced": forced,
        "b1_removable": sorted(map_spec & sdk),             # SDK now supports it → drop the mapping
        "b2_still_forced": sorted(map_spec - sdk),          # spec has it, SDK still lacks it → watch
        "spec_minus_sdk": len(spec - sdk),
        "sdk_minus_spec": sorted(sdk - spec),               # SDK code absent from the spec enum
    }


def _load_ours() -> tuple[set[str], set[str]]:
    sys.path.insert(0, str(Path.cwd()))
    import src.core.exceptions as ex  # noqa: PLC0415

    mapping_keys = set(ex.ERROR_CODE_MAPPING)
    codes: set[str] = set(ex.ERROR_CODE_MAPPING) | set(ex.INTERNAL_CODES)

    def walk(cls) -> None:
        for sub in cls.__subclasses__():
            codes.add(sub._default_error_code)
            walk(sub)

    codes.add(ex.AdCPError._default_error_code)
    walk(ex.AdCPError)
    return mapping_keys, codes


def selftest() -> int:
    spec = {"A", "B", "C", "D"}
    sdk = {"A", "B"}                       # SDK lacks C, D
    mapping_keys = {"C", "D"}              # we map C (forced) and D
    our_codes = {"A", "C", "D", "X"}       # X is non-spec internal
    r = analyze(spec, sdk, mapping_keys, our_codes)
    ok = (
        r["forced"] == ["C", "D"]
        and r["b1_removable"] == []
        and r["b2_still_forced"] == ["C", "D"]
        and r["spec_minus_sdk"] == 2
        and r["sdk_minus_spec"] == []
    )
    # now let the SDK "catch up" on C → it becomes removable (B1)
    r2 = analyze(spec, sdk | {"C"}, mapping_keys, our_codes)
    ok = ok and r2["b1_removable"] == ["C"] and r2["forced"] == ["D"]
    print("round 1:", r)
    print("round 2 (SDK adds C):", {k: r2[k] for k in ("forced", "b1_removable", "b2_still_forced")})
    print("self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    try:
        import adcp  # noqa: PLC0415  # type: ignore[import-not-found]
        from adcp.server.helpers import STANDARD_ERROR_CODES  # noqa: PLC0415  # type: ignore[import-not-found]

        pin = adcp.get_adcp_spec_version()
        sdk = set(STANDARD_ERROR_CODES)
    except Exception as exc:
        print(f"ERROR: could not import the adcp SDK (run via `uv run`): {exc}", file=sys.stderr)
        return 2
    try:
        mapping_keys, our_codes = _load_ours()
    except Exception as exc:
        print(f"ERROR: could not import src.core.exceptions (run from repo root): {exc}", file=sys.stderr)
        return 2

    if pin and pin != SNAPSHOT_SPEC_VERSION:
        print(
            f"STALE SNAPSHOT (hard fail): spec pin is {pin} but the embedded error-code snapshot is "
            f"{SNAPSHOT_SPEC_VERSION}. Analyzing against a stale enum misreports the forced/removable "
            f"buckets, so this gates rather than warns (the ignored-warning miss-class) — re-fetch "
            f"error-code.json@{pin} (refresh cmd in the docstring), bump SNAPSHOT_SPEC_VERSION, re-run.",
            file=sys.stderr,
        )
        return 2
    r = analyze(set(SPEC_ERROR_CODES), sdk, mapping_keys, our_codes)

    print(f"spec codes: {len(SPEC_ERROR_CODES)}  SDK codes: {len(sdk)}  (raw drift: {r['spec_minus_sdk']} spec codes the SDK lacks)")
    if r["b1_removable"]:
        print("\n=== ACTION: SDK now supports these — REMOVE the mapping and emit the spec code directly ===")
        for c in r["b1_removable"]:
            print(f"  {c}")
    if r["forced"]:
        print("\n=== FORCED off-spec (spec-standard, SDK lacks → we must map away; watch for SDK to add them) ===")
        for c in r["forced"]:
            print(f"  {c}")
    if r["sdk_minus_spec"]:
        print(f"\n=== SDK code(s) absent from the spec enum (SDK-only / legacy): {', '.join(r['sdk_minus_spec'])} ===")
    if not r["b1_removable"]:
        print("\nNo now-removable mappings (snapshot fresh). The FORCED gap is an upstream SDK lag — re-run on the next adcp bump.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
