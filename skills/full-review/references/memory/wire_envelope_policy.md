---
name: wire-envelope-policy
description: "Canonical error-test pattern: env.call_via(transport) → assert_envelope_shape(result.wire_error_envelope, code, recovery=...). Reconstructed exceptions are lossy; the wire envelope IS the buyer contract. Current signature: (target, code, *, recovery [REQUIRED], message_substr=None, check_mcp_tool_error=False) — NO check_backward_compat, NO field param."
---

(Signature re-verified 2026-06-11 by reading `tests/helpers/envelope_assertions.py` — an earlier version of this memory listed a `check_backward_compat` kwarg that does NOT exist in the live helper, and showed `recovery` as optional when it is now REQUIRED. Cite the helper by reading it, not from this memory.)

# Wire-envelope assertion policy (established PR #1359)

## The reference pattern

```python
from tests.helpers import assert_envelope_shape

result = env.call_via(transport, **kwargs)
assert result.is_error
assert_envelope_shape(
    result.wire_error_envelope,
    "PACKAGE_NOT_FOUND",
    recovery="terminal",            # REQUIRED kwarg
    message_substr="...",           # optional
)
```

**Current live signature** (`tests/helpers/envelope_assertions.py`): `assert_envelope_shape(target, code, *, recovery, message_substr=None, check_mcp_tool_error=False)`. `target` accepts a dict (REST body, A2A `error.data`, raw envelope) or an `AdCPToolError` (MCP — reads `.envelope`). The two-layer invariant: `adcp_error.code` and `errors[0].code` must BOTH match. The helper replaced the per-boundary `_assert_*_envelope` helpers.

## Why

Reconstruction is **lossy** — e.g. `AdCPAuthenticationError` and `AdCPAuthorizationError` both map to `AUTH_REQUIRED` on the wire; the harness reconstruction always picks one of them regardless of which production raised. Tests asserting on reconstructed exceptions verify the reconstruction layer, not the buyer-facing contract. The buyer contract IS the envelope; the spec defines it; storyboard runners parse it.

## What NOT to assert in new error tests

`isinstance(error, AdCPValidationError)` / `error.error_code == ...` / `error.recovery == ...` / `exc_info.value.details.get("error_code")` — all reconstruction-layer. Acceptable ONLY in `_impl`-level tests (no wire involved) and in pre-policy tests not yet migrated.

## Migration policy

New error tests MUST use `result.wire_error_envelope` + `assert_envelope_shape()`. Existing call sites migrate when touched (boy-scout rule). BDD Then steps get wire-envelope variants alongside exception-based steps.

## Reference implementation

`tests/integration/test_a2a_error_responses.py::test_create_media_buy_validation_error_includes_errors_field` — cite by TEST NAME, not line number (the old ":164" citation drifted; lines always do).

Related: [[harness_error_wire_per_transport_mechanics]] (what call_via captures per transport), [[reference_review_patterns]] (P23 per-transport coverage; P24 is this policy).
