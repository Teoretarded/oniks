"""M2-T4 — player UI for the Kh-31P ARM (anti-radiation missile).

The SEAD SIM (launch_arm / emitter_contacts / PlayerArmMissile) already exists
and is gated (M2-T1..T3).  This task wires it to the player so the ARM is
USABLE in a battle:

  * Armory: a KH-31P AMMO stepper (field kh31p_ammo, clamp CLAMP_ARM_AMMO),
    flowing through build_config().
  * B weapon cycle: a 3-way oniks->zircon->kh31p->oniks cycle, GATED so the ARM
    is skipped when the world has no ARM ammo (the DEFAULT battle keeps the
    exact 2-way oniks<->zircon UX, byte-identical).
  * request_launch: a kh31p branch — requires a selected EMITTER (map
    selection); no emitter -> hint + None; with one -> world.launch_arm(eid).
  * tactical_map: pick_emitter(view, emitter_contacts, mouse_px) -> emitter_id,
    nearest within PICK_RADIUS_PX, over the fog-honest SIGINT picture.
  * hud: bastion_weapon_strip(sandbox, world) -> [(label, selected, ammo_text)]
    for ONIKS|ZIRCON|KH-31P (kh31p row only when ARM ammo is configured), and
    arm_seeker_row(missile) -> (label, color) LOCK / SILENT-CEP / MEMORY.

All logic is headless / GL-free (no window, no OpenGL).  No tautologies: every
assertion drives a real code path (the helpers are pure functions tested against
real values, the cycle/launch logic against stub sandboxes/worlds).
"""

import numpy as np
import pygame
import pytest

from game.tactical_map import MapView, PICK_RADIUS_PX, pick_emitter
from game.hud import bastion_weapon_strip, arm_seeker_row
from game.combat_setup import CombatSetupState, _PAGE_ARMORY
from world.combat_config import CLAMP_ARM_AMMO, CombatConfig


W, H = 1600, 900


def view(center=(0.0, 200_000.0), mpp=400.0):
    return MapView(W, H, center, mpp)


# ===========================================================================
# 1. Armory — KH-31P AMMO stepper
# ===========================================================================

class _Recorder:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _FakeStates:
    def __init__(self):
        self.current = None

    def switch(self, state):
        self.current = state


class _FakeApp:
    def __init__(self):
        self.audio = _Recorder()
        self.states = _FakeStates()
        self.menu = "MENU_SENTINEL"
        self.combat_configs = []

    def start_combat_with(self, cfg):
        self.combat_configs.append(cfg)

    def ui_text(self):
        raise RuntimeError("GL not available in headless tests")


def key_event(key, unicode=""):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0,
                              scancode=0, unicode=unicode)


@pytest.fixture
def setup():
    app = _FakeApp()
    return CombatSetupState(app, app.start_combat_with)


def _arm_row_idx(setup):
    return next(i for i, r in enumerate(setup._rows())
                if r.get("field") == "kh31p_ammo")


def test_armory_has_kh31p_ammo_stepper(setup):
    """The ARMORY page carries a kh31p_ammo stepper bounded by CLAMP_ARM_AMMO."""
    setup.handle_event(key_event(pygame.K_TAB))
    assert setup._page == _PAGE_ARMORY
    row = next(r for r in setup._rows() if r.get("field") == "kh31p_ammo")
    assert row["kind"] == "stepper"
    assert (row["lo"], row["hi"]) == CLAMP_ARM_AMMO
    assert row["step"] == 1


def test_kh31p_stepper_changes_field_within_clamp(setup):
    """Stepping right raises kh31p_ammo by 1; it clamps at the ARM ceiling and
    floor (0) — never wraps, never escapes CLAMP_ARM_AMMO."""
    setup.handle_event(key_event(pygame.K_TAB))
    setup._sel = _arm_row_idx(setup)
    assert setup._fields["kh31p_ammo"] == 0          # OFF by default
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["kh31p_ammo"] == 1
    # Clamp at the ceiling.
    setup._fields["kh31p_ammo"] = CLAMP_ARM_AMMO[1]
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["kh31p_ammo"] == CLAMP_ARM_AMMO[1]
    # Clamp at the floor (0).
    setup._fields["kh31p_ammo"] = CLAMP_ARM_AMMO[0]
    setup.handle_event(key_event(pygame.K_LEFT))
    assert setup._fields["kh31p_ammo"] == CLAMP_ARM_AMMO[0]


def test_start_config_carries_kh31p_ammo(setup):
    """A non-zero ARM stock survives build_config() onto the emitted config."""
    setup._fields["kh31p_ammo"] = 6
    cfg = setup.build_config()
    assert cfg.kh31p_ammo == 6


def test_default_config_kh31p_ammo_zero(setup):
    """Untouched, the ARM stays OFF (byte-identical default battle)."""
    assert setup.build_config().kh31p_ammo == 0


# ===========================================================================
# 2. B weapon cycle — 3-way, gated on ARM ammo
# ===========================================================================

class _StubAudio:
    def ui_click(self):
        pass


class _StubApp:
    def __init__(self):
        self.audio = _StubAudio()


class _StubWorld:
    """Minimal world carrying just the ARM pool the cycle gate reads."""
    def __init__(self, kh31p_ammo):
        self._kh31p_ammo = kh31p_ammo


class _CycleSandbox:
    """A bare Sandbox carrying only what cycle_oniks_weapon touches."""
    def __init__(self, kh31p_ammo):
        from game.sandbox import SandboxState
        self.oniks_weapon = "oniks"
        self.app = _StubApp()
        self.world = _StubWorld(kh31p_ammo)
        self.hint_text = ""
        self.hint_left = 0.0
        self._cycle = SandboxState.cycle_oniks_weapon
        self._hint = SandboxState.show_hint

    def show_hint(self, text, seconds=2.5):
        self.hint_text = text
        self.hint_left = seconds

    def cycle_oniks_weapon(self):
        return self._cycle(self)


def test_b_cycle_two_way_when_no_arm_ammo():
    """ARM ammo 0 -> the B cycle stays the EXACT oniks<->zircon 2-way UX
    (kh31p is skipped); this preserves the byte-identical default battle."""
    sb = _CycleSandbox(kh31p_ammo=0)
    assert sb.oniks_weapon == "oniks"
    assert sb.cycle_oniks_weapon() == "zircon"
    assert sb.cycle_oniks_weapon() == "oniks"      # wraps, never lands on kh31p
    assert sb.cycle_oniks_weapon() == "zircon"


def test_b_cycle_three_way_when_arm_ammo():
    """ARM ammo > 0 -> oniks->zircon->kh31p->oniks."""
    sb = _CycleSandbox(kh31p_ammo=4)
    assert sb.oniks_weapon == "oniks"
    assert sb.cycle_oniks_weapon() == "zircon"
    assert sb.cycle_oniks_weapon() == "kh31p"
    assert sb.cycle_oniks_weapon() == "oniks"


def test_b_cycle_arm_none_ammo_skips_kh31p():
    """A None ARM pool (sandbox, never configured) is treated as empty."""
    sb = _CycleSandbox(kh31p_ammo=None)
    assert sb.cycle_oniks_weapon() == "zircon"
    assert sb.cycle_oniks_weapon() == "oniks"


def test_b_cycle_off_kh31p_when_ammo_drained():
    """If the player is ON kh31p and the pool empties, the next B press still
    advances normally back to oniks (no stuck state)."""
    sb = _CycleSandbox(kh31p_ammo=2)
    sb.oniks_weapon = "kh31p"
    # Pool empties mid-battle.
    sb.world._kh31p_ammo = 0
    # From kh31p the cycle returns to oniks (kh31p -> oniks regardless of gate).
    assert sb.cycle_oniks_weapon() == "oniks"


# ===========================================================================
# 3. request_launch — kh31p branch
# ===========================================================================

class _FakeRound:
    """Stand-in PlayerArmMissile: only .pos is touched by the launch effects."""
    def __init__(self):
        self.pos = np.array([0.0, 5.0, 0.0])


class _LaunchWorld:
    """Records launch_arm calls; returns a sentinel 'missile'."""
    def __init__(self, kh31p_ammo=4):
        self._kh31p_ammo = kh31p_ammo
        self.arm_calls = []
        self.missiles = []
        self._return = _FakeRound()

    def launch_arm(self, emitter_id):
        self.arm_calls.append(emitter_id)
        return self._return


class _FakeMap:
    def __init__(self, selected_emitter=None):
        self.selected_emitter = selected_emitter


class _FakeRig:
    def __init__(self):
        self.retargets = 0

    def retarget(self):
        self.retargets += 1

    def kick_shake(self, *a, **k):
        pass


class _LaunchSandbox:
    """Bare sandbox carrying only what request_launch's kh31p branch touches."""
    def __init__(self, world, selected_emitter=None):
        from game.sandbox import SandboxState
        self.oniks_weapon = "kh31p"
        self.active_platform = "bastion"
        self.world = world
        self.tactical_map = _FakeMap(selected_emitter)
        self.rig = _FakeRig()
        self.followed = None
        self.target_point = None
        self.waypoints = []
        self.profile = "hi-lo"
        self.hint_text = ""
        self.hint_left = 0.0
        self.app = _StubApp()
        self.effects = _Recorder()
        self.app.audio = _Recorder()
        self._tel_pos = np.array([0.0, 0.0, 0.0])
        self._request = SandboxState.request_launch
        self._arm = SandboxState._request_arm_launch

    def show_hint(self, text, seconds=2.5):
        self.hint_text = text
        self.hint_left = seconds

    def _spawn_cover_debris(self, *a, **k):
        pass

    def _request_arm_launch(self):
        return self._arm(self)

    def request_launch(self):
        return self._request(self)


def test_request_launch_arm_with_emitter_calls_launch_arm():
    """kh31p selected + a selected emitter -> world.launch_arm(eid), the round
    is followed, the rig retargets onto it."""
    world = _LaunchWorld()
    sb = _LaunchSandbox(world, selected_emitter="radar_3")
    m = sb.request_launch()
    assert world.arm_calls == ["radar_3"]
    assert m is world._return
    assert sb.followed is m
    assert sb.rig.retargets == 1


def test_request_launch_arm_no_emitter_hints_and_does_not_fire():
    """kh31p selected with NO emitter -> the SELECT-AN-EMITTER hint, None, and
    launch_arm is never called (no fire)."""
    from game.sandbox import HINT_ARM_NO_EMITTER
    world = _LaunchWorld()
    sb = _LaunchSandbox(world, selected_emitter=None)
    m = sb.request_launch()
    assert m is None
    assert world.arm_calls == []
    assert sb.hint_text == HINT_ARM_NO_EMITTER


def test_request_launch_arm_world_refusal_returns_none():
    """If launch_arm refuses (e.g. emitter died / pool emptied), request_launch
    returns None and does NOT follow a non-round."""
    world = _LaunchWorld()
    world._return = None                 # world-side gate refuses
    sb = _LaunchSandbox(world, selected_emitter="radar_9")
    m = sb.request_launch()
    assert m is None
    assert world.arm_calls == ["radar_9"]    # the world WAS asked
    assert sb.followed is None                # ... but nothing to follow
    assert sb.rig.retargets == 0


# ===========================================================================
# 4. pick_emitter — nearest localized emitter within PICK_RADIUS_PX
# ===========================================================================

def _emitters(entries):
    """emitter_contacts dict: eid -> {pos (3,), kind, quality, last_heard, age}."""
    out = {}
    for eid, pos in entries.items():
        out[eid] = dict(pos=np.asarray(pos, dtype=np.float64),
                        kind="GND RADAR", quality=100.0,
                        last_heard=0.0, age=10.0)
    return out


def test_pick_emitter_nearest_within_radius_else_none():
    v = view(center=(0.0, 200_000.0), mpp=400.0)
    a = (10_000.0, 0.0, 205_000.0)
    b = (10_000.0 + 12.0 * 400.0, 0.0, 205_000.0)    # 12 px east of a
    ec = _emitters({"a": a, "b": b})
    pa = v.world_to_screen((a[0], a[2]))
    # 5 px east of a: inside 14 px of both, nearest is a.
    assert pick_emitter(v, ec, (pa[0] + 5.0, pa[1])) == "a"
    # 8 px east of a -> 4 px west of b: nearest is b.
    assert pick_emitter(v, ec, (pa[0] + 8.0, pa[1])) == "b"
    # 13.9 px below a: still inside a.
    assert pick_emitter(v, ec, (pa[0], pa[1] + 13.9)) == "a"
    # 15 px below a, > 14 from b too: None.
    assert pick_emitter(v, ec, (pa[0], pa[1] + 15.0)) is None
    assert PICK_RADIUS_PX == 14.0


def test_pick_emitter_empty_picture_returns_none():
    v = view()
    assert pick_emitter(v, {}, (800.0, 450.0)) is None


def test_pick_emitter_uses_est_pos_belief():
    """The pick resolves at the SIGINT est_pos (belief), the same vector the
    glyph renders — never a separate truth position."""
    v = view(center=(0.0, 200_000.0), mpp=400.0)
    est = (-30_000.0, 0.0, 215_000.0)
    ec = _emitters({"e1": est})
    on = v.world_to_screen((est[0], est[2]))
    assert pick_emitter(v, ec, on) == "e1"
    far = (on[0] + 200.0, on[1] + 200.0)
    assert pick_emitter(v, ec, far) is None


# ===========================================================================
# 5. bastion_weapon_strip
# ===========================================================================

class _StripWorld:
    def __init__(self, oniks_ammo=8, oniks_cap=8, zircon=4, kh31p=0):
        self._oniks_ammo = oniks_ammo
        self._oniks_mag_cap = oniks_cap
        self._zircon_ammo = zircon
        self._kh31p_ammo = kh31p


class _StripSandbox:
    def __init__(self, oniks_weapon="oniks"):
        self.oniks_weapon = oniks_weapon


def test_weapon_strip_two_rows_when_arm_off():
    """ARM unconfigured (0) -> only ONIKS + ZIRCON rows (default battle UX)."""
    sb = _StripSandbox("oniks")
    world = _StripWorld(kh31p=0)
    strip = bastion_weapon_strip(sb, world)
    labels = [label for (label, _sel, _ammo) in strip]
    assert labels == ["ONIKS", "ZIRCON"]


def test_weapon_strip_three_rows_when_arm_configured():
    sb = _StripSandbox("kh31p")
    world = _StripWorld(kh31p=5)
    strip = bastion_weapon_strip(sb, world)
    labels = [label for (label, _sel, _ammo) in strip]
    assert labels == ["ONIKS", "ZIRCON", "KH-31P"]


def test_weapon_strip_selected_flag_tracks_active_weapon():
    world = _StripWorld(kh31p=5)
    for weapon, want in (("oniks", "ONIKS"), ("zircon", "ZIRCON"),
                         ("kh31p", "KH-31P")):
        strip = bastion_weapon_strip(_StripSandbox(weapon), world)
        selected = [label for (label, sel, _a) in strip if sel]
        assert selected == [want], f"{weapon} should flag {want}"


def test_weapon_strip_ammo_text():
    """ONIKS shows magazine n/cap; the pool weapons show their count."""
    sb = _StripSandbox("oniks")
    world = _StripWorld(oniks_ammo=6, oniks_cap=8, zircon=3, kh31p=2)
    rows = {label: ammo for (label, _sel, ammo) in
            bastion_weapon_strip(sb, world)}
    assert rows["ONIKS"] == "6/8"
    assert rows["ZIRCON"] == "3"
    assert rows["KH-31P"] == "2"


def test_weapon_strip_exactly_one_selected():
    sb = _StripSandbox("zircon")
    world = _StripWorld(kh31p=4)
    strip = bastion_weapon_strip(sb, world)
    assert sum(1 for (_l, sel, _a) in strip if sel) == 1


# ===========================================================================
# 6. arm_seeker_row — LOCK / SILENT-CEP / MEMORY / None
# ===========================================================================

class _FakeRadar:
    def __init__(self, alive=True, emitting=True):
        self.alive = alive
        self.emitting = emitting


class _FakeArm:
    """Duck-typed PlayerArmMissile: target_radar + _miss_offset are what the
    seeker readout reads off the FOLLOWED round (allowed own-round state)."""
    is_player_arm = True

    def __init__(self, radar, miss_offset=None):
        self.target_radar = radar
        self._miss_offset = miss_offset


def test_arm_seeker_row_lock():
    """Target alive + emitting + no miss offset -> LOCK."""
    row = arm_seeker_row(_FakeArm(_FakeRadar(alive=True, emitting=True)))
    assert row is not None
    label, _col = row
    assert label == "LOCK"


def test_arm_seeker_row_silent_cep():
    """A drawn miss offset (radar went silent) -> SILENT-CEP."""
    row = arm_seeker_row(_FakeArm(_FakeRadar(alive=True, emitting=False),
                                  miss_offset=np.array([200.0, 0.0, 50.0])))
    assert row is not None
    label, _col = row
    assert label == "SILENT-CEP"


def test_arm_seeker_row_memory():
    """No miss offset but the target isn't emitting (coasting last-known) ->
    MEMORY."""
    row = arm_seeker_row(_FakeArm(_FakeRadar(alive=True, emitting=False),
                                  miss_offset=None))
    assert row is not None
    label, _col = row
    assert label == "MEMORY"


def test_arm_seeker_row_dead_target_memory():
    """A dead target with no offset is coasting last-known too -> MEMORY."""
    row = arm_seeker_row(_FakeArm(_FakeRadar(alive=False, emitting=False),
                                  miss_offset=None))
    assert row is not None and row[0] == "MEMORY"


def test_arm_seeker_row_none_for_non_arm():
    """A non-ARM missile (no target_radar / not a PlayerArmMissile) -> None."""
    class _Oniks:
        pass
    assert arm_seeker_row(_Oniks()) is None
    assert arm_seeker_row(None) is None


def test_arm_seeker_row_real_player_arm_locks():
    """Against a REAL PlayerArmMissile homing on an emitting radar: LOCK."""
    from sim.arsenal import KH31P
    from sim.radar import Radar
    from sim.strike import PlayerArmMissile
    radar = Radar("e", np.array([0.0, 0.0, 90_000.0], dtype=np.float64),
                  antenna_m=10.0,
                  ranges={"missile": 300_000.0, "fighter": 300_000.0})
    radar.emitting = True
    rng = np.random.default_rng([1337, 8])
    m = PlayerArmMissile(KH31P, np.zeros(3), np.array([0.0, 0.0, 60.0]),
                         radar, rng)
    row = arm_seeker_row(m)
    assert row is not None and row[0] == "LOCK"
