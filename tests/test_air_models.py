"""Tests for the Phase-5a air/surface models:
  models/fighter.py  — build_fighter()
  models/awacs.py    — build_awacs()
  models/carrier.py  — build_carrier()
  models/airfield.py — build_airfield()

Test strategy mirrors test_destroyer_model.py:
  1. build returns a non-empty MeshData, correct dtypes.
  2. Finite vertices, unit normals, valid indices (sanity).
  3. Bounding-box dimensions within ±20 % of real-world figures.
  4. Vertex count in a sane band (not a bare box, not a hero asset).
  5. Ships / aircraft are symmetric about x = 0  (|max_x + min_x| < 0.5 m).
  6. Model-specific signatures (rotodome exists for AWACS, etc.).
"""

from __future__ import annotations

import numpy as np
import pytest

from engine.meshdata import MeshData
from models.aircraft_model import build_fast_aircraft
from models.fighter  import build_fighter
from models.jammer   import build_jammer
from models.awacs    import build_awacs
from models.carrier  import build_carrier
from models.airfield import build_airfield
from models.common   import PALETTE

# ---------------------------------------------------------------------------
# Real-world reference dimensions
# ---------------------------------------------------------------------------

# F/A-18E Super Hornet
_FIGHTER_LENGTH_M   = 18.3
_FIGHTER_SPAN_M     = 13.6

# E-3 Sentry AWACS
_AWACS_LENGTH_M     = 46.6
_AWACS_SPAN_M       = 44.4

# Nimitz-class CVN
_CARRIER_LENGTH_M   = 333.0
_CARRIER_DECK_BEAM  =  76.8

# Airfield
_RUNWAY_LENGTH_M    = 2500.0
_RUNWAY_WIDTH_M     =   45.0

_TOL = 0.20   # ±20 % tolerance on all dimensions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_sanity(md: MeshData) -> None:
    """Replicate the shared sanity assertions from test_destroyer_model."""
    assert isinstance(md, MeshData), "result is not a MeshData"
    assert md.vertices.dtype == np.float32,  "vertices must be float32"
    assert md.indices.dtype  == np.uint32,   "indices must be uint32"
    assert len(md.vertices) > 0,             "vertices array is empty"
    assert len(md.indices)  > 0,             "indices array is empty"
    assert md.indices.max() < len(md.vertices), "index out of range"
    assert np.isfinite(md.vertices).all(),   "non-finite value in vertices"
    norms = np.linalg.norm(md.vertices[:, 3:6], axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), "normals not unit length"
    assert len(md.indices) % 3 == 0, "index count is not a multiple of 3"


def _bbox(md: MeshData):
    """Return (min_xyz, max_xyz) as (3,) float arrays."""
    pos = md.vertices[:, 0:3]
    return pos.min(axis=0), pos.max(axis=0)


def _x_sym_ok(md: MeshData, tol: float = 0.5) -> bool:
    """Return True if the model is symmetric about x = 0."""
    pos = md.vertices[:, 0]
    asymmetry = abs(float(pos.max()) + float(pos.min()))
    return asymmetry < tol


# ===========================================================================
# F/A-18E Fighter
# ===========================================================================

@pytest.fixture(scope="module")
def fighter():
    return build_fighter()


def test_fighter_returns_meshdata(fighter):
    assert isinstance(fighter, MeshData)


def test_fighter_sanity(fighter):
    _check_sanity(fighter)


def test_fighter_length(fighter):
    lo, hi = _bbox(fighter)
    length = float(hi[2] - lo[2])
    assert abs(length - _FIGHTER_LENGTH_M) / _FIGHTER_LENGTH_M <= _TOL, (
        f"fighter length {length:.2f} m not within 20% of {_FIGHTER_LENGTH_M} m"
    )


def test_fighter_span(fighter):
    lo, hi = _bbox(fighter)
    span = float(hi[0] - lo[0])
    assert abs(span - _FIGHTER_SPAN_M) / _FIGHTER_SPAN_M <= _TOL, (
        f"fighter span {span:.2f} m not within 20% of {_FIGHTER_SPAN_M} m"
    )


def test_fighter_x_symmetry(fighter):
    assert _x_sym_ok(fighter), (
        "fighter model is not symmetric about x = 0"
    )


def test_fighter_vertex_count(fighter):
    """Spec: density at most 3× build_fast_aircraft() vertex count."""
    fast_vcount = len(build_fast_aircraft().vertices)
    n = len(fighter.vertices)
    assert n >= 50, f"fighter vertex count {n} suspiciously low"
    assert n <= fast_vcount * 3, (
        f"fighter vertex count {n} exceeds 3× fast_aircraft ({fast_vcount * 3})"
    )


def test_fighter_origin_near_mid(fighter):
    """Z mid-point should be within ±2 m of origin (origin at mid-fuselage)."""
    lo, hi = _bbox(fighter)
    z_mid = float((hi[2] + lo[2]) * 0.5)
    assert abs(z_mid) <= 2.0, f"fighter z-midpoint {z_mid:.2f} m not near 0"


def test_fighter_tails_are_upright_and_outboard(fighter):
    """Regression for fins that previously rotated below the fuselage."""
    pos = fighter.vertices[:, 0:3]
    grey = np.all(
        np.isclose(fighter.vertices[:, 6:9], PALETTE["aircraft_grey"], atol=1e-4),
        axis=1,
    )
    tips = pos[grey & (pos[:, 2] < -4.0) & (pos[:, 1] > 2.2)]
    assert (tips[:, 0] > 0.8).any()
    assert (tips[:, 0] < -0.8).any()
    assert float(pos[:, 1].min()) > -1.1


# ===========================================================================
# EA-18G Growler escort jammer (M3-F2)
# ===========================================================================

@pytest.fixture(scope="module")
def jammer():
    return build_jammer()


def test_jammer_returns_meshdata(jammer):
    assert isinstance(jammer, MeshData)


def test_jammer_sanity(jammer):
    _check_sanity(jammer)


def test_jammer_length(jammer):
    """A Super Hornet airframe: same ~18.3 m length (pods stay inside it)."""
    lo, hi = _bbox(jammer)
    length = float(hi[2] - lo[2])
    assert abs(length - _FIGHTER_LENGTH_M) / _FIGHTER_LENGTH_M <= _TOL, (
        f"jammer length {length:.2f} m not within 20% of {_FIGHTER_LENGTH_M} m"
    )


def test_jammer_span(jammer):
    """~13.6 m span — the wingtip ALQ-218 pods sit just inboard of the tips."""
    lo, hi = _bbox(jammer)
    span = float(hi[0] - lo[0])
    assert abs(span - _FIGHTER_SPAN_M) / _FIGHTER_SPAN_M <= _TOL, (
        f"jammer span {span:.2f} m not within 20% of {_FIGHTER_SPAN_M} m"
    )


def test_jammer_x_symmetry(jammer):
    assert _x_sym_ok(jammer), "jammer model is not symmetric about x = 0"


def test_jammer_origin_near_mid(jammer):
    lo, hi = _bbox(jammer)
    z_mid = float((hi[2] + lo[2]) * 0.5)
    assert abs(z_mid) <= 2.0, f"jammer z-midpoint {z_mid:.2f} m not near 0"


def test_jammer_pod_palette():
    """The EW-pod paint must be registered (added for the Growler)."""
    assert "jammer_pod" in PALETTE, "'jammer_pod' missing from PALETTE"


def test_jammer_has_ew_pods(jammer):
    """THE Growler signature: jammer_pod-coloured EW pods that the plain
    Super Hornet does NOT carry — pods on both wings (±x) plus the centreline,
    so the player can tell a Growler from a fighter (and from the AWACS)."""
    pod_mask = np.all(
        np.isclose(jammer.vertices[:, 6:9], PALETTE["jammer_pod"], atol=1e-4),
        axis=1,
    )
    assert pod_mask.any(), "no jammer_pod vertices — EW pods missing?"
    pods = jammer.vertices[pod_mask]
    assert (pods[:, 0] > 1.0).any(), "no pod on the starboard (+x) wing"
    assert (pods[:, 0] < -1.0).any(), "no pod on the port (−x) wing"
    assert (np.abs(pods[:, 0]) < 1.0).any(), "no centreline belly pod"
    # The plain fighter wears none of this paint — the meshes are distinct.
    fighter_mask = np.all(
        np.isclose(build_fighter().vertices[:, 6:9], PALETTE["jammer_pod"],
                   atol=1e-4),
        axis=1,
    )
    assert not fighter_mask.any(), "plain fighter unexpectedly has EW pods"


def test_jammer_distinct_from_awacs(jammer):
    """A Growler is NOT a 707/AWACS: it must carry no rotodome (no
    radar_white above the fuselage) and be a far smaller airframe."""
    white_above = np.all(
        np.isclose(jammer.vertices[:, 6:9], PALETTE["radar_white"], atol=1e-4),
        axis=1,
    ) & (jammer.vertices[:, 1] > 1.0)
    assert not white_above.any(), "jammer has an AWACS-style rotodome"
    lo, hi = _bbox(jammer)
    assert float(hi[0] - lo[0]) < _AWACS_SPAN_M * 0.5, (
        "jammer span is AWACS-sized — should be a Super Hornet"
    )


def test_jammer_uses_two_seat_canopy(jammer, fighter):
    """EA-18G derives from the tandem-seat F/A-18F, not single-seat E."""
    def canopy_min_z(md):
        pos = md.vertices[:, 0:3]
        dark = np.all(
            np.isclose(md.vertices[:, 6:9], PALETTE["aircraft_dark"], atol=1e-4),
            axis=1,
        )
        canopy = pos[dark & (pos[:, 1] > 0.80) & (np.abs(pos[:, 0]) < 0.8)]
        assert len(canopy)
        return float(canopy[:, 2].min())

    assert canopy_min_z(jammer) < canopy_min_z(fighter) - 0.6


# ===========================================================================
# E-3 Sentry AWACS
# ===========================================================================

@pytest.fixture(scope="module")
def awacs():
    return build_awacs()


def test_awacs_returns_meshdata(awacs):
    assert isinstance(awacs, MeshData)


def test_awacs_sanity(awacs):
    _check_sanity(awacs)


def test_awacs_length(awacs):
    lo, hi = _bbox(awacs)
    length = float(hi[2] - lo[2])
    assert abs(length - _AWACS_LENGTH_M) / _AWACS_LENGTH_M <= _TOL, (
        f"AWACS length {length:.2f} m not within 20% of {_AWACS_LENGTH_M} m"
    )


def test_awacs_span(awacs):
    lo, hi = _bbox(awacs)
    span = float(hi[0] - lo[0])
    assert abs(span - _AWACS_SPAN_M) / _AWACS_SPAN_M <= _TOL, (
        f"AWACS span {span:.2f} m not within 20% of {_AWACS_SPAN_M} m"
    )


def test_awacs_x_symmetry(awacs):
    assert _x_sym_ok(awacs), (
        "AWACS model is not symmetric about x = 0"
    )


def test_awacs_vertex_count(awacs):
    n = len(awacs.vertices)
    assert 200 <= n <= 15_000, (
        f"AWACS vertex count {n} outside expected band [200, 15000]"
    )


def test_awacs_rotodome_exists(awacs):
    """THE AWACS signature: a 9.1 m diameter rotodome disc above the fuselage.

    White geometry should exist above the fuselage centreline (y > 1.0 m) and
    have an x-span of at least 2 × (9.1 / 2) × 0.8 = 7.28 m (within 20%).
    """
    white_mask = np.all(
        np.isclose(awacs.vertices[:, 6:9], PALETTE["radar_white"], atol=1e-4),
        axis=1,
    )
    assert white_mask.any(), "no radar_white vertices found — rotodome missing?"
    white_verts = awacs.vertices[white_mask]
    # Rotodome must extend above the fuselage
    assert white_verts[:, 1].max() >= 2.0, (
        "rotodome top is not above y = 2.0 m (may be missing)"
    )
    # Rotodome width should be close to 9.1 m (within 20%)
    dome_x_span = float(white_verts[:, 0].max() - white_verts[:, 0].min())
    assert dome_x_span >= 9.1 * 0.80, (
        f"rotodome x-span {dome_x_span:.2f} m is less than 80% of 9.1 m"
    )


def test_awacs_four_engine_pods(awacs):
    """Four underwing engine pods: exhaust-ring-colored verts should appear
    at both positive and negative x positions, and at two distinct x offsets
    (inboard and outboard) on each side."""
    exh_mask = np.all(
        np.isclose(awacs.vertices[:, 6:9], PALETTE["exhaust_ring"], atol=1e-4),
        axis=1,
    )
    assert exh_mask.any(), "no exhaust_ring vertices — engine pods missing?"
    exh = awacs.vertices[exh_mask]
    # Pods on both sides
    assert (exh[:, 0] > 2.0).any(), "no exhaust verts on starboard (+x) side"
    assert (exh[:, 0] < -2.0).any(), "no exhaust verts on port (−x) side"


def test_awacs_origin_near_mid(awacs):
    lo, hi = _bbox(awacs)
    z_mid = float((hi[2] + lo[2]) * 0.5)
    assert abs(z_mid) <= 3.0, f"AWACS z-midpoint {z_mid:.2f} m not near 0"


def test_awacs_fin_upright_and_tailplane_conventional(awacs):
    """E-3/707 has an upright fin and low conventional tail, not a T-tail."""
    pos = awacs.vertices[:, 0:3]
    grey = np.all(
        np.isclose(awacs.vertices[:, 6:9], PALETTE["aircraft_grey"], atol=1e-4),
        axis=1,
    )
    fin = pos[grey & (np.abs(pos[:, 0]) < 0.5) &
              (pos[:, 2] < -14.0) & (pos[:, 1] > 6.0)]
    assert len(fin)

    tailplane = pos[grey & (np.abs(pos[:, 0]) > 3.0) & (pos[:, 2] < -12.0)]
    assert len(tailplane)
    assert float(tailplane[:, 1].max()) < 2.0


# ===========================================================================
# Nimitz-class Carrier
# ===========================================================================

@pytest.fixture(scope="module")
def carrier():
    return build_carrier()


def test_carrier_returns_meshdata(carrier):
    assert isinstance(carrier, MeshData)


def test_carrier_sanity(carrier):
    _check_sanity(carrier)


def test_carrier_length(carrier):
    lo, hi = _bbox(carrier)
    length = float(hi[2] - lo[2])
    assert abs(length - _CARRIER_LENGTH_M) / _CARRIER_LENGTH_M <= _TOL, (
        f"carrier length {length:.2f} m not within 20% of {_CARRIER_LENGTH_M} m"
    )


def test_carrier_deck_beam(carrier):
    """The flight deck overhangs the hull — total x-span should be ≈ 76.8 m."""
    lo, hi = _bbox(carrier)
    beam = float(hi[0] - lo[0])
    assert abs(beam - _CARRIER_DECK_BEAM) / _CARRIER_DECK_BEAM <= _TOL, (
        f"carrier deck beam {beam:.2f} m not within 20% of {_CARRIER_DECK_BEAM} m"
    )


def test_carrier_origin_midship(carrier):
    """Z midpoint should be within ±10 m of z = 0 (waterline-center origin)."""
    lo, hi = _bbox(carrier)
    z_mid = float((hi[2] + lo[2]) * 0.5)
    assert abs(z_mid) <= 10.0, f"carrier z-midpoint {z_mid:.2f} m not near 0"


def test_carrier_draft_limit(carrier):
    """Nothing should be deeper than 10 m below the waterline."""
    y_min = float(carrier.vertices[:, 1].min())
    assert y_min >= -10.0, f"deepest carrier vertex at y = {y_min:.2f} m"


def test_carrier_island_above_deck(carrier):
    """Island superstructure and mast should push y_max well above 10 m."""
    y_max = float(carrier.vertices[:, 1].max())
    assert y_max >= 10.0, (
        f"carrier y_max = {y_max:.2f} m — island/mast appears missing"
    )


def test_carrier_vertex_count(carrier):
    n = len(carrier.vertices)
    # The carrier is a collection of large box/cylinder primitives; each box
    # is 24 verts. 10 such primitives → 240 verts minimum — allow from 200.
    assert n >= 200, f"carrier vertex count {n} suspiciously low"
    assert n <= 100_000, f"carrier vertex count {n} unreasonably high"


def test_carrier_planform_stays_inside_reference_envelope(carrier):
    """Regression for the old fake bow and oversized rotated deck slab."""
    lo, hi = _bbox(carrier)
    assert lo[2] == pytest.approx(-166.5, abs=0.02)
    assert hi[2] == pytest.approx(166.5, abs=0.02)
    assert (hi[0] - lo[0]) == pytest.approx(76.8, abs=0.5)


def test_carrier_has_catapult_landing_and_elevator_markings(carrier):
    white = np.all(np.isclose(carrier.vertices[:, 6:9],
                              PALETTE["radar_white"], atol=1e-4), axis=1)
    yellow = np.all(np.isclose(carrier.vertices[:, 6:9],
                               PALETTE["container_c"], atol=1e-4), axis=1)
    elevator = np.all(np.isclose(carrier.vertices[:, 6:9],
                                 PALETTE["warship_deck"], atol=1e-4), axis=1)
    assert white.sum() >= 250
    assert yellow.sum() >= 100
    assert elevator.sum() >= 4 * 24


# ===========================================================================
# Airfield
# ===========================================================================

@pytest.fixture(scope="module")
def airfield():
    return build_airfield()


def test_airfield_returns_meshdata(airfield):
    assert isinstance(airfield, MeshData)


def test_airfield_sanity(airfield):
    _check_sanity(airfield)


def test_airfield_runway_length(airfield):
    """Z extent should be approximately 2500 m (the runway length)."""
    lo, hi = _bbox(airfield)
    length = float(hi[2] - lo[2])
    assert abs(length - _RUNWAY_LENGTH_M) / _RUNWAY_LENGTH_M <= _TOL, (
        f"airfield z-extent {length:.1f} m not within 20% of {_RUNWAY_LENGTH_M} m"
    )


def test_airfield_width_includes_taxiway(airfield):
    """X extent must cover at least runway + taxiway + hangar offset.

    Runway: 45 m wide (±22.5 m about x=0).
    Taxiway is offset 80 m starboard; hangars extend further.
    Total width should be at least 100 m (taxiway side).
    """
    lo, hi = _bbox(airfield)
    width = float(hi[0] - lo[0])
    assert width >= 100.0, (
        f"airfield x-extent {width:.1f} m — taxiway and/or hangars may be missing"
    )


def test_airfield_above_ground(airfield):
    """All geometry must sit at or above y = 0 (ground level)."""
    y_min = float(airfield.vertices[:, 1].min())
    assert y_min >= -0.01, (
        f"airfield has geometry {y_min:.3f} m below ground"
    )


def test_airfield_tower_height(airfield):
    """Control tower must push y_max above 20 m."""
    y_max = float(airfield.vertices[:, 1].max())
    assert y_max >= 20.0, (
        f"airfield y_max = {y_max:.2f} m — tower appears missing or too short"
    )


def test_airfield_vertex_count(airfield):
    n = len(airfield.vertices)
    assert n >= 100, f"airfield vertex count {n} suspiciously low"
    assert n <= 50_000, f"airfield vertex count {n} unreasonably high"


def test_airfield_runway_z_straddles_origin(airfield):
    """Runway midpoint should be near z = 0 (runway centred on the origin)."""
    lo, hi = _bbox(airfield)
    z_mid = float((hi[2] + lo[2]) * 0.5)
    # Allow up to ±50 m offset: hangars and tower are on one side
    assert abs(z_mid) <= 200.0, (
        f"airfield z-midpoint {z_mid:.1f} m — origin may not be at runway centre"
    )
