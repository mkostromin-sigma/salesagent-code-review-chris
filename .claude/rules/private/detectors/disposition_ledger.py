#!/usr/bin/env python3
"""Disposition-ledger detector — a real finding, silently dropped by consolidation.

The trigger (PR #1547 re-review): the specialist reviewers FOUND two genuine DRY sites — but rated
them NIT, split across two agents, and the consolidation filed the lot as "SHOULD-FIX (all
optional / non-gating)". They were never surfaced; they stayed in a local note. The same
sites were raised independently on the PR (unified, with a fix path) a day later. Severity was not
the failure — DISPOSITION was: a finding with no resolved next-action gets dropped, and
"optional / non-gating" is the banned label that launders the drop (`review-charter.md` §1.8,
§3, §4b.5). ``make quality`` is green either way; nothing mechanical catches a dropped finding.

This detector reads a consolidation artifact (a `.claude/reports/full-review-*.md`, or any
review write-up) and checks the OUTPUT contract the charter already mandates in prose:

  1. LEDGER-PRESENT   — an Actions ledger section exists (§4b.5): every finding ends in a
                        resolved state {done | folded-in | tracked(link) | won't-fix(reason)}.
  2. DISPOSITION-COVERAGE — every severity-tagged finding carries a disposition somewhere
                        (inline ``Disposition:`` per §3, or an Actions-ledger entry). A deficit
                        means N findings have no resolved next-action — the drop.
  3. BANNED-AS-DISPOSITION — "optional / non-blocking / non-gating / nice-to-have" used as a
                        finding's disposition or as a bucket header (§1.8): they name no action.

This is a WORKLIST, not a verdict (like recovery_audit): the counts are heuristic and the
banned words can legitimately appear when QUOTING an external reviewer. The human adjudicates
each hit — the point is that a dropped finding stops being SILENT. It does NOT judge whether a
finding is correct or well-unified; cross-agent unification is the T3 synthesis step (a
judgment pass in `/full-review` Step 5), which this detector deliberately does not attempt.

  4. SITE-DROP (``--notes``) — the second failure channel, from PR #1534. The consolidation notes
     enumerated a THIRD duplication site (``media_buy_create.py:4207``); the SSOT-synthesis pass
     then reframed the finding to "two homes" and the third `path:line` fell out of the posted
     review. It was raised independently a day later. The disposition checks above can't see it: nothing
     was un-resolved — a site inside one finding's prose was silently narrowed 3→2. This mode
     diffs the `path:line` tokens in the source notes against the shipped artifact and flags any
     that vanished (compared on ``basename:line`` so a notes-basename matches an artifact-full-path).
     Some sites legitimately consolidate; the human adjudicates — but a dropped site stops being
     invisible. Pair every SSOT/duplication finding with one ledger ROW PER SITE so this holds.
     Signal-to-noise is best when the ``--notes`` input is the structured findings ledger (each row
     a real finding-site); freeform scratch notes also cite reasoning breadcrumbs, which surface as
     benign "drops" to wave past — the real dropped-finding site (e.g. ``media_buy_create.py:4207``)
     is in the list either way.

  5. INTERNAL-VOCAB (§1.9 output hygiene) — from PR #1575: the internal quality-bar label "gold
     standard" was in the request's wording and got drafted straight into a posted PR comment.
     Internal harness / quality-bar vocabulary ("gold standard"), the review WORKINGS (specialist
     reviewers, "<X> harness", "masking-gotcha"), and detector names must NEVER appear in a public
     artifact — EVEN when echoing the user's own framing. This scan flags them (worklist: the human
     adjudicates quote-of-reviewer vs a genuine leak) and gates independently of findings, so it
     fires on a zero-finding write-up too. Report the concrete technical state, not the internal
     label. The banned-disposition check (#3) covers §1.8; this covers §1.9.

Usage:
  python3 disposition_ledger.py [report.md]                 # audit a report (default: newest full-review-*.md)
  python3 disposition_ledger.py report.md --notes notes.md  # + cross-check notes→artifact site drop
  python3 disposition_ledger.py --selftest                  # prove the audit logic on synthetic reports

Exit 1 if the contract is unmet or a site was dropped (worklist); 0 if clean / selftest ok; 2 on I/O error.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# §3 disposition vocabulary + the §4b.5 Actions-ledger resolved verbs. A finding is "resolved"
# when one of these appears for it (inline or in the ledger).
DISPOSITION_TOKENS = re.compile(
    r"\b(FIX-NOW|FOLD-IN|FOLLOW-UP|WON'?T-FIX)\b"
    r"|(?:→|->)\s*(?:done|folded-in|tracked|declined|won'?t-fix|fix-now)",
    re.IGNORECASE,
)
# A severity-tagged finding header, e.g. "**[SHOULD-FIX · arch-guards] ARCH-SF1 …**" or
# "#### [BLOCKER] P17 — `foo` (path:12)". The bracketed severity is the anchor.
FINDING_TAG = re.compile(r"\[(BLOCKER|SHOULD-FIX|NIT)\b", re.IGNORECASE)
# The Actions-ledger section heading (§4b.5).
LEDGER_HEADING = re.compile(r"^#{1,4}\s*Actions\b|Actions\s+ledger|Actions\s*\(charter", re.IGNORECASE | re.MULTILINE)
# Banned-as-disposition language (§1.8) — flagged with line; human adjudicates quote-vs-bucket.
BANNED = re.compile(r"\b(optional|non-blocking|non-gating|nice-to-have)\b", re.IGNORECASE)
# §1.9 output-hygiene — internal harness / quality-bar vocabulary that must NEVER surface in a
# public artifact (PR comment, issue, committed doc), EVEN when echoing the user's own request
# framing. "gold standard" is the trigger (PR #1575: the internal quality-bar label was drafted
# from the request's wording straight into a posted PR comment). The process/tooling names reveal
# the review WORKINGS (feedback_no_internal_dialogue_in_public_artifacts). Worklist, not verdict:
# the human adjudicates quote-of-reviewer vs a genuine leak — but the leak stops being silent.
INTERNAL_VOCAB = re.compile(
    r"\bgold[\s-]?standard\b"
    r"|\bmasking[\s-]?gotcha\b"
    r"|\b(?:review|reviewer|personal|our)\s+harness\b"
    r"|\bspecialist reviewers?\b"
    r"|\b(?:recovery_audit|citation_freshness|disposition_ledger|sdk_spec_drift"
    r"|ssot_docstring_duplication|pr_import_cycle|review_completeness|bump_check|fixme_format)\b",
    re.IGNORECASE,
)
# A code-site citation: `path/to/file.py:4207` or `file.py:232-246`. Normalized to basename:first-line
# so a notes basename ("media_buy_create.py:4207") matches an artifact full path.
SITE_TOKEN = re.compile(r"[\w./-]*?([\w-]+\.py):(\d+)(?:-\d+)?")


def site_tokens(text: str) -> set[tuple[str, int]]:
    """Pure: every code-site citation in the text, normalized to (basename, first-line)."""
    return {(m.group(1), int(m.group(2))) for m in SITE_TOKEN.finditer(text)}


def dropped_sites(notes_text: str, artifact_text: str) -> list[tuple[str, int]]:
    """Pure: sites cited in the notes but absent from the shipped artifact (the #1534 site drop)."""
    return sorted(site_tokens(notes_text) - site_tokens(artifact_text))


def audit(text: str) -> dict:
    """Pure: parse a review artifact, return the contract-violation worklist."""
    findings = FINDING_TAG.findall(text)
    n_findings = len(findings)
    n_dispositions = len(DISPOSITION_TOKENS.findall(text))
    has_ledger = bool(LEDGER_HEADING.search(text))
    banned_hits = [
        (i, ln.strip())
        for i, ln in enumerate(text.splitlines(), 1)
        if BANNED.search(ln)
    ]
    internal_vocab_hits = [
        (i, ln.strip())
        for i, ln in enumerate(text.splitlines(), 1)
        if INTERNAL_VOCAB.search(ln)
    ]
    # Coverage deficit: findings with no resolved next-action anywhere in the artifact.
    deficit = max(0, n_findings - n_dispositions)
    return {
        "n_findings": n_findings,
        "n_dispositions": n_dispositions,
        "has_ledger": has_ledger,
        "deficit": deficit,
        "banned_hits": banned_hits,
        "internal_vocab_hits": internal_vocab_hits,
    }


def _is_clean(r: dict) -> bool:
    # A report with findings must carry a ledger AND cover every finding AND use no banned
    # disposition. A report with zero findings is vacuously clean for the drop channels — but the
    # §1.9 internal-vocab leak is independent of findings, so it gates either way.
    if r["n_findings"] == 0:
        return not r["banned_hits"] and not r["internal_vocab_hits"]
    return (
        r["has_ledger"]
        and r["deficit"] == 0
        and not r["banned_hits"]
        and not r["internal_vocab_hits"]
    )


def _report(r: dict) -> None:
    print(f"findings (severity-tagged): {r['n_findings']}")
    print(f"dispositions resolved:      {r['n_dispositions']}")
    print(f"Actions ledger present:     {r['has_ledger']}")
    if r["n_findings"] and not r["has_ledger"]:
        print("  ✗ LEDGER-ABSENT: no Actions section (§4b.5) — findings have no resolved state; "
              "this is the drop channel.")
    if r["deficit"]:
        print(f"  ✗ DISPOSITION-DEFICIT: {r['deficit']} finding(s) carry no disposition "
              "(inline §3 or ledger). These are the silently-dropped ones.")
    if r["banned_hits"]:
        print(f"  ✗ BANNED-AS-DISPOSITION ({len(r['banned_hits'])} line(s)) — §1.8; "
              "adjudicate quote-of-reviewer vs a real 'optional' bucket:")
        for i, ln in r["banned_hits"][:12]:
            print(f"      L{i}: {ln[:110]}")
    if r["internal_vocab_hits"]:
        print(f"  ✗ INTERNAL-VOCAB ({len(r['internal_vocab_hits'])} line(s)) — §1.9; internal harness / "
              "quality-bar vocabulary ('gold standard', review-workings, detector names) must not appear in a "
              "public artifact, even when echoing the request's framing. Adjudicate quote-vs-leak:")
        for i, ln in r["internal_vocab_hits"][:12]:
            print(f"      L{i}: {ln[:110]}")


def selftest() -> int:
    good = (
        "## Summary: 0 BLOCKER / 1 SHOULD-FIX / 1 NIT\n"
        "**[SHOULD-FIX · code-patterns] CP1 helper dup** — `foo.py:52`.\n"
        "- Disposition: FIX-NOW\n"
        "**[NIT · bdd] BDD1 dispatch dup** — `bar.py:235`.\n"
        "- Disposition: FOLD-IN\n"
        "## Actions\n"
        "- CP1 → done\n"
        "- BDD1 → folded-in\n"
    )
    bad = (
        "## Summary: 0 BLOCKER / 3 SHOULD-FIX\n"
        "**[SHOULD-FIX] CP1 helper dup** — `foo.py:52`.\n"
        "**[NIT] BDD1 dispatch dup** — `bar.py:235`.\n"
        "**[NIT] N3 basename collision** — `baz.py`.\n"
        "SHOULD-FIX (all optional / non-gating): the above.\n"  # banned + no ledger + no dispositions
    )
    empty = "## Summary: 0 BLOCKER / 0 SHOULD-FIX / 0 NIT\nNo findings.\n"
    # §1.9 leak: zero findings, but internal quality-bar / workings vocabulary echoed into the
    # (would-be public) artifact — must gate even though there is nothing to "drop" (PR #1575).
    leaky = (
        "## Summary: 0 BLOCKER / 0 SHOULD-FIX / 0 NIT\n"
        "The change meets our gold standard; the specialist reviewers and disposition_ledger agree.\n"
    )

    rg, rb, re_, rl = audit(good), audit(bad), audit(empty), audit(leaky)
    # SITE-DROP: notes cite 3 sites; the artifact ships only 2 (the #1534 site collapse).
    notes = "H3 dup at exceptions.py:971, app.py:246, and media_buy_create.py:4207 (3rd, thinner)."
    artifact = "The shape has two homes: exceptions.py:971 and app.py:246. Disposition: FOLD-IN."
    drops = dropped_sites(notes, artifact)
    ok = (
        _is_clean(rg)
        and not _is_clean(rb)
        and rb["deficit"] >= 1          # 3 findings, 0 dispositions
        and not rb["has_ledger"]        # no Actions section
        and len(rb["banned_hits"]) >= 1  # "optional / non-gating"
        and _is_clean(re_)              # zero findings ⇒ vacuously clean
        and not _is_clean(rl)           # §1.9: internal-vocab leak gates despite zero findings
        and len(rl["internal_vocab_hits"]) >= 1  # "gold standard" + workings/detector names
        and not rg["internal_vocab_hits"]        # clean report has no false positive
        and drops == [("media_buy_create.py", 4207)]   # the 3rd site, dropped notes→artifact
    )
    print("── GOOD report ──")
    _report(rg)
    print("\n── BAD report ──")
    _report(rb)
    print("\n── EMPTY report ──")
    _report(re_)
    print("\n── LEAKY report (internal vocab, zero findings) ──")
    _report(rl)
    print(f"\n── SITE-DROP (notes→artifact) ──\n  dropped: {drops}")
    print("\nself-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _newest_report() -> Path | None:
    root = Path.cwd() / ".claude" / "reports"
    reports = sorted(root.glob("full-review-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[0] if reports else None


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    notes_path = None
    if "--notes" in argv:
        i = argv.index("--notes")
        notes_path = argv[i + 1] if i + 1 < len(argv) else None
    args = [a for a in argv if not a.startswith("-") and a != notes_path]
    target = Path(args[0]) if args else _newest_report()
    if target is None:
        print("ERROR: no report path given and no .claude/reports/full-review-*.md found "
              "(run from repo root).", file=sys.stderr)
        return 2
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: could not read {target}: {exc}", file=sys.stderr)
        return 2

    print(f"disposition-ledger audit — {target}\n")
    r = audit(text)
    _report(r)

    drops: list[tuple[str, int]] = []
    if notes_path:
        try:
            notes_text = Path(notes_path).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: could not read notes {notes_path}: {exc}", file=sys.stderr)
            return 2
        drops = dropped_sites(notes_text, text)
        print(f"\nSite-drop cross-check vs {notes_path}:")
        if drops:
            print(f"  ✗ SITE-DROP ({len(drops)}) — cited in the notes, absent from the artifact "
                  "(the #1534 site collapse). Adjudicate each: legit consolidation, or a dropped site?")
            for base, line in drops:
                print(f"      {base}:{line}")
        else:
            print("  every code-site cited in the notes survives into the artifact.")

    if _is_clean(r) and not drops:
        print("\nContract met: every finding resolves to an action; no banned disposition; no dropped site.")
        return 0
    print(
        "\nWorklist — a finding with no resolved next-action gets dropped (the #1547 miss-class) and "
        "'optional / non-gating' launders the drop; a site cited in notes but missing from the artifact "
        "is the #1534 site drop; internal-vocab ('gold standard', review-workings, detector names) is the "
        "#1575 §1.9 leak. Resolve each finding to done | folded-in | tracked(link) | won't-fix, one ledger "
        "ROW PER SITE (§4b.0/§4b.5), and strip internal vocabulary before this artifact ships."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
