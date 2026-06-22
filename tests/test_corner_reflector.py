"""M5 #5 — CORNER-REFLECTOR back-plot decoy (sim/decoys + world wiring).

The reflector works ONLY by planting a REAL sensor event: an EXTRA biased
BackPlotEntry (a real false-return geometry) injected through the SAME
add_back_plot path the enemy commander uses.  The enemy then acts on a NORMAL
LaunchCluster — there is NO "miss" flag, NO truth edit, and NO commander
decision-logic change.

Contracts (spec 06 F4):
  - a planted reflector biases the enemy back-plot so a LaunchCluster.centre
    forms within X m of the reflector (NOT the real pad), and a TLAM/JASSM salvo
    aims there -> _refine_strike_aim finds NO real structure within
    SEEKER_BASKET_M -> dirt (the real TEL survives);
  - the bias is a SENSOR-LEVEL plant (an added BackPlotEntry from a real
    geometry), provable by the enemy acting on a normal cluster — NOT a "miss";
  - the pure biased_back_plot helper reuses the SHARED back_plot_surface and
    returns the un-biased plot byte-for-byte with no reflector in range;
  - DETERMINISM: same seed -> same reflector placement + bias;
  - byte-identical default: n_corner_reflectors=0 injects NOTHING.
"""

from __future__ import annotations

import math

import numpy as np

from sim.commander import (
    EnemyPicture, back_plot_surface,
    BACKPLOT_CLUSTER_R_M, BACKPLOT_FIXES_NEEDED,
)
from sim.decoys import (
    CornerReflector, biased_back_plot, CR_INFLUENCE_M, CR_BIAS_FRAC,
)
from world.combat import CombatWorld, SEEKER_BASKET_M
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


# ---------------------------------------------------------------------------
# Pure biased_back_plot contracts
# ---------------------------------------------------------------------------

def _level_launch():
    """A real player Oniks: home-coast launch flying NORTH (vz > 0) as a level
    sea-skimmer, first detected a few km downrange.  back_plot_surface projects
    it back to ~the coast (the localizable case)."""
    first_pos = np.array([0.0, 30.0, 5_000.0], dtype=np.float64)
    first_vel = np.array([10.0, 0.0, 250.0], dtype=np.float64)
    return first_pos, first_vel


def test_biased_back_plot_no_reflector_is_unbiased():
    """No reflector / None -> the un-biased shared back_plot_surface byte-for-byte
    (the byte-identical regression seam)."""
    fp, fv = _level_launch()
    plain = back_plot_surface(fp, fv)
    assert biased_back_plot(fp, fv, None) == plain


def test_biased_back_plot_far_reflector_is_unbiased():
    """A reflector OUTSIDE its influence radius does not bias the plot."""
    fp, fv = _level_launch()
    plain = back_plot_surface(fp, fv)
    far = CornerReflector("cr", np.array([plain[0] + 9e9, 0.0, plain[1]]))
    assert biased_back_plot(fp, fv, far) == plain


def test_biased_back_plot_dead_reflector_is_unbiased():
    """A DEAD reflector (killed) stops biasing -> the un-biased plot."""
    fp, fv = _level_launch()
    plain = back_plot_surface(fp, fv)
    cr = CornerReflector("cr", np.array([plain[0] + 1_000.0, 0.0, plain[1]]))
    cr.alive = False
    assert biased_back_plot(fp, fv, cr) == plain


def test_biased_back_plot_pulls_toward_reflector():
    """A reflector within influence pulls the plot bias_frac of the way toward
    its planted XZ — closer to the reflector than to the honest plot."""
    fp, fv = _level_launch()
    plain = back_plot_surface(fp, fv)
    rx, rz = plain[0] + 5_000.0, plain[1]
    cr = CornerReflector("cr", np.array([rx, 0.0, rz]),
                         influence_m=CR_INFLUENCE_M, bias_frac=CR_BIAS_FRAC)
    biased = biased_back_plot(fp, fv, cr)
    assert biased is not None
    # Exactly bias_frac of the way from plain toward the reflector.
    exp_x = plain[0] + (rx - plain[0]) * CR_BIAS_FRAC
    exp_z = plain[1] + (rz - plain[1]) * CR_BIAS_FRAC
    assert math.isclose(biased[0], exp_x, abs_tol=1e-6)
    assert math.isclose(biased[1], exp_z, abs_tol=1e-6)
    # Decisively closer to the reflector than the honest plot was.
    d_refl = math.hypot(biased[0] - rx, biased[1] - rz)
    d_plain_refl = math.hypot(plain[0] - rx, plain[1] - rz)
    assert d_refl < d_plain_refl


def test_biased_back_plot_dogleg_stays_none():
    """A geometry back_plot_surface cannot localize (a coast-parallel dogleg)
    stays None even with a reflector — the reflector never invents a fix."""
    # vz below min-close -> back_plot_surface returns None.
    fp = np.array([0.0, 30.0, 5_000.0], dtype=np.float64)
    fv = np.array([250.0, 0.0, 1.0], dtype=np.float64)
    assert back_plot_surface(fp, fv) is None
    cr = CornerReflector("cr", np.array([0.0, 0.0, 0.0]))
    assert biased_back_plot(fp, fv, cr) is None


# ---------------------------------------------------------------------------
# The enemy acts on a NORMAL cluster from the planted (biased) BackPlotEntries
# ---------------------------------------------------------------------------

def test_biased_entries_form_cluster_off_the_pad():
    """BACKPLOT_FIXES_NEEDED biased fixes (distinct track ids, the world plants
    one per launch per reflector) form a NORMAL LaunchCluster whose centre is on
    the decoy coast — within X m of the reflector, NOT the real pad.  The enemy
    targetable_clusters() sees it as an ordinary cluster (no miss flag)."""
    fp, fv = _level_launch()
    plain = back_plot_surface(fp, fv)
    real_pad_xz = (plain[0], plain[1])     # the honest back-plot ~ the real pad
    rx, rz = plain[0] + 5_000.0, plain[1]
    cr = CornerReflector("cr", np.array([rx, 0.0, rz]))
    pic = EnemyPicture()
    for i in range(BACKPLOT_FIXES_NEEDED):
        b = biased_back_plot(fp, fv, cr)
        pic.add_back_plot(
            estimated_xz=np.array([b[0], b[1]], dtype=np.float64),
            error_m=100.0, sim_time=float(i), track_id=f"t{i}_cr")
    targetable = pic.targetable_clusters()
    assert targetable, "biased fixes must form a normal targetable cluster"
    c = targetable[0]
    d_pad = math.hypot(float(c.centre[0]) - real_pad_xz[0],
                       float(c.centre[1]) - real_pad_xz[1])
    d_refl = math.hypot(float(c.centre[0]) - rx, float(c.centre[1]) - rz)
    assert d_refl < d_pad, "cluster must sit on the decoy coast, off the real pad"
    # The cluster centre is well outside the seeker basket of the real pad.
    assert d_pad > SEEKER_BASKET_M


# ---------------------------------------------------------------------------
# World wiring: the bias hook injects EXTRA entries, byte-identical at 0
# ---------------------------------------------------------------------------

def test_reflector_built_when_armed():
    """A built reflector exists in world._corner_reflectors + a destructible
    Structure; absent at n_corner_reflectors=0 (byte-identical default)."""
    cw0 = CombatWorld(CombatConfig(seed=1337, n_corner_reflectors=0))
    assert cw0._corner_reflectors == []
    assert not any(s.structure_id.startswith("corner_reflector_")
                   for s in cw0.structures)

    cw1 = CombatWorld(CombatConfig(seed=1337, n_corner_reflectors=1))
    assert len(cw1._corner_reflectors) == 1
    assert any(s.structure_id == "corner_reflector_00_struct"
               for s in cw1.structures)


def test_reflector_centroid_spares_the_real_tel():
    """A salvo aimed at the reflector-biased centroid runs _refine_strike_aim: the
    nearest REAL FIRING TEL (bastion_tel) is >> SEEKER_BASKET_M away, so the round
    can NEVER acquire it — the real battery survives.  Whatever the round hits at
    the decoy coast (the reflector's own bait Structure, or empty dirt once that is
    rubble) is a worthless waste.  This is the headline dodge, physics-not-dice."""
    cw = CombatWorld(CombatConfig(seed=1337, n_corner_reflectors=1))
    cr = cw._corner_reflectors[0]
    rx, rz = cr.xz
    # The nearest REAL firing TEL must be well outside the seeker basket.
    nearest_tel = min(
        (math.hypot(float(s.pos[0]) - rx, float(s.pos[2]) - rz)
         for s in cw.structures
         if s.alive and s.kind in ("bastion_tel", "s300_tel", "buk_tel")),
        default=float("inf"))
    assert nearest_tel >= SEEKER_BASKET_M, (
        "reflector site must be >> a seeker basket from any real firing TEL")
    # With the reflector's OWN bait Structure killed, the centroid refines to
    # empty dirt (no real structure within the basket) — the round is wasted.
    refl_struct = next(s for s in cw.structures
                       if s.structure_id == f"{cr.reflector_id}_struct")
    refl_struct.alive = False
    ax, az, ay = cw._refine_strike_aim(rx, rz)
    nearest_live = min(
        (math.hypot(float(s.pos[0]) - rx, float(s.pos[2]) - rz)
         for s in cw.structures if s.alive), default=float("inf"))
    assert nearest_live >= SEEKER_BASKET_M
    assert (ax, az) == (rx, rz), "aim falls to dirt at the decoy point"


def test_reflector_bias_injects_extra_backplot():
    """Driving a real Oniks launch through the world feed with a reflector armed
    injects an EXTRA biased BackPlotEntry (tagged by the reflector id) into the
    enemy picture — a real sensor-level plant, not a flag."""
    cw = CombatWorld(CombatConfig(seed=1337, n_corner_reflectors=1))
    cr = cw._corner_reflectors[0]
    # Fire a real Oniks toward the enemy so the back-plot pipeline runs.
    cw.launch("lo-lo", np.array([float(cr.pos[0]), 0.0, 220_000.0]))
    saw_cr_entry = False
    for _ in range(int(120 * 120)):       # up to 120 s
        cw.step(DT)
        for bp in cw.commander.picture._back_plots:
            if str(bp.track_id).endswith(f"_cr_{cr.reflector_id}"):
                saw_cr_entry = True
                break
        if saw_cr_entry:
            break
    assert saw_cr_entry, (
        "a reflector-tagged biased BackPlotEntry must be planted by the feed")


def test_dead_reflector_injects_nothing():
    """A reflector killed before launch (alive False) plants no biased entry —
    the bias dies with the decoy."""
    cw = CombatWorld(CombatConfig(seed=1337, n_corner_reflectors=1))
    cr = cw._corner_reflectors[0]
    cr.alive = False
    cw.launch("lo-lo", np.array([float(cr.pos[0]), 0.0, 220_000.0]))
    for _ in range(int(60 * 120)):
        cw.step(DT)
    assert not any(str(bp.track_id).endswith(f"_cr_{cr.reflector_id}")
                   for bp in cw.commander.picture._back_plots)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_reflector_placement_deterministic():
    """Same seed -> same reflector placement."""
    a = CombatWorld(CombatConfig(seed=99, n_corner_reflectors=2))
    b = CombatWorld(CombatConfig(seed=99, n_corner_reflectors=2))
    pa = [tuple(np.round(c.pos, 6)) for c in a._corner_reflectors]
    pb = [tuple(np.round(c.pos, 6)) for c in b._corner_reflectors]
    assert pa == pb
    assert len(pa) == 2
