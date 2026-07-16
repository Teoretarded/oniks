"""Focused contracts for the bounded flight-computer sweep tool."""

import csv
import io
import json
import math

from tools import sweep_flight_computer as sweep


def test_quick_matrix_is_exactly_bounded_and_covers_every_axis():
    cases = sweep.generate_cases("quick", "oniks", "hi-lo")
    assert len(cases) == sweep.MAX_QUICK_CASES == 64
    assert [case.case_id for case in cases[:3]] == [
        "q00000", "q00001", "q00002"]
    assert {case.allow_high for case in cases} == {False, True}
    assert {case.route_kind for case in cases} == {
        sweep.ROUTE_STRAIGHT, sweep.ROUTE_DOGLEG_45}
    assert len({case.launch_alt_m for case in cases}) == 2
    assert len({case.range_m for case in cases}) == 2
    assert len({case.initial_mach for case in cases}) == 2
    assert len({case.target_alt_m for case in cases}) == 2


def test_full_matrix_expands_quick_but_stays_under_hard_bound():
    quick = sweep.generate_cases("quick", "oniks", "hi-lo")
    full = sweep.generate_cases("full", "oniks", "hi-lo")
    assert len(quick) < len(full) <= sweep.MAX_FULL_CASES
    assert len(full) == 3_600
    assert full[0].case_id == "f00000"
    assert full[-1].case_id == f"f{len(full) - 1:05d}"


def test_dogleg_routes_are_longer_than_the_same_straight_range():
    base = sweep.SweepCase(
        "q00000", "oniks", "hi-lo", "quick", 60.0, 100_000.0,
        2.0, 0.0, sweep.ROUTE_STRAIGHT, True)
    straight = sweep.route_for_case(base)
    dogleg = sweep.route_for_case(
        sweep.SweepCase(
            "q00001", "oniks", "hi-lo", "quick", 60.0, 100_000.0,
            2.0, 0.0, sweep.ROUTE_DOGLEG_90, True))
    pos = (0.0, 60.0, 0.0)
    assert sweep.route_arc_length_m(pos, straight) == 100_000.0
    assert sweep.route_arc_length_m(pos, dogleg) > 100_000.0


def test_evaluate_case_reports_candidate_terminal_energy_and_failures():
    case = sweep.generate_cases("quick", "oniks", "hi-lo")[0]
    row = sweep.evaluate_case(case)
    assert tuple(row) == sweep.CSV_FIELDS
    assert row["selected_candidate"] in {
        "deck", "preferred", "hold", "mid", "direct"}
    assert row["rollout_samples"] <= 256
    assert math.isfinite(row["terminal_specific_energy_jkg"])
    assert math.isfinite(row["energy_margin_jkg"])
    assert row["terminal_mach"] > 0.0
    assert row["failures"] == "NONE" or row["failures"]


def test_case_evaluation_is_deterministic():
    case = sweep.generate_cases("quick", "zircon", "hi-lo")[17]
    assert sweep.evaluate_case(case) == sweep.evaluate_case(case)


def test_run_limit_is_a_hard_ordered_bound():
    cases = sweep.generate_cases("quick", "tomahawk")
    rows = sweep.run_sweep(cases, limit=3)
    assert [row["case_id"] for row in rows] == [
        "q00000", "q00001", "q00002"]


def test_summary_counts_candidates_and_each_failure_code():
    rows = [
        {"selected_candidate": "deck", "command_mode": "CRUISE",
         "failures": "NONE", "feasible": True, "energy_margin_jkg": 10.0},
        {"selected_candidate": "deck", "command_mode": "DESCEND",
         "failures": "ENERGY;FUEL_RESERVE", "feasible": False,
         "energy_margin_jkg": -20.0},
    ]
    summary = sweep.summarize(rows)
    assert summary["cases"] == 2
    assert summary["feasible"] == 1 and summary["infeasible"] == 1
    assert summary["candidate_counts"] == {"deck": 2}
    assert summary["failure_counts"] == {"ENERGY": 1, "FUEL_RESERVE": 1}


def test_csv_output_has_stable_columns_and_rows():
    rows = sweep.run_sweep(sweep.generate_cases("quick")[:2])
    text = sweep.csv_text(rows)
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert tuple(parsed[0]) == sweep.CSV_FIELDS
    assert [row["case_id"] for row in parsed] == ["q00000", "q00001"]


def test_json_output_contains_metadata_summary_and_ordered_cases():
    rows = sweep.run_sweep(sweep.generate_cases("quick")[:2])
    metadata = {
        "mode": "quick", "weapon": "oniks", "profile": "hi-lo",
        "generated_cases": 64, "evaluated_cases": 2, "case_bound": 64,
    }
    payload = json.loads(sweep.json_text(rows, metadata))
    assert payload["metadata"] == metadata
    assert payload["summary"]["cases"] == 2
    assert [case["case_id"] for case in payload["cases"]] == [
        "q00000", "q00001"]


def test_cli_writes_bounded_json_and_honors_infeasible_exit(tmp_path):
    output = tmp_path / "sweep.json"
    rc = sweep.main([
        "--mode", "quick", "--weapon", "oniks", "--format", "json",
        "--output", str(output), "--limit", "2",
    ])
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["metadata"]["evaluated_cases"] == 2
    assert len(payload["cases"]) == 2

    # A deliberately starved/high-energy corner may or may not be feasible as
    # tuning evolves, so exercise the flag against the already-evaluated rows.
    expected = int(any(not row["feasible"] for row in payload["cases"]))
    rc = sweep.main([
        "--mode", "quick", "--weapon", "oniks", "--format", "json",
        "--output", str(output), "--limit", "2", "--fail-on-infeasible",
    ])
    assert rc == expected

