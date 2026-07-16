"""Shoulder-fired weapons for the cinematic walk mode.

The WeaponRig owns everything player-weapon: the F1 weapons locker UI,
the shouldered view model, right-click sighting, middle-click target
designation (a flying round or any ground point), left-click launch, the
missile flyout rendering (corkscrew trails, dart separation) and the
seeker HUD. Physics lives in sim/manpads.py; this module only feeds it
and draws it.

Contract with CinematicState (kept NARROW so game/cinematic.py needs
only five one-line hooks): reads st.walker/.scene/.launches/.effects/
.freecam/.zoom_i/.ui_open/.text, calls st._say/._queue_sound/
._screen_pos, and st.app.renderer for drawing. GL objects are created
lazily inside draw_world; constructing the rig is GL-free (headless
tests import this module).

Controls (walk mode, weapon shouldered):
    F1     weapons locker (click a system to shoulder it)
    RMB    hold: raise the sight (weapon's optic FOV)
    MMB    designate what the crosshair is on — a burning round, or the
           terrain point itself; IR needs a source inside its acquisition
           range, the Starstreak beam takes anything
    LMB    fire. Starstreak then RIDES YOUR AIM (SACLOS): keep the
           crosshair on the target all the way in.
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from engine import math3d
from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.cinematic_missiles import WIND
from sim.manpads import ManpadsRound, WEAPONS, WEAPON_BY_ID

# Same fresh glass palette as the cinematic director overlay.
UI_GLASS = (0.02, 0.03, 0.045, 0.86)
UI_HAIR = (1.0, 1.0, 1.0, 0.14)
UI_TXT = (0.93, 0.95, 0.97)
UI_DIM = (0.52, 0.58, 0.65)
UI_ACC = (0.55, 0.85, 1.0)
UI_WARN = (1.0, 0.62, 0.30)

BASE_FOV = 68.0
ACQ_PICK_DEG = 3.5           # crosshair pick half-angle for designation
TONE_TIME_S = 0.8            # IR uncage: TONE -> LOCK hold time
GROUND_RAY_MAX = 8000.0
COAST_LOCK_SCALE = 0.45      # IR range vs a burnt-out (coasting) round

_SFX_SMOKE_LIFE = (22.0, 45.0)


class _BeamPoint:
    """Starstreak SACLOS: the guidance 'target' is wherever the player's
    crosshair rests, updated every frame — the missile rides the aim."""

    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.vel = np.zeros(3)
        self.done = False
        self.radius = 0.5

    def move(self, pos, dt):
        p = np.asarray(pos, dtype=np.float64)
        if dt > 1e-6:
            self.vel = (p - self.pos) / dt
        self.pos = p


class _Flyout:
    """One live round + its cosmetic trail state."""

    def __init__(self, rnd: ManpadsRound, target):
        self.rnd = rnd
        self.target = target             # ScriptedLaunch | _BeamPoint | None
        self.beam = isinstance(target, _BeamPoint)
        self._last_trail = None
        self._smoke_carry = 0.0
        self._path_m = 0.0
        self.sep_t = None                # time of dart separation


class WeaponRig:
    """All player-weapon behaviour for the cinematic walk mode."""

    def __init__(self):
        self.weapon = None               # ManpadsSpec | None (stowed)
        self.locker_open = False
        self.ads = 0.0                   # 0..1 sight blend
        self._ads_held = False
        self.reload_left = 0.0
        self.seek_state = "idle"        # idle | tone | lock
        self._tone_left = 0.0
        self.track = None                # designated ScriptedLaunch
        self.ground_mark = None          # designated ground point (np)
        self.flyouts: list[_Flyout] = []
        self._ui_rects: list = []
        self._gl_ready = False
        self._launcher_meshes = {}
        self._missile_meshes = {}
        self._dart_mesh = None
        self._t = 0.0
        self._occ_left = 0.0

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _aim(st):
        return np.asarray(st.walker.forward(), dtype=np.float64)

    @staticmethod
    def _eye(st):
        return np.asarray(st.walker.eye, dtype=np.float64)

    @staticmethod
    def _ground_fn(st):
        """Scene ground sampler that returns 'no ground' outside the baked
        tile bounds so a long flyout never faults the sampler."""
        sc = st.scene

        def ground(x, z):
            if sc.x0 <= x <= sc.x1 and sc.z0 <= z <= sc.z1:
                return float(sc.ground_h(x, z))
            return -1.0e9
        return ground

    def _ray_ground(self, st, max_m=GROUND_RAY_MAX):
        """March the aim ray onto the terrain (same scheme as the state's
        freecam teleport: coarse march + bisection)."""
        d = self._aim(st)
        p = self._eye(st)
        ground = self._ground_fn(st)
        t, step = 0.0, 6.0
        while t < max_m:
            t += step
            q = p + d * t
            if ground(q[0], q[2]) >= q[1]:
                lo, hi = t - step, t
                for _ in range(16):
                    mid = 0.5 * (lo + hi)
                    q = p + d * mid
                    if ground(q[0], q[2]) >= q[1]:
                        hi = mid
                    else:
                        lo = mid
                q = p + d * hi
                q[1] = ground(q[0], q[2])
                return q
        return None

    def _los_clear(self, st, a, b) -> bool:
        ground = self._ground_fn(st)
        rel = np.asarray(b, dtype=np.float64) - a
        dist = float(np.linalg.norm(rel))
        n = max(int(dist / 40.0), 1)
        d = rel / n
        p = np.asarray(a, dtype=np.float64).copy()
        for _ in range(n - 1):
            p = p + d
            if ground(p[0], p[2]) >= p[1]:
                return False
        return True

    def fov_override(self):
        """The sight's FOV while aiming (None hands control back)."""
        if self.weapon is None or self.ads <= 0.01:
            return None
        return BASE_FOV + (self.weapon.ads_fov_deg - BASE_FOV) * self.ads

    # -------------------------------------------------------------- input

    def handle_event(self, ev, st) -> bool:
        """Consume weapon-related events; True stops the state's handling.
        Called FIRST in the state's handler — ESC is only taken when the
        locker is open, everything else falls through."""
        if st.walker is None:
            return False
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F1:
            self._toggle_locker(st)
            return True
        if self.locker_open:
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self._toggle_locker(st)
                return True
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_g:
                self._toggle_locker(st)   # hand the cursor to the director
                return False
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                self._locker_click(st, getattr(ev, "pos", (0, 0)))
                return True
            if ev.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN,
                           pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL):
                return True
            return False
        if self.weapon is None or st.freecam or st.ui_open:
            return False
        # Shouldered weapon, walking free-look:
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == 3:
                self._ads_held = True
                return True
            if ev.button == 2:
                self._designate(st)
                return True
            if ev.button == 1 and st.zoom_i == 0:
                self._fire(st)
                return True
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 3:
            self._ads_held = False
            return True
        elif ev.type == pygame.MOUSEWHEEL and self._ads_held:
            return True                   # no binoculars over the sight
        return False

    def _toggle_locker(self, st) -> None:
        self.locker_open = not self.locker_open
        if self.locker_open:
            st.ui_open = False            # the director yields the cursor
            self._ads_held = False
        pygame.event.set_grab(not self.locker_open and not st.ui_open)
        pygame.mouse.set_visible(self.locker_open or st.ui_open)

    def _locker_click(self, st, pos) -> None:
        for kind, wid, rect in self._ui_rects:
            if not (rect[0] <= pos[0] <= rect[2]
                    and rect[1] <= pos[1] <= rect[3]):
                continue
            if kind == "stow":
                self.weapon = None
                self._clear_designation()
                st._say("WEAPON STOWED")
            else:
                self.weapon = WEAPON_BY_ID[wid]
                self.reload_left = 0.0
                self._clear_designation()
                st._say(f"{self.weapon.label} SHOULDERED - "
                        "MMB DESIGNATE, LMB FIRE")
            self._toggle_locker(st)
            return

    # -------------------------------------------------------- designation

    def _clear_designation(self) -> None:
        self.seek_state = "idle"
        self.track = None
        self.ground_mark = None
        self._tone_left = 0.0

    def _designate(self, st) -> None:
        s = self.weapon
        eye = self._eye(st)
        aim = self._aim(st)
        # 1) airborne rounds under the crosshair, nearest angular pick
        best, best_ang = None, math.radians(ACQ_PICK_DEG)
        for m in st.launches:
            if m.done:
                continue
            rel = np.asarray(m.pos, dtype=np.float64) - eye
            rng = float(np.linalg.norm(rel))
            if rng < 25.0:
                continue
            ang = math.acos(float(np.clip(np.dot(aim, rel / rng),
                                          -1.0, 1.0)))
            if ang >= best_ang:
                continue
            if s.seeker == "ir":
                limit = s.lock_range_m * (1.0 if m.burning()
                                          else COAST_LOCK_SCALE)
                if rng > limit:
                    continue
            elif rng > s.range_m * 1.15:
                continue
            if self._los_clear(st, eye, m.pos):
                best, best_ang = m, ang
        if best is not None:
            self.track = best
            self.ground_mark = None
            if s.seeker == "ir":
                self.seek_state = "tone"
                self._tone_left = TONE_TIME_S
                st._say("SEEKER TONE...")
            else:
                self.seek_state = "lock"
                st._say("BEAM ON TARGET - RIDE IT IN")
            return
        # 2) a ground point
        hit = self._ray_ground(st)
        if hit is not None:
            rng = float(np.linalg.norm(hit - eye))
            if rng < s.min_range_m:
                st._say(f"TOO CLOSE - MIN {s.min_range_m:0.0f} M")
                return
            limit = s.lock_range_ground_m if s.seeker == "ir" \
                else s.range_m * 1.15
            if rng <= limit:
                self.track = None
                self.ground_mark = hit
                if s.seeker == "ir":
                    self.seek_state = "tone"
                    self._tone_left = TONE_TIME_S
                    st._say(f"HOT CLUTTER TONE - {rng:0.0f} M")
                else:
                    self.seek_state = "lock"
                    st._say(f"BEAM MARK - {rng:0.0f} M")
                return
            st._say("NO IR SOURCE IN RANGE" if s.seeker == "ir"
                    else "BEYOND BEAM RANGE")
            return
        self._clear_designation()
        st._say("NO TARGET UNDER CROSSHAIR")

    def _designation_valid(self, st) -> bool:
        """Re-check the hold conditions while TONE runs / LOCK holds."""
        s = self.weapon
        if s is None:
            return False
        eye = self._eye(st)
        if self.track is not None:
            if getattr(self.track, "done", False):
                return False
            rel = np.asarray(self.track.pos, dtype=np.float64) - eye
            rng = float(np.linalg.norm(rel))
            if s.seeker == "ir":
                limit = s.lock_range_m * (1.0 if self.track.burning()
                                          else COAST_LOCK_SCALE)
                if rng > limit:
                    return False
            return self._los_clear(st, eye, self.track.pos)
        if self.ground_mark is not None:
            return True
        return False

    # --------------------------------------------------------------- fire

    def _fire(self, st) -> None:
        s = self.weapon
        if self.reload_left > 0.0:
            st._say(f"NEW TUBE - {self.reload_left:0.1f} S")
            return
        if self.seek_state != "lock":
            st._say("NO LOCK - MMB TO DESIGNATE" if s.seeker == "ir"
                    else "NO BEAM MARK - MMB FIRST")
            return
        eye = self._eye(st)
        aim = self._aim(st)
        f, r, u = self._basis(st)
        muzzle = eye + f * 0.9 + r * 0.18 - u * 0.12
        if s.seeker == "beam":
            beam = _BeamPoint(self._beam_point(st))
            target, gp = beam, None
        elif self.track is not None:
            target, gp = self.track, None
        else:
            target, gp = None, self.ground_mark
        rnd = ManpadsRound(s, muzzle, aim, target=target, ground_point=gp,
                           ground_h=self._ground_fn(st),
                           victims=lambda: st.launches)
        self.flyouts.append(_Flyout(rnd, target))
        self.reload_left = s.reload_s
        self._launch_fx(st, muzzle, f)
        st._queue_sound("pop", muzzle, gain=0.8)
        st._say(f"{s.label} AWAY")

    def _beam_point(self, st):
        """Where the beam rests: along the aim ray, ranged to the
        designated track when there is one (the aiming unit ranges the
        target — aim error then displaces the beam by angle x range,
        which is exactly the SACLOS skill demand), else the terrain hit,
        else max range."""
        eye = self._eye(st)
        aim = self._aim(st)
        if self.track is not None and not getattr(self.track, "done",
                                                  False):
            rng = float(np.linalg.norm(
                np.asarray(self.track.pos, dtype=np.float64) - eye))
            return eye + aim * rng
        hit = self._ray_ground(st)
        if hit is not None:
            return hit
        return eye + aim * self.weapon.range_m

    def _launch_fx(self, st, muzzle, f) -> None:
        """Eject puff at the muzzle + the MANPADS backblast cone."""
        fx = st.effects
        rng = fx.rng
        fx.smoke.emit(10, muzzle + f * 0.6, 0.5, f * 14.0 + WIND, 3.0,
                      (1.2, 2.4), (0.35, 1.6),
                      ((0.78, 0.76, 0.70), (0.62, 0.62, 0.60)), rng,
                      alpha01=(0.7, 0.05), fade_in=0.03, stretch=0.02)
        back = muzzle - f * 2.2
        idx = fx.smoke.emit(16, back, 0.7, -f * 22.0 + WIND, 5.0,
                            (0.8, 1.8), (0.5, 2.6),
                            ((0.72, 0.68, 0.60), (0.55, 0.52, 0.47)), rng,
                            alpha01=(0.75, 0.04), fade_in=0.02,
                            stretch=0.03)
        # dust kicked off the ground behind the gunner
        g = self._ground_fn(st)(float(back[0]), float(back[2]))
        if back[1] - g < 3.0:
            fx.smoke.emit(12, np.array([back[0], g + 0.4, back[2]]),
                          1.4, -f * 9.0 + np.array([0.0, 2.5, 0.0]), 2.5,
                          (1.5, 3.2), (0.8, 3.4),
                          ((0.55, 0.50, 0.42), (0.44, 0.41, 0.36)), rng,
                          alpha01=(0.6, 0.04), fade_in=0.05)
        _ = idx

    # ------------------------------------------------------------- update

    def update(self, dt: float, st) -> None:
        if st.walker is None:
            return
        self._t += dt
        self.ads += ((1.0 if (self._ads_held and self.weapon is not None
                              and not st.freecam and st.zoom_i == 0)
                      else 0.0) - self.ads) * min(1.0, dt * 10.0)
        if self.reload_left > 0.0:
            self.reload_left = max(0.0, self.reload_left - dt)

        # TONE -> LOCK progression (IR), and lock-hold checks.
        if self.seek_state == "tone":
            if not self._designation_valid(st):
                self._clear_designation()
                st._say("TONE LOST")
            else:
                self._tone_left -= dt
                if self._tone_left <= 0.0:
                    self.seek_state = "lock"
                    st._say("LOCK")
        elif self.seek_state == "lock" and self.weapon is not None \
                and self.weapon.seeker == "ir":
            self._occ_left -= dt
            if self._occ_left <= 0.0:
                self._occ_left = 0.15
                if not self._designation_valid(st):
                    self._clear_designation()
                    st._say("LOCK LOST")

        # Fly the rounds.
        for fo in self.flyouts:
            if fo.beam:
                fo.target.move(self._beam_point(st), dt)
            events: list = []
            fo.rnd.step(dt, events)
            for kind, pos in events:
                self._round_event(st, fo, kind, pos)
            self._emit_trail(st, fo, dt)
        self.flyouts = [fo for fo in self.flyouts if not fo.rnd.done]

    def _round_event(self, st, fo, kind, pos) -> None:
        fx = st.effects
        if kind == "ignite":
            fx.fire.emit(8, pos, 0.4, (0.0, 0.0, 0.0), 4.0, (0.08, 0.18),
                         (0.5, 1.6), ((1.0, 0.95, 0.8), (1.0, 0.55, 0.15)),
                         fx.rng)
            st._queue_sound("pop", pos, gain=0.5)
        elif kind == "dart_sep":
            fo.sep_t = fo.rnd.t
            fx.smoke.emit(6, pos, 0.5, WIND, 2.0, (1.0, 2.0), (0.4, 1.8),
                          ((0.8, 0.8, 0.78), (0.65, 0.66, 0.66)), fx.rng,
                          alpha01=(0.5, 0.04))
        elif kind == "hit":
            self._explosion(st, pos, 1.0)
            tgt = fo.rnd.victim
            if isinstance(tgt, _BeamPoint):
                tgt = None
            if tgt is not None and not getattr(tgt, "done", True):
                tgt.done = True
                self._explosion(st, np.asarray(tgt.pos, dtype=np.float64),
                                1.6)
                st._say(f"SPLASH - {tgt.variant.label}")
            elif fo.rnd.ground_point is not None:
                st._say("IMPACT ON POINT")
        elif kind == "ground":
            self._dirt_burst(st, pos,
                             1.4 if fo.rnd.spec.warhead_kg > 2.0 else 1.0)
            if fo.rnd.hit:
                st._say("IMPACT ON POINT")
        elif kind == "self_destruct":
            fx.smoke.emit(8, pos, 0.8, WIND, 1.5, (2.5, 5.0), (1.0, 4.0),
                          ((0.62, 0.62, 0.62), (0.5, 0.5, 0.5)), fx.rng,
                          alpha01=(0.55, 0.04))
            fx.fire.emit(4, pos, 0.4, (0.0, 0.0, 0.0), 2.0, (0.1, 0.2),
                         (0.6, 1.4), ((1.0, 0.9, 0.7), (1.0, 0.6, 0.2)),
                         fx.rng)
            st._queue_sound("pop", pos, gain=0.5)
        elif kind == "lock_lost":
            st._say("MISSILE LOST TRACK - BALLISTIC")

    def _explosion(self, st, pos, scale) -> None:
        fx = st.effects
        r = fx.rng
        fx.fire.emit(int(26 * scale), pos, 1.2 * scale,
                     (0.0, 2.0, 0.0), 9.0, (0.15, 0.45),
                     (1.2 * scale, 3.6 * scale),
                     ((1.0, 0.97, 0.85), (1.0, 0.5, 0.12)), r)
        fx.smoke.emit(int(18 * scale), pos, 1.5 * scale,
                      WIND + np.array([0.0, 3.0, 0.0]), 4.0, (4.0, 9.0),
                      (1.6 * scale, 7.5 * scale),
                      ((0.30, 0.29, 0.28), (0.52, 0.52, 0.52)), r,
                      alpha01=(0.8, 0.05), fade_in=0.03)
        fx.spray.emit(int(20 * scale), pos, 0.6, (0.0, 14.0, 0.0), 16.0,
                      (0.6, 1.5), (0.10, 0.30),
                      ((1.0, 0.8, 0.4), (0.6, 0.3, 0.1)), r)
        st._queue_sound("boom", pos)

    def _dirt_burst(self, st, pos, scale) -> None:
        fx = st.effects
        r = fx.rng
        fx.fire.emit(int(10 * scale), pos, 0.7 * scale, (0.0, 6.0, 0.0),
                     5.0, (0.10, 0.25), (0.8 * scale, 2.2 * scale),
                     ((1.0, 0.9, 0.7), (1.0, 0.5, 0.15)), r)
        idx = fx.smoke.emit(int(26 * scale), pos, 1.0,
                            np.array([0.0, 12.0, 0.0]) + WIND, 4.0,
                            (2.5, 6.0), (1.2 * scale, 6.0 * scale),
                            ((0.50, 0.44, 0.36), (0.42, 0.40, 0.36)), r,
                            alpha01=(0.8, 0.05), fade_in=0.03)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            sp = r.uniform(4.0, 14.0, len(idx))
            fx.smoke.vel[idx, 0] += (np.sin(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 2] += (np.cos(ang) * sp).astype(np.float32)
        fx.spray.emit(int(14 * scale), pos, 0.4, (0.0, 16.0, 0.0), 10.0,
                      (0.5, 1.2), (0.08, 0.22),
                      ((0.5, 0.42, 0.3), (0.35, 0.3, 0.22)), r)
        st._queue_sound("boom", pos)

    def _emit_trail(self, st, fo, dt) -> None:
        rnd = fo.rnd
        if rnd.done or rnd.phase == "eject":
            fo._last_trail = None
            return
        s = rnd.spec
        fx = st.effects
        r = fx.rng
        h = rnd.heading()
        tail = rnd.pos - h * (s.length_m * 0.5)
        if rnd.burning:
            flick = 1.0 + 0.25 * math.sin(self._t * 2.0 * math.pi * 31.0)
            fx.fire.emit(1, tail - h * (s.flame_len_m * 0.4), 0.12,
                         -h * 30.0, 3.0, (0.05, 0.12),
                         (0.10 * s.flame_len_m * flick,
                          0.30 * s.flame_len_m * flick),
                         ((1.0, 0.97, 0.86), (1.0, 0.55, 0.14)), r,
                         stretch=0.02)
            # glow dot for range visibility
            fx.fire.emit(1, tail, 0.05, (0.0, 0.0, 0.0), 0.0, (0.04, 0.08),
                         (s.flame_len_m * 0.9, s.flame_len_m * 1.2),
                         ((0.5, 0.42, 0.30), (0.4, 0.32, 0.2)), r)
        if fo._last_trail is None:
            fo._last_trail = tail.copy()
            return
        seg = tail - fo._last_trail
        dist = float(np.linalg.norm(seg))
        if dist <= 1e-6:
            return
        # Smoke only while the motor produces it (darts fly clean).
        if rnd.burning and not rnd.darts:
            fo._smoke_carry += dist * s.smoke_per_m
            n = int(fo._smoke_carry)
            fo._smoke_carry -= n
            u = _perp(h)
            v = np.cross(h, u)
            for k in range(n):
                t01 = (k + 0.5) / max(n, 1)
                p = fo._last_trail + seg * t01
                # the MANPADS corkscrew: rolling-airframe helix, purely
                # cosmetic (guidance never sees it)
                if s.corkscrew_m > 0.0:
                    grow = min((fo._path_m + dist * t01) / 120.0, 1.0)
                    ph = (fo._path_m + dist * t01) * (2.0 * math.pi / 9.0)
                    p = p + (u * math.cos(ph) + v * math.sin(ph)) \
                        * (s.corkscrew_m * grow)
                fx.smoke.emit(1, p, 0.25, WIND + np.array([0.0, 0.2, 0.0]),
                              0.5, _SFX_SMOKE_LIFE,
                              (s.trail_width_m, s.trail_width_m * 7.0),
                              ((0.90, 0.90, 0.88), (0.72, 0.73, 0.73)), r,
                              alpha01=(0.55, 0.03), fade_in=0.10)
        fo._path_m += dist
        fo._last_trail = tail.copy()

    # ------------------------------------------------------------ drawing

    def _basis(self, st):
        w = st.walker
        yaw, pitch = w.yaw, w.pitch
        cp = math.cos(pitch)
        f = np.array([math.sin(yaw) * cp, math.sin(pitch),
                      math.cos(yaw) * cp])
        r = np.array([math.cos(yaw), 0.0, -math.sin(yaw)])
        u = np.cross(f, r)               # view-up (f x r IS up here)
        return f, r, u

    def _ensure_gl(self):
        if self._gl_ready:
            return
        from engine.mesh import Mesh
        from models.manpads_model import (build_dart, build_launcher,
                                          build_missile)
        for s in WEAPONS:
            self._launcher_meshes[s.id] = Mesh(build_launcher(s.id))
            self._missile_meshes[s.id] = Mesh(build_missile(s.id))
        self._dart_mesh = Mesh(build_dart())
        self._gl_ready = True

    def draw_world(self, st) -> None:
        if st.walker is None:
            return
        if self.weapon is None and not self.flyouts:
            return
        self._ensure_gl()
        rend = st.app.renderer
        # rounds in flight
        for fo in self.flyouts:
            rnd = fo.rnd
            if rnd.done:
                continue
            rot = math3d.rotation_from_forward(rnd.heading())
            if rnd.darts:
                f = rnd.heading()
                u = _perp(f)
                v = np.cross(f, u)
                spread = min((rnd.t - (fo.sep_t or rnd.t)) * 1.6, 2.2)
                for k in range(3):
                    a = math.radians(90.0 + 120.0 * k)
                    off = (u * math.cos(a) + v * math.sin(a)) * spread
                    rend.draw_mesh(self._dart_mesh, rnd.pos + off, rot)
            else:
                rend.draw_mesh(self._missile_meshes[rnd.spec.id],
                               rnd.pos, rot)
        # shouldered view model
        if self.weapon is not None and not st.freecam:
            f, r, u = self._basis(st)
            eye = self._eye(st)
            a = self.ads
            hip = eye + f * 0.55 + r * 0.20 - u * 0.20
            sight = eye + f * 0.50 + r * 0.05 - u * 0.085
            pos = hip * (1.0 - a) + sight * a
            wk = st.walker
            if wk.on_ground and math.hypot(wk.vx, wk.vz) > 0.3:
                bob = math.sin(wk.walked * 2.0 * math.pi / 0.75)
                pos = pos - u * (bob * 0.008 * (1.0 - 0.7 * a))
            rot = math3d.rotation_from_forward(f)
            rend.draw_mesh(self._launcher_meshes[self.weapon.id], pos, rot)

    # ---------------------------------------------------------------- HUD

    def draw_hud(self, st, w: int, h: int) -> bool:
        if st.walker is None or st.freecam:
            return False
        text = st.text
        drew = False
        if self.weapon is not None and not self.locker_open \
                and st.zoom_i == 0 and not st.ui_open:
            self._draw_reticle(st, text, w, h)
            self._draw_weapon_card(text, w, h)
            drew = True
        if self.locker_open:
            self._draw_locker(text, w, h)
            drew = True
        return drew

    def _draw_reticle(self, st, text, w, h) -> None:
        cx, cy = w * 0.5, h * 0.5
        s = self.weapon
        col = UI_ACC if self.seek_state == "lock" else \
            (UI_WARN if self.seek_state == "tone" else (*UI_TXT, 0.8)[:3])
        # outer ring
        pts = [(cx + math.cos(a) * 46.0, cy + math.sin(a) * 46.0)
               for a in np.linspace(0.0, 2.0 * math.pi, 40)]
        text.draw_lines(pts, (*col, 0.55), 1.0)
        # cardinal ticks + center dot
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            text.draw_lines([(cx + dx * 34, cy + dy * 34),
                             (cx + dx * 46, cy + dy * 46)], (*col, 0.9),
                            1.0)
        text.draw_rect(cx - 1.5, cy - 1.5, 3, 3, (*col, 1.0))
        # seeker state line
        state_txt = {"idle": "CAGED - MMB DESIGNATE",
                     "tone": "TONE ...",
                     "lock": ("LOCK" if s.seeker == "ir"
                              else "BEAM - RIDE THE AIM")}[self.seek_state]
        tw = text.text_width(state_txt, SMALL_SIZE)
        text.draw_text(cx - tw * 0.5, cy + 58, state_txt, (*col, 0.95),
                       SMALL_SIZE)
        # designation diamond + range
        mark_pos = None
        if self.track is not None and not getattr(self.track, "done",
                                                  False):
            mark_pos = np.asarray(self.track.pos, dtype=np.float64)
        elif self.ground_mark is not None:
            mark_pos = self.ground_mark
        if mark_pos is not None:
            sp = st._screen_pos(w, h, mark_pos)
            if sp is not None:
                x, y = sp
                d = 11.0
                text.draw_lines([(x, y - d), (x + d, y), (x, y + d),
                                 (x - d, y), (x, y - d)], (*col, 0.95),
                                1.0)
                rng = float(np.linalg.norm(mark_pos - self._eye(st)))
                text.draw_text(x + 15, y - 7, f"{rng:0.0f} M",
                               (*col, 0.9), SMALL_SIZE)
        # rounds in the air: tiny chevrons
        for fo in self.flyouts:
            sp = st._screen_pos(w, h, fo.rnd.pos)
            if sp is not None:
                x, y = sp
                text.draw_lines([(x - 5, y + 4), (x, y - 4), (x + 5, y + 4)],
                                (*UI_TXT, 0.75), 1.0)

    def _draw_weapon_card(self, text, w, h) -> None:
        s = self.weapon
        pw, ph = 300, 86
        x0, y0 = w - pw - 28, h - ph - 26
        text.draw_rect(x0, y0, pw, ph, UI_GLASS)
        text.draw_rect(x0, y0, pw, 1, UI_HAIR)
        text.draw_rect(x0, y0 + ph - 1, pw, 1, UI_HAIR)
        text.draw_rect(x0, y0, 1, ph, UI_HAIR)
        text.draw_rect(x0 + pw - 1, y0, 1, ph, UI_HAIR)
        text.draw_text(x0 + 16, y0 + 12, s.label, UI_TXT, BODY_SIZE)
        text.draw_text(x0 + pw - 44, y0 + 12, s.nation, UI_ACC, SMALL_SIZE)
        sub = ("IR SEEKER" if s.seeker == "ir" else "LASER BEAM") + \
            f"   {s.range_m / 1000.0:0.1f} KM   M{s.peak_speed_ms / 320.0:0.1f}"
        text.draw_text(x0 + 16, y0 + 36, sub, UI_DIM, SMALL_SIZE)
        if self.reload_left > 0.0:
            frac = 1.0 - self.reload_left / max(s.reload_s, 1e-6)
            text.draw_rect(x0 + 16, y0 + 62, (pw - 32) * frac, 3,
                           (*UI_WARN, 0.9))
            text.draw_text(x0 + 16, y0 + 54, "NEW TUBE", (*UI_WARN, 0.9),
                           SMALL_SIZE)
        else:
            text.draw_rect(x0 + 16, y0 + 62, pw - 32, 3, (*UI_ACC, 0.55))
            text.draw_text(x0 + 16, y0 + 54, "READY", (*UI_ACC, 0.9),
                           SMALL_SIZE)

    def _draw_locker(self, text, w, h) -> None:
        pw = 460
        x0 = 48
        y0 = 42
        y1 = h - 42
        text.draw_rect(x0, y0, pw, y1 - y0, UI_GLASS)
        for rx, ry, rw, rh in ((x0, y0, pw, 1), (x0, y1 - 1, pw, 1),
                               (x0, y0, 1, y1 - y0),
                               (x0 + pw - 1, y0, 1, y1 - y0)):
            text.draw_rect(rx, ry, rw, rh, UI_HAIR)
        x = x0 + 26
        text.draw_text(x, y0 + 20, "WEAPONS", UI_TXT, HEADER_SIZE,
                       scale=1.25)
        text.draw_text(x, y0 + 52, "SHOULDER-FIRED - WALK MODE", UI_ACC,
                       SMALL_SIZE)
        text.draw_rect(x, y0 + 76, pw - 52, 1, UI_HAIR)
        self._ui_rects = []
        y = y0 + 96
        mx, my = pygame.mouse.get_pos()
        for s in WEAPONS:
            row_h = 74
            rect = (x0 + 14, y - 6, x0 + pw - 14, y - 6 + row_h)
            self._ui_rects.append(("weapon", s.id, rect))
            hovered = (rect[0] <= mx <= rect[2]
                       and rect[1] <= my <= rect[3])
            selected = self.weapon is not None and self.weapon.id == s.id
            if selected:
                text.draw_rect(rect[0], rect[1], 2, row_h, (*UI_ACC, 0.95))
            if hovered and not selected:
                text.draw_rect(rect[0], rect[1], rect[2] - rect[0], row_h,
                               (1.0, 1.0, 1.0, 0.05))
            col = UI_TXT if (selected or hovered) else UI_DIM
            text.draw_text(x + 12, y, s.label, col, BODY_SIZE)
            text.draw_text(x0 + pw - 70, y, s.nation, UI_ACC, SMALL_SIZE)
            text.draw_text(x + 12, y + 22, s.blurb, (*UI_DIM, 0.85),
                           SMALL_SIZE)
            spec_line = (f"{s.range_m / 1000.0:0.1f} KM   "
                         f"M{s.peak_speed_ms / 320.0:0.1f}   "
                         f"{s.warhead_kg:0.1f} KG   "
                         + ("PN HOMING" if s.seeker == "ir"
                            else "SACLOS BEAM"))
            text.draw_text(x + 12, y + 42, spec_line, (*UI_ACC, 0.55),
                           SMALL_SIZE)
            y += row_h + 6
        y += 8
        rect = (x0 + 14, y - 4, x0 + pw - 14, y + 24)
        self._ui_rects.append(("stow", "", rect))
        hovered = rect[0] <= mx <= rect[2] and rect[1] <= my <= rect[3]
        text.draw_text(x + 12, y, "STOW WEAPON",
                       UI_TXT if hovered else UI_DIM, BODY_SIZE)
        text.draw_text(x, y1 - 30,
                       "CLICK TO SHOULDER   F1 OR ESC CLOSES   "
                       "RMB SIGHT   MMB DESIGNATE   LMB FIRE",
                       (*UI_DIM, 0.9), SMALL_SIZE)

    # ------------------------------------------------------------ cleanup

    def dispose(self) -> None:
        for m in list(self._launcher_meshes.values()) \
                + list(self._missile_meshes.values()):
            if hasattr(m, "delete"):
                m.delete()
        if self._dart_mesh is not None and hasattr(self._dart_mesh,
                                                   "delete"):
            self._dart_mesh.delete()
        self._launcher_meshes.clear()
        self._missile_meshes.clear()
        self._dart_mesh = None
        self._gl_ready = False


def _perp(v: np.ndarray) -> np.ndarray:
    """A unit vector perpendicular to v (stable choice, no RNG)."""
    a = np.array([0.0, 1.0, 0.0]) if abs(float(v[1])) < 0.9 \
        else np.array([1.0, 0.0, 0.0])
    p = np.cross(v, a)
    n = float(np.linalg.norm(p))
    return p / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
