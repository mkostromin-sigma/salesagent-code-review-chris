#!/usr/bin/env python3
"""PR-import-cycle detector — a newly-created import cycle papered over by a lazy import.

The trigger (an independent re-review of PR #1534): the PR made ``exceptions.py`` import
``first_validation_error_field`` from ``validation_helpers.py`` — but ``validation_helpers.py``
already imports ``normalize_to_adcp_error`` from ``exceptions.py`` at MODULE level. The new edge
would be an ``ImportError`` except that it's written LAZILY (inside the function body). So the PR
introduced a real 2-module cycle; the only thing hiding it is the deferred import.

The first review SAW the lazy import and rationalized it "circular import OK (lazy breaks cycle)",
invoking the standing heuristic *most lazy imports are load-bearing, don't hoist*. That heuristic
is about not REMOVING an existing lazy import — it got misapplied to a NEWLY-ADDED cycle, where
the right question is inverted: *should this PR create the cycle at all?* (The fix raised there:
relocate the pure, zero-dep function to a leaf module so no cycle exists.) No mechanism asked the
inverted question — this does.

Signal: a first-party 2-module pair {A, B} that import each other, where at least ONE direction
is LAZY-ONLY (imported only inside a function, never at module level). A lazy-only edge in a
cycle is the tell that the cycle is being deferred rather than designed away. A module-level↔
module-level cycle is a different (usually already-failing) problem and is reported separately.

WORKLIST, not a verdict: some lazy edges are legitimately load-bearing (genuine bidirectional
need, or breaking a cycle that can't be relocated). The human adjudicates each; the point is a
PR-introduced papered-over cycle stops being invisible. Pass ``--base <ref>`` to mark the cycles
that involve files changed vs that ref (the per-PR view) — those are the ones a review must judge.

Usage:
  python3 pr_import_cycle.py [--base origin/main] [pkg_root]   # default root: src
  python3 pr_import_cycle.py --selftest

Exit 1 if a papered-over cycle involves a changed file (with --base) or any exists (without);
0 if clean / selftest ok; 2 on error.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

# per-directed-edge kind
TOP, LAZY = "module-level", "lazy"


def _module_name(rel_path: str) -> str:
    """src/core/exceptions.py -> src.core.exceptions ; .../__init__.py -> package name."""
    p = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    p = p.replace("/", ".").replace("\\", ".")
    return p[: -len(".__init__")] if p.endswith(".__init__") else p


def _edges(module: str, source: str, known: set[str]) -> dict[str, str]:
    """Pure: first-party import edges module -> {target: TOP|LAZY}.

    An edge is TOP if the target is imported at module scope anywhere (module-level dominates);
    LAZY if it's only ever imported inside a function/method body.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    # mark every import node with whether it is nested inside a function
    lazy_nodes: set[int] = set()

    class _Walk(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0

        def _visit_fn(self, node: ast.AST) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_FunctionDef = _visit_fn  # type: ignore[assignment]
        visit_AsyncFunctionDef = _visit_fn  # type: ignore[assignment]

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self.depth > 0:
                lazy_nodes.add(id(node))
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            if self.depth > 0:
                lazy_nodes.add(id(node))
            self.generic_visit(node)

    _Walk().visit(tree)

    def _resolve(name: str) -> str | None:
        """Longest known-module prefix of a dotted target (a symbol import resolves to its module)."""
        if name in known:
            return name
        parts = name.split(".")
        for i in range(len(parts) - 1, 0, -1):
            cand = ".".join(parts[:i])
            if cand in known:
                return cand
        return None

    edges: dict[str, str] = {}
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            # `from M import N`: N may be a submodule (M.N) or a symbol (resolves to M).
            for alias in node.names:
                resolved = _resolve(f"{node.module}.{alias.name}") or _resolve(node.module)
                if resolved:
                    targets.append(resolved)
        elif isinstance(node, ast.Import):
            targets = [t for t in (_resolve(a.name) for a in node.names) if t]
        else:
            continue
        kind = LAZY if id(node) in lazy_nodes else TOP
        for tgt in targets:
            if tgt and tgt != module:
                # module-level dominates: never downgrade an existing TOP to LAZY
                if edges.get(tgt) != TOP:
                    edges[tgt] = kind
    return edges


def audit(files: dict[str, str], changed: set[str] | None = None) -> dict:
    """Pure: {module: source} -> papered-over + hard cycles. `changed` = changed module names."""
    known = set(files)
    graph: dict[str, dict[str, str]] = {m: _edges(m, src, known) for m, src in files.items()}

    papered, hard = [], []
    seen: set[frozenset] = set()
    for a, out in graph.items():
        for b, kind_ab in out.items():
            kind_ba = graph.get(b, {}).get(a)
            if kind_ba is None:
                continue  # not a cycle
            pair = frozenset((a, b))
            if pair in seen:
                continue
            seen.add(pair)
            entry = (a, kind_ab, b, kind_ba)
            if LAZY in (kind_ab, kind_ba):
                papered.append(entry)
            else:
                hard.append(entry)

    def _touches(entry: tuple) -> bool:
        return changed is not None and (entry[0] in changed or entry[2] in changed)

    return {
        "papered": sorted(papered),
        "hard": sorted(hard),
        "changed_papered": sorted(e for e in papered if _touches(e)),
        "scoped": changed is not None,
    }


def _fmt(entry: tuple) -> str:
    a, kab, b, kba = entry
    return f"{a}  --[{kab}]-->  {b}   and   {b}  --[{kba}]-->  {a}"


def _report(r: dict) -> None:
    if r["papered"]:
        print(f"✗ PAPERED-OVER CYCLES ({len(r['papered'])}) — a 2-module cycle held together only "
              "by a lazy (in-function) import. Hoisting the lazy edge would ImportError (the #1534 "
              "class). Adjudicate: relocate a leaf symbol to break it, or confirm it's designed.")
        for e in r["papered"]:
            mark = "  ⟵ involves a changed file" if r["scoped"] and (e in r["changed_papered"]) else ""
            print(f"    {_fmt(e)}{mark}")
    if r["hard"]:
        print(f"\n· MODULE-LEVEL CYCLES ({len(r['hard'])}) — both directions import at module scope; "
              "usually already an ImportError risk. Report only:")
        for e in r["hard"]:
            print(f"    {_fmt(e)}")
    if not (r["papered"] or r["hard"]):
        print("No first-party import cycles found.")


def selftest() -> int:
    files = {
        # a imports b at module level; b imports a only inside a function -> papered-over {a,b}
        "src.core.mod_a": "from src.core.mod_b import thing\n\ndef f():\n    return thing\n",
        "src.core.mod_b": "def g():\n    from src.core.mod_a import other\n    return other\n",
        # c -> d one way only: no cycle
        "src.core.mod_c": "from src.core.mod_d import q\n",
        "src.core.mod_d": "def h():\n    return 1\n",
    }
    r = audit(files, changed={"src.core.mod_a"})
    scoped = audit(files, changed={"src.core.mod_c"})
    ok = (
        len(r["papered"]) == 1
        and set(r["papered"][0][:3:2]) == {"src.core.mod_a", "src.core.mod_b"}
        and not r["hard"]
        and len(r["changed_papered"]) == 1          # mod_a is in the cycle and changed
        and not scoped["changed_papered"]           # mod_c is changed but not in any cycle
    )
    print("── synthetic graph (mod_a ↔ mod_b via lazy edge; mod_c→mod_d acyclic) ──")
    _report(r)
    print("\nself-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _changed_modules(base: str, root: str) -> set[str] | None:
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    mods = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(f"{root}/") and line.endswith(".py"):
            mods.add(_module_name(line))
    return mods


def _scan(root: str) -> dict[str, str]:
    cwd, base = Path.cwd(), Path.cwd() / root
    files: dict[str, str] = {}
    if base.exists():
        for py in base.rglob("*.py"):
            try:
                files[_module_name(str(py.relative_to(cwd)))] = py.read_text(encoding="utf-8")
            except OSError:
                continue
    return files


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    base = None
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1] if i + 1 < len(argv) else None
    positional = [a for a in argv if not a.startswith("-") and a != base]
    root = positional[0] if positional else "src"
    files = _scan(root)
    if not files:
        print(f"ERROR: no .py files under {root}/ (run from repo root).", file=sys.stderr)
        return 2
    changed = _changed_modules(base, root) if base else None
    print(f"pr-import-cycle — {len(files)} modules under {root}/"
          + (f"; changed vs {base}: {len(changed)}" if changed is not None else "") + "\n")
    r = audit(files, changed)
    _report(r)
    fire = bool(r["changed_papered"]) if r["scoped"] else bool(r["papered"])
    if fire:
        print("\nWorklist: a lazy import is the only thing preventing an ImportError for the cycle(s) "
              "above. If this PR introduced one, prefer relocating a leaf symbol over deferring the "
              "import. Cycles not touching changed files are pre-existing context.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
