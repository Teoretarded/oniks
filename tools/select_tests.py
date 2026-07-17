"""Impact-based test selection: run the tests YOUR CHANGE touches, not all 1300.

usage:
    python -m tools.select_tests                 # select vs git working tree + HEAD~1
    python -m tools.select_tests --since REF     # select vs a git ref (e.g. HEAD~5)
    python -m tools.select_tests sim/ciws.py ... # explicit changed files
    python -m tools.select_tests --run [-- ...]  # and RUN pytest on the selection
                                                 # (extra args after -- go to pytest)
    python -m tools.select_tests --graph sim.ciws   # debug: who depends on this?
    python -m tools.select_tests --depth 2 sim/ciws.py  # only tests within 2
                                                 # import hops (fast inner loop;
                                                 # default = full closure)

How it works (pure static analysis, ~1 s, no pytest plugin):
  1. Parse EVERY repo .py with ``ast`` and record its imports (function-level
     lazy imports included — the codebase uses them heavily and they still
     appear as Import nodes in the tree).
  2. Build the reverse dependency graph over repo-local modules
     (sim/ world/ game/ engine/ models/ tests/ tools/ + main).
  3. Changed files -> their modules -> everything transitively importing
     them -> the TEST FILES in that closure (plus changed test files
     themselves).
  4. Print the selection; with ``--run`` execute
     ``pytest -q -n auto <selected...>``.

Safety rails (when in doubt, the answer is the FULL suite):
  * a change to conftest.py / pytest.ini / world/generation cache format or
    any non-Python file under sim|world|engine -> selects EVERYTHING;
  * a changed .py that maps to no known module (new file with no importers
    yet) still selects its own test file heuristically (tests/test_<stem>*).

This selects at FILE granularity — coarser than per-test but it turns the
hour-long wall into the handful of suites that can actually break, and the
full ``pytest -q -n auto`` stays the merge gate (run it before committing a
big change; this tool is the inner loop).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGES = ("sim", "world", "game", "engine", "models", "tests", "tools")
TOP_MODULES = ("main",)
# Files whose change invalidates everything.
FULL_SUITE_TRIGGERS = ("tests/conftest.py", "conftest.py", "pytest.ini")


def _module_name(path: str) -> str | None:
    """repo-relative path -> dotted module name, or None if outside scope."""
    rel = path.replace("\\", "/")
    if not rel.endswith(".py"):
        return None
    rel = rel[:-3]
    parts = rel.split("/")
    if parts[0] in PACKAGES or (len(parts) == 1 and parts[0] in TOP_MODULES):
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)
    return None


def _iter_repo_py():
    for pkg in PACKAGES:
        root = os.path.join(REPO, pkg)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                if fn.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), REPO)
                    yield rel.replace("\\", "/")
    for top in TOP_MODULES:
        p = os.path.join(REPO, top + ".py")
        if os.path.exists(p):
            yield top + ".py"


def _imports_of(path: str) -> set[str]:
    """Repo-local modules imported by ``path`` (any nesting level)."""
    try:
        with open(os.path.join(REPO, path), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()

    def _local(name: str) -> str | None:
        root = name.split(".")[0]
        if root in PACKAGES or root in TOP_MODULES:
            return name
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                m = _local(alias.name)
                if m:
                    found.add(m)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            m = _local(node.module)
            if m:
                found.add(m)
                # ``from sim import ew`` style: the names may be submodules.
                for alias in node.names:
                    found.add(f"{node.module}.{alias.name}")
    return found


def build_graph():
    """(module -> file, module -> set(imported modules)) for the whole repo."""
    mod_file: dict[str, str] = {}
    for path in _iter_repo_py():
        m = _module_name(path)
        if m:
            mod_file[m] = path
    imports: dict[str, set[str]] = {}
    for m, path in mod_file.items():
        imports[m] = {i for i in _imports_of(path) if i in mod_file}
    return mod_file, imports


def affected_tests(changed: list[str], depth: float = float("inf")):
    """(test_files, full_suite_reason) for a list of repo-relative paths.

    ``depth`` limits the reverse-import BFS (1 = tests importing a changed
    module directly, 2 = plus tests of its direct importers, ...).  The
    default full closure is the SAFE set; a shallow depth is the fast inner
    loop while iterating — always finish with the full closure (or suite)."""
    normalized = [c.replace("\\", "/") for c in changed]
    for c in normalized:
        if c in FULL_SUITE_TRIGGERS:
            return None, f"{c} changed: full suite"
        if (c.split("/")[0] in ("sim", "world", "engine")
                and not c.endswith(".py")):
            return None, f"non-Python change under {c.split('/')[0]}/: full suite"

    mod_file, imports = build_graph()
    # Reverse edges.
    rev: dict[str, set[str]] = {m: set() for m in mod_file}
    for m, deps in imports.items():
        for d in deps:
            rev.setdefault(d, set()).add(m)

    seeds = set()
    extra_tests = set()
    for c in normalized:
        m = _module_name(c)
        if m is None:
            continue                      # docs/renders/etc: no tests
        if m in mod_file:
            seeds.add(m)
        stem = os.path.splitext(os.path.basename(c))[0]
        if stem.startswith("test_"):
            extra_tests.add(c)
        else:
            # Heuristic net for brand-new modules nobody imports yet.
            guess = f"tests/test_{stem}.py"
            if os.path.exists(os.path.join(REPO, guess)):
                extra_tests.add(guess)

    # (Depth-limited) closure over reverse imports.
    hit = set(seeds)
    frontier = [(m, 0) for m in seeds]
    while frontier:
        m, d = frontier.pop()
        if d >= depth:
            continue
        for user in rev.get(m, ()):
            if user not in hit:
                hit.add(user)
                frontier.append((user, d + 1))

    tests = {mod_file[m] for m in hit
             if mod_file[m].startswith("tests/")
             and os.path.basename(mod_file[m]).startswith("test_")}
    tests |= extra_tests
    return sorted(tests), None


def changed_files(since: str | None) -> list[str]:
    ref = since or "HEAD~1"
    out = subprocess.run(
        ["git", "diff", "--name-only", ref], cwd=REPO,
        capture_output=True, text=True, check=True).stdout.split()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=REPO,
        capture_output=True, text=True, check=True).stdout.split()
    return sorted(set(out) | set(untracked))


def main(argv: list[str]) -> int:
    since = None
    run = False
    depth = float("inf")
    graph_query = None
    files: list[str] = []
    pytest_extra: list[str] = []
    it = iter(range(len(argv)))
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--since":
            i += 1
            since = argv[i]
        elif a == "--run":
            run = True
        elif a == "--graph":
            i += 1
            graph_query = argv[i]
        elif a == "--depth":
            i += 1
            depth = float(argv[i])
        elif a == "--":
            pytest_extra = argv[i + 1:]
            break
        else:
            files.append(a)
        i += 1

    if graph_query:
        mod_file, imports = build_graph()
        users = sorted(m for m, deps in imports.items() if graph_query in deps)
        print(f"direct importers of {graph_query}:")
        for u in users:
            print(f"  {u}")
        return 0

    if not files:
        files = changed_files(since)
    tests, reason = affected_tests(files, depth=depth)
    if reason is not None:
        print(f"[select_tests] {reason}")
        selection = ["tests"]
    elif not tests:
        print("[select_tests] no repo tests affected by:",
              ", ".join(files) or "(nothing changed)")
        return 0
    else:
        print(f"[select_tests] {len(files)} changed file(s) -> "
              f"{len(tests)} test file(s):")
        for t in tests:
            print(f"  {t}")
        selection = tests

    if run:
        cmd = [sys.executable, "-m", "pytest", "-q", "-n", "auto",
               *selection, *pytest_extra]
        print("[select_tests] running:", " ".join(cmd[2:]))
        return subprocess.call(cmd, cwd=REPO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
