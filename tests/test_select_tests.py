"""Impact-based test selection (tools/select_tests.py, 2026-07-17).

Locks the contracts that make the selector trustworthy as the AI inner
loop: path normalization on Windows, transitive closure over the REAL
repo import graph, depth limiting, the full-suite safety triggers, and
the changed-test-file passthrough."""

from tools.select_tests import _module_name, affected_tests, build_graph


def test_module_name_normalizes_separators():
    assert _module_name("sim\\ciws.py") == "sim.ciws"
    assert _module_name("sim/ciws.py") == "sim.ciws"
    assert _module_name("main.py") == "main"
    assert _module_name("docs/notes.md") is None
    assert _module_name("renders/x.py") is None


def test_direct_importer_selected():
    tests, reason = affected_tests(["sim/ciws.py"])
    assert reason is None
    assert "tests/test_sm2_ciws.py" in tests


def test_transitive_closure_reaches_integration_suites():
    # ciws -> enemy_defense -> world.combat -> the e2e suites.
    tests, _ = affected_tests(["sim/ciws.py"])
    assert "tests/test_phase6_e2e.py" in tests
    assert "tests/test_enemy_defense.py" in tests


def test_depth_limit_shrinks_selection():
    full, _ = affected_tests(["sim/ciws.py"])
    shallow, _ = affected_tests(["sim/ciws.py"], depth=2)
    assert set(shallow) <= set(full)
    assert len(shallow) < len(full)
    assert "tests/test_sm2_ciws.py" in shallow


def test_doc_change_selects_nothing():
    tests, reason = affected_tests(["docs/whatever.md"])
    assert reason is None and tests == []


def test_conftest_triggers_full_suite():
    tests, reason = affected_tests(["tests/conftest.py"])
    assert tests is None and "full suite" in reason


def test_changed_test_file_selects_itself():
    tests, _ = affected_tests(["tests/test_aero.py"])
    assert "tests/test_aero.py" in tests


def test_graph_is_nonempty_and_sane():
    mod_file, imports = build_graph()
    assert "sim.missile" in mod_file
    assert "sim.physics" in imports["sim.missile"]
