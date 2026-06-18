"""M5 #1 amphibious OBJECTIVE / TIMED beachhead lose-path.

Coverage (spec 05 "Amphibious landing as a TIMED lose condition"):
  * an Lcac entering the LANDING_BOX sets beachhead_active True and starts
    beachhead_left counting down;
  * killing ALL committed craft before expiry sets beachhead_active False and
    CANCELS the loss (defeated stays False on the amphibious clause);
  * letting beachhead_left reach 0 sets defeated True with defeat_cause ==
    'beachhead';
  * a TEL-only defeat still yields defeat_cause == 'bastion';
  * victorious requires the transports + LCACs dead (ships-count-for-win) —
    an alive landing force => not victorious even with all else dead;
  * REGRESSION: n_transports=0 reproduces today EXACTLY — defeated trips only on
    the bastion_tel clause; a same-seed multi-thousand-step digest is
    bit-identical to the pre-change HEAD (the byte-identical GATE);
  * the commander orders TRANSPORT_RUN only from its sensor picture (no truth
    read; deterministic).
"""

from __future__ import annotations

import numpy as np

from sim.amphibious import (BEACHHEAD_GRACE_S, LANDING_BOX_RADIUS_M,
                            LAUNCH_LINE_RANGE_M, Lcac, landing_box_xz)
from sim.ships import ST_ALIVE, ST_GONE
from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS

DT = 1.0 / 120.0
BX, BZ = float(BASE_POS[0]), float(BASE_POS[2])
BOX = landing_box_xz((BX, BZ))

# Pre-change HEAD baseline digest of the default battle (seed 1337, 3000 steps),
# captured from git HEAD BEFORE this feature.  The n_transports=0 default battle
# MUST reproduce it bit-for-bit (the byte-identical GATE).
HEAD_DEFAULT_DIGEST = \
    "058de76c8efb167a95a164ee4eaa2ad5a97fa0fd0d6efec522d661ee2fc6f721"


def _force_landing(cw):
    """Splash one transport and drive its LCACs into the box so a beachhead is
    in progress.  Returns the live LCAC list."""
    tr = cw.transports[0]
    tr.begin_run()
    tr.pos[0] = BX
    tr.pos[2] = BZ + LAUNCH_LINE_RANGE_M - 100.0
    cw._step_amphibious(DT)             # splash
    # Teleport every committed craft so an LCAC lands and the rest stay alive.
    for lc in cw.lcacs:
        lc.pos[0] = BOX[0]
        lc.pos[2] = BOX[1]
        lc.update(DT)                   # latch landed
    return cw.lcacs


# ---------------------------------------------------------------------------
# Beachhead clock: starts on landing, counts down
# ---------------------------------------------------------------------------

def test_lcac_in_box_starts_the_beachhead_clock():
    """An LCAC entering the LANDING_BOX flips beachhead_active True and arms
    beachhead_left at the grace value."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1, beachhead_grace_s=60.0))
    assert not cw.beachhead_active
    assert cw.beachhead_left is None
    _force_landing(cw)
    cw._step_amphibious(DT)             # detect the landing, start the clock
    assert cw.beachhead_active
    assert cw.beachhead_left is not None
    assert 0.0 < cw.beachhead_left <= 60.0


def test_beachhead_clock_counts_down():
    """beachhead_left strictly decreases while a landing is in progress and craft
    remain alive."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1, beachhead_grace_s=60.0))
    _force_landing(cw)
    cw._step_amphibious(DT)
    t0 = cw.beachhead_left
    for _ in range(120):                # 1 s
        cw._step_amphibious(DT)
    assert cw.beachhead_left < t0
    assert abs((t0 - cw.beachhead_left) - 1.0) < 0.05


# ---------------------------------------------------------------------------
# Clearing all committed craft CANCELS the loss (a real save)
# ---------------------------------------------------------------------------

def test_clearing_all_craft_cancels_the_loss():
    """Killing EVERY committed craft (transports + LCACs) before expiry sets
    beachhead_active False and keeps defeated False on the amphibious clause."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1, n_enemy_radars=0,
                                  beachhead_grace_s=60.0))
    _force_landing(cw)
    cw._step_amphibious(DT)
    assert cw.beachhead_active
    # Kill the transport AND every LCAC (the player cleared the lodgement).
    for tr in cw.transports:
        tr.state = ST_GONE
    for lc in cw.lcacs:
        lc.state = ST_GONE
    cw._step_amphibious(DT)
    assert not cw.beachhead_active, "clearing all craft must cancel the beachhead"
    assert not cw.defeated, "a cleared beachhead must not defeat the player"
    assert cw.defeat_cause is None


def test_beachhead_expiry_defeats_with_cause_beachhead():
    """Letting the clock reach 0 with craft still ashore sets defeated True and
    defeat_cause == 'beachhead'."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1, beachhead_grace_s=2.0))
    _force_landing(cw)
    cw._step_amphibious(DT)
    assert not cw.defeated
    # Run past the 2 s grace (the LCAC stays in the box, alive).
    for _ in range(int(2.5 * 120)):
        cw._step_amphibious(DT)
    assert cw.defeated, "an unexpired beachhead must defeat the player"
    assert cw.defeat_cause == "beachhead"


# ---------------------------------------------------------------------------
# Defeat-cause selection + bastion precedence
# ---------------------------------------------------------------------------

def test_tel_only_defeat_yields_cause_bastion():
    """A pure TEL-wipe (no transports) defeats with cause 'bastion' (the
    regression path)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=0))
    assert not cw.defeated
    for s in cw.structures:
        if s.kind == "bastion_tel":
            s.alive = False
    assert cw.defeated
    assert cw.defeat_cause == "bastion"


# ---------------------------------------------------------------------------
# victorious requires the landing force dead (ships-count-for-win)
# ---------------------------------------------------------------------------

def test_victorious_requires_landing_force_dead():
    """An alive transport / LCAC keeps victorious False even with every other
    hull / airfield / radar dead (ships-count-for-win)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1, n_enemy_radars=0))
    # Splash so an LCAC also exists.
    tr = cw.transports[0]
    tr.begin_run()
    tr.pos[0] = BX
    tr.pos[2] = BZ + LAUNCH_LINE_RANGE_M - 100.0
    cw._step_amphibious(DT)
    assert cw.lcacs
    # Kill EVERYTHING except the landing force.
    for s in cw.ships:
        if not isinstance(s, (Lcac, type(tr))) and s.ship_type not in (
                "transport", "lcac"):
            s.state = ST_GONE
    cw.airfield.alive = False
    assert not cw.victorious, "alive landing force must block victory"
    # Now sink the whole landing force too.
    for s in cw.ships:
        s.state = ST_GONE
    assert cw.victorious


# ---------------------------------------------------------------------------
# Commander TRANSPORT_RUN: sensor-only release (no truth read), deterministic
# ---------------------------------------------------------------------------

def test_commander_holds_run_without_a_sensor_trigger():
    """With an EMPTY picture (no localized base) the commander issues NO
    transport_run order — the transports stay in LOITER."""
    from sim.commander import EnemyCommander, EnemyPicture
    cmd = EnemyCommander(fighters=[], awacs=None, destroyers=[],
                         picture=EnemyPicture(), seed=1)
    orders = cmd.tick(0.0, 1.0)
    assert not any(o["type"] == "transport_run" for o in orders)
    assert not cmd._amphibious_released


def test_commander_releases_run_on_believed_trigger():
    """Supplying the BELIEVED trigger (a confirmed launch cluster in the sensor
    picture) makes the commander issue transport_run EXACTLY once — from belief,
    never truth."""
    from sim.commander import (BACKPLOT_FIXES_NEEDED, EnemyCommander,
                               EnemyPicture)
    pic = EnemyPicture()
    # Seed a CONFIRMED cluster purely from sensor back-plot events (no truth):
    # BACKPLOT_FIXES_NEEDED distinct fixes at the same site -> targetable.
    for i in range(BACKPLOT_FIXES_NEEDED):
        pic.add_back_plot(np.array([0.0, 0.0]), 100.0, float(i), f"trk_{i}")
    assert pic.targetable_clusters(), "test setup: cluster must be confirmed"
    cmd = EnemyCommander(fighters=[], awacs=None, destroyers=[],
                         picture=pic, seed=1)
    orders = cmd.tick(0.0, 1.0)
    runs = [o for o in orders if o["type"] == "transport_run"]
    assert len(runs) == 1, "exactly one transport_run on the believed trigger"
    assert cmd._amphibious_released
    # A second tick issues NO further run order (latched once).
    orders2 = cmd.tick(1.0, 1.0)
    assert not any(o["type"] == "transport_run" for o in orders2)


def test_commander_release_is_deterministic():
    """Same picture sequence + seed -> same release decision."""
    from sim.commander import (BACKPLOT_FIXES_NEEDED, EnemyCommander,
                               EnemyPicture)

    def _run(seed):
        pic = EnemyPicture()
        for i in range(BACKPLOT_FIXES_NEEDED):
            pic.add_back_plot(np.array([0.0, 0.0]), 100.0, float(i), f"t{i}")
        cmd = EnemyCommander(fighters=[], awacs=None, destroyers=[],
                             picture=pic, seed=seed)
        return [o["type"] for o in cmd.tick(0.0, 1.0)]

    assert _run(7) == _run(7)


# ---------------------------------------------------------------------------
# REGRESSION: n_transports=0 is byte-identical (THE GATE)
# ---------------------------------------------------------------------------

def _battle_digest(cw, steps=3000):
    """Bit-level digest of the default battle: events + missile + ship positions
    rounded to 1e-6, hashed.  Mirrors tests/test_submarine._battle_digest."""
    import hashlib
    rows = []
    for _ in range(steps):
        cw.step(DT)
        for ev in cw.events:
            rows.append((ev[0],) + tuple(round(float(c), 6)
                                         for c in np.asarray(ev[1]).ravel()))
        for m in cw.missiles:
            rows.append(("m",) + tuple(round(float(c), 6) for c in m.pos))
        for s in cw.ships:
            rows.append(("s",) + tuple(round(float(c), 6) for c in s.pos))
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def test_n_transports_zero_is_inert():
    """With n_transports=0 NO transport/LCAC is built, the views are empty,
    _step_amphibious is a no-op, the beachhead clock never starts and defeated
    reduces to the bastion clause."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert cw.transports == []
    assert cw.lcacs == []
    assert not cw.beachhead_active
    assert cw.beachhead_left is None
    # Step a while: nothing amphibious ever happens, no defeat from the new path.
    for _ in range(600):
        cw.step(DT)
    assert cw.lcacs == []
    assert not cw.beachhead_active
    assert not cw.defeated
    assert cw.defeat_cause is None


def test_n_transports_zero_default_battle_bit_identical_to_head():
    """THE GATE: the n_transports=0 default battle digest is bit-identical to the
    pre-change HEAD baseline (the new amphibious path is fully inert and does not
    perturb determinism)."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert _battle_digest(cw) == HEAD_DEFAULT_DIGEST, (
        "n_transports=0 default battle diverged from the pre-change HEAD digest")


def test_n_transports_zero_cross_build_bit_identical():
    """Two same-seed builds match (determinism, independent of the HEAD pin)."""
    a = CombatWorld(CombatConfig(seed=1337))
    b = CombatWorld(CombatConfig(seed=1337))
    assert _battle_digest(a) == _battle_digest(b)
