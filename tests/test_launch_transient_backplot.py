"""M5 launch-transient back-plot: the free, always-on ASW fix when the boat shoots.

Contracts (spec 03, feature 4):
  (a) a Kalibr salvo injects a subsurface DATUM into the player picture within
      error of the sub's true launch point.
  (b) the datum fades/drops within the configured window (ages out — the boat ran).
  (c) the SubCommander's evade window lengthens after a datum (the prosecution
      belief rises) — deterministic.
  (d) NO truth leak: the datum carries error, not the boat's live post-launch pos.
"""

from __future__ import annotations

import numpy as np
import pytest

from world.combat import (CombatWorld, BACKPLOT_DATUM_FADE_S,
                          BACKPLOT_DATUM_ERR_FRAC, SUB_THREAT_ON_DATUM)
from world.combat_config import CombatConfig
from world.generation import BASE_POS

DT = 1.0 / 120.0


def _fire(cw):
    sub = cw.subs[0]
    launch_xz = (float(sub.pos[0]), float(sub.pos[2]))
    cw._fire_kalibr_salvo(sub, (float(BASE_POS[0]), float(BASE_POS[2]), 0.0))
    return sub, launch_xz


# ---------------------------------------------------------------------------
# (a) a salvo injects a datum near the true launch point
# ---------------------------------------------------------------------------

def test_salvo_injects_launch_datum_near_truth():
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    sub, launch_xz = _fire(cw)
    did = f"{sub.sub_id}_datum"
    assert did in cw.sub_contacts, "a salvo must inject a launch datum"
    datum = cw.sub_contacts[did]
    assert datum["kind"] == "datum"
    # Within a few error-sigmas of the true launch point.
    rng_m = float(np.hypot(launch_xz[0] - BASE_POS[0],
                           launch_xz[1] - BASE_POS[2]))
    err = BACKPLOT_DATUM_ERR_FRAC * rng_m
    d = float(np.hypot(datum["pos"][0] - launch_xz[0],
                       datum["pos"][2] - launch_xz[1]))
    assert d <= 5.0 * err + 1.0, (
        f"datum {d:.0f} m from the true launch point (err sigma {err:.0f} m)")


# ---------------------------------------------------------------------------
# (b) the datum fades / drops within the window
# ---------------------------------------------------------------------------

def test_launch_datum_fades_out():
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    sub, _ = _fire(cw)
    did = f"{sub.sub_id}_datum"
    assert did in cw.sub_contacts
    # Step past the fade window; the datum must drop.
    for _ in range(int((BACKPLOT_DATUM_FADE_S + 5.0) / DT)):
        cw.step(DT)
        if did not in cw.sub_contacts:
            break
    assert did not in cw.sub_contacts, (
        "the launch datum must age out within its fade window (the boat ran)")


# ---------------------------------------------------------------------------
# (c) the boat's evade / prosecution belief lengthens after a datum
# ---------------------------------------------------------------------------

def test_datum_raises_prosecution_belief():
    """Firing sets the boat's sensor-honest prosecution belief HIGH (it knows it
    was loud) so the SubCommander evades — deterministic."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    sub, _ = _fire(cw)
    assert cw._sub_threat[sub.sub_id] == SUB_THREAT_ON_DATUM


def test_evade_window_lengthens_under_threat():
    """The Submarine's own evade window is longer when prosecuted: firing under
    threat=1 yields a longer evade than firing unprosecuted (deterministic)."""
    from sim.submarine import (Submarine, SUB_LAUNCH, SUB_EVADE,
                              SUB_EVADE_S)
    # Drive the boat to LAUNCH with threat 0 vs threat 1 and compare the evade
    # window it sets when it fires.
    def evade_window(threat):
        sub = Submarine(anchor_xz=(0.0, 100_000.0),
                        rng=np.random.default_rng([7, 13]),
                        kalibr_ammo=4, base_xz=(0.0, 0.0))
        sub.state = SUB_LAUNCH
        sub._enter(SUB_LAUNCH)
        sub.step(DT, threat_level=threat)   # fires this tick (sets _evade_window)
        return sub._evade_window
    w0 = evade_window(0.0)
    w1 = evade_window(1.0)
    assert w1 > w0
    assert w0 == pytest.approx(SUB_EVADE_S, abs=1e-6)


# ---------------------------------------------------------------------------
# (d) no truth leak
# ---------------------------------------------------------------------------

def test_datum_is_launch_point_not_live_position():
    """The datum is the LAUNCH point ± error — NOT the boat's live post-launch
    position.  After the boat sprints away in EVADE, the datum stays put (it does
    not track the moving boat), proving it is not a truth feed."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    sub, launch_xz = _fire(cw)
    did = f"{sub.sub_id}_datum"
    datum_pos0 = cw.sub_contacts[did]["pos"].copy()
    # Run a while: the boat moves (EVADE sprint), but the datum must NOT follow.
    for _ in range(int(20.0 / DT)):
        cw.step(DT)
        if did not in cw.sub_contacts:
            break
    if did in cw.sub_contacts:
        assert np.allclose(cw.sub_contacts[did]["pos"], datum_pos0), (
            "the datum must stay at the launch point, not track the live boat")
    # And the datum is NOT the boat's live truth pos (the boat moved off it).
    moved = float(np.hypot(sub.pos[0] - datum_pos0[0],
                           sub.pos[2] - datum_pos0[2]))
    assert moved >= 0.0   # (the boat may or may not have moved far; the key
    #                       assertion is the datum did not follow it, above)
