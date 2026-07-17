"""ICBM flight core for cinematic mode: RS-28 Sarmat + LGM-30G Minuteman III.

GL-free (LOCKED). Every constant traces to
docs/research/icbm_reference_2026-07-17.md; `~` there = estimate.

The short-range physics (a 16 km map cannot absorb a 7 km/s burnout)
uses the REAL mechanisms, no dice and no fudge (research doc section 3):

- Targeting is uniform-gravity Lambert in time-of-arrival form: the
  velocity that puts the vehicle on a ballistic arc arriving at the
  target exactly when the TOA clock runs out is
  ``v_req = D/tau + 0.5*g*tau*up`` (D = target - pos, tau = time left).
- Solids (Minuteman III) cannot shut down, so boost flies GEMS —
  Generalized Energy Management Steering (US 4,387,865 / 10,323,907):
  thrust points ``theta = arccos(|Vg| / C)`` off the velocity-to-be-
  gained Vg, the orthogonal component rotating slowly (the corkscrew
  that visibly WASTES energy).  Under that law d|Vg|/dt = -a*|Vg|/C
  while dC/dt = -a, so the ratio |Vg|/C is invariant: Vg reaches zero
  exactly as the last propellant burns.  All stages burn to depletion
  on the real schedule; the post-boost vehicle trims the residual —
  which is precisely what a PSRE/PBV exists for.
- Liquids (Sarmat) burn both boost stages the same way and the PBV
  engine simply SHUTS DOWN at Vg ~ 0 (the "cutoff" event).

Straight-line boost drag is ignored (near-vertical climb at GEMS-shaped
moderate speeds; error is small against the PBV trim authority) and the
RV falls the exact uniform-gravity arc — the trajectory is closed-form
consistent with the guidance, so impact lands on the designated point
deterministically.  Zero RNG anywhere in this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

GRAVITY = 9.81
UP = np.array([0.0, 1.0, 0.0])

# Guidance shape knobs (shared; per-weapon numbers live in the specs).
GATE_TILT_DEG = 3.0        # programmed tilt toward target below the gate
SLEW_DEG_S = 30.0          # attitude slew limit (TVC authority, visual)
VG_TRIM_MS = 0.4           # PBV stops trimming below this |Vg|
TAU_GUARD_S = 2.0          # stop guiding this close to arrival


@dataclass(frozen=True)
class IcbmStage:
    label: str
    gross_kg: float
    prop_kg: float
    thrust_n: float          # average thrust over the burn
    burn_s: float

    @property
    def mdot(self) -> float:
        return self.prop_kg / self.burn_s

    @property
    def v_e(self) -> float:  # effective exhaust velocity
        return self.thrust_n / self.mdot


@dataclass(frozen=True)
class IcbmSpec:
    id: str
    label: str
    nation: str
    blurb: str
    length_m: float
    diameter_m: float
    launch_mode: str         # 'hot' (in-tube ignition) | 'cold' (mortar)
    stages: tuple            # boost stages only (IcbmStage, ...)
    bus_kg: float            # PBV + RV dry
    bus_prop_kg: float
    bus_thrust_n: float
    bus_isp_s: float         # storable bipropellant (RS-14 class)
    door_s: float            # closure door / silo lid slide time
    base_depth_m: float      # missile TAIL below ground at rest
    toa_s: float             # time of arrival after ignition (the loft knob)
    gate_agl_m: float        # below this fly the vertical program
    spin_hz: float           # GEMS orthogonal rotation rate
    shake_amp: float         # observer shake at the acoustic hit
    cutoff_event: bool       # liquids report engine shutdown
    # Visual identity (research doc 1.5 / 2.5 plume phenomenology).
    flame_core: tuple = (1.0, 0.98, 0.88)
    flame_edge: tuple = (1.0, 0.57, 0.14)
    flame_len_x: float = 1.4    # flame length as a multiple of body length
    smoke_fresh: tuple = (0.93, 0.92, 0.87)
    smoke_old: tuple = (0.70, 0.72, 0.72)
    smoke_per_m: float = 3.0    # column density (48N6 = 2.0 for scale)
    width_mult: float = 2.2     # column width vs the S-300 family
    eject_exit_v: float = 0.0   # cold: tube-exit speed
    hang_s: float = 0.0         # cold: unlit coast after tube exit


# --------------------------------------------------------------- the weapons
# docs/research/icbm_reference_2026-07-17.md tables 1.2 / 2.2.

MINUTEMAN_III = IcbmSpec(
    id="mm3", label="MINUTEMAN III", nation="USA",
    blurb="LGM-30G - HOT LAUNCH, SMOKE RING, WHITE PILLAR",
    length_m=18.3, diameter_m=1.68, launch_mode="hot",
    stages=(
        IcbmStage("M55A1", 23230.0, 20780.0, 790e3, 61.0),
        IcbmStage("SR19", 7270.0, 6240.0, 267.7e3, 65.0),
        IcbmStage("SR73", 3710.0, 3310.0, 152.0e3, 61.0),
    ),
    bus_kg=1100.0, bus_prop_kg=120.0, bus_thrust_n=1.4e3,   # PSRE / RS-14
    bus_isp_s=290.0,
    door_s=1.5,              # 110 t door on gas actuators, ~35 mph
    base_depth_m=22.0,       # 80 ft tube, 18.3 m missile: nose near mouth
    toa_s=340.0, gate_agl_m=1500.0, spin_hz=0.06,
    shake_amp=1.4, cutoff_event=False,
    # Aluminized solid: brilliant white-orange flame, DENSE white pillar.
    flame_core=(1.0, 0.99, 0.90), flame_edge=(1.0, 0.62, 0.16),
    flame_len_x=1.6,
    smoke_fresh=(0.94, 0.93, 0.88), smoke_old=(0.71, 0.73, 0.73),
    smoke_per_m=3.4, width_mult=2.2)

SARMAT = IcbmSpec(
    id="sarmat", label="SARMAT", nation="RUSSIA",
    blurb="RS-28 - 208 T COLD MORTAR EJECT, HYPERGOLIC",
    length_m=35.3, diameter_m=3.0, launch_mode="cold",
    stages=(
        IcbmStage("PDU-99", 158000.0, 150000.0, 4600e3, 95.0),
        IcbmStage("STAGE 2", 40500.0, 37500.0, 760e3, 165.0),
    ),
    bus_kg=7600.0, bus_prop_kg=2000.0, bus_thrust_n=20e3,
    bus_isp_s=300.0,
    door_s=6.0,              # the huge lid walks open on rails
    base_depth_m=33.0,       # ~39 m silo, TPK; tail rides near the bottom
    toa_s=560.0, gate_agl_m=1800.0, spin_hz=0.05,
    shake_amp=1.8, cutoff_event=True,
    # Hypergolic N2O4/UDMH: hard orange flame, thin brown-grey haze —
    # the mortar puff at the silo is the dirtiest moment of the launch.
    flame_core=(1.0, 0.88, 0.62), flame_edge=(1.0, 0.48, 0.12),
    flame_len_x=1.0,
    smoke_fresh=(0.56, 0.53, 0.49), smoke_old=(0.46, 0.45, 0.44),
    smoke_per_m=0.9, width_mult=1.6,
    eject_exit_v=22.0, hang_s=1.45)

ICBMS = (MINUTEMAN_III, SARMAT)
ICBM_BY_ID = {s.id: s for s in ICBMS}


class IcbmLaunch:
    """One ICBM flying from silo to a designated ground point.

    Duck-types the ScriptedLaunch contract CinematicState.sim_step uses
    (.t .pos .done .variant .step(dt, events) .emit(fx, dt) plus the fx
    event hooks); event kinds beyond the S-300 set are additive:
    door / eject / pallet / smoke_ring / stage / cutoff / impact.
    """

    def __init__(self, spec: IcbmSpec, silo, target, ground_h,
                 door_open: bool = False):
        self.spec = spec
        self.variant = spec              # .shake_amp / .label for sim_step
        self.ground_h = ground_h
        self.t = 0.0
        self.done = False
        sx, sy, sz = float(silo[0]), float(silo[1]), float(silo[2])
        self._silo = np.array([sx, sy, sz], dtype=np.float64)
        tx, tz = float(target[0]), float(target[2])
        self._target = np.array([tx, float(ground_h(tx, tz)), tz],
                                dtype=np.float64)
        # pos = missile TAIL, world coords.
        self.pos = np.array([sx, sy - spec.base_depth_m, sz],
                            dtype=np.float64)
        self.vel = np.zeros(3, dtype=np.float64)
        self.axis = UP.copy()            # attitude (slew-limited)
        self.mass = (sum(s.gross_kg for s in spec.stages)
                     + spec.bus_kg + spec.bus_prop_kg)
        # Cold-launch mortar: reach exit_v over the tube run.
        self._eject_a = ((spec.eject_exit_v ** 2)
                         / (2.0 * spec.base_depth_m)
                         if spec.launch_mode == "cold" else 0.0)

        # Phase state.
        self.stage_idx = 0               # current boost stage (draw hint)
        self.rv_only = False             # after final sep (draw hint)
        self.ignite_t = None
        self.burnout_t = None            # end of last BOOST stage
        self.apex_m = self.pos[1]
        self._door_done = False
        self._ejected = False            # cold: tail clear of the tube
        self._eject_t = None
        self._pallet_done = False
        self._ring_done = False          # hot: the one smoke ring
        self._ignited = False
        self._burned_in_stage = 0.0
        self._bus_prop_left = spec.bus_prop_kg
        self._cut = False                # bus finished (trim done / cutoff)
        self._spin_e1 = None
        self._spin_e2 = None
        # Subsequent-stage delta-v capability, precomputed once.
        self._dv_after = self._dv_after_table()
        if door_open:                    # silo door already stands open
            self._door_done = True
            self.t = spec.door_s

    @property
    def ignited(self) -> bool:
        return self._ignited

    @property
    def door_frac(self) -> float:
        """0..1 door/lid slide for the draw layer."""
        if self._door_done and self.spec.door_s > 0.0:
            return min(1.0, self.t / self.spec.door_s)
        return 1.0 if self._door_done else 0.0

    # ------------------------------------------------------------ capability

    def _dv_after_table(self):
        """dv_after[i] = full delta-v of BOOST stages after i.

        The bus is deliberately EXCLUDED: it is the trim reserve, not
        energy-management capability.  With C counting boost stages
        only, C reaches zero exactly at final-stage depletion, so the
        arccos ratio crosses 1 late in the burn and the law finishes
        fully aligned — |Vg| and C ride to ~zero together (the classic
        GEMS endgame).  Counting the bus left |Vg| = ratio*C_bus at
        burnout, which is more than the PBV can trim (measured: 156 m/s
        residual vs 69 m/s authority, 15 km miss)."""
        spec = self.spec
        bus_tot = spec.bus_kg + spec.bus_prop_kg
        out = []
        n = len(spec.stages)
        for i in range(n):
            dv = 0.0
            for j in range(i + 1, n):
                m0 = (sum(s.gross_kg for s in spec.stages[j:]) + bus_tot)
                dv += spec.stages[j].v_e * math.log(m0 / (m0
                                                          - spec.stages[j].prop_kg))
            out.append(dv)
        out.append(0.0)                  # only the bus flies: no capability
        return out

    def _capability(self) -> float:
        """Remaining GEMS delta-v (boost stages only; bus = trim reserve)."""
        spec = self.spec
        if self.rv_only:
            if self._bus_prop_left <= 0.0:
                return 0.0
            return (spec.bus_isp_s * GRAVITY) \
                * math.log(self.mass / (self.mass - self._bus_prop_left))
        st = spec.stages[self.stage_idx]
        prop_rem = st.prop_kg - self._burned_in_stage
        c = st.v_e * math.log(self.mass / max(self.mass - prop_rem, 1.0))
        return c + self._dv_after[self.stage_idx]

    # -------------------------------------------------------------- guidance

    def _tau(self) -> float:
        return self.spec.toa_s - (self.t - self.ignite_t)

    def _v_req(self) -> np.ndarray:
        tau = max(self._tau(), 1.0)
        d = self._target - self.pos
        return d / tau + UP * (0.5 * GRAVITY * tau)

    def vg(self) -> np.ndarray:
        return self._v_req() - self.vel

    def _thrust_dir(self) -> np.ndarray:
        """Vertical program below the gate; Lambert+GEMS above it."""
        agl = self.pos[1] - self._silo[1]
        gate = self.spec.gate_agl_m
        to_t = self._target - self._silo
        az = math.atan2(to_t[0], to_t[2])
        tilt = math.radians(GATE_TILT_DEG) * min(1.0, max(agl, 0.0) / gate)
        vertical = np.array([math.sin(az) * math.sin(tilt),
                             math.cos(tilt),
                             math.cos(az) * math.sin(tilt)])
        if agl < gate:
            return vertical
        vg = self.vg()
        nvg = float(np.linalg.norm(vg))
        cap = self._capability()
        if nvg < 1e-6 or cap < 1e-6:
            return self.axis.copy()
        e = vg / nvg
        if self._spin_e1 is None:
            r = np.cross(e, UP)
            if np.linalg.norm(r) < 1e-6:
                r = np.cross(e, np.array([1.0, 0.0, 0.0]))
            self._spin_e1 = r / np.linalg.norm(r)
            self._spin_e2 = np.cross(e, self._spin_e1)
        # Re-orthogonalize the spin frame against the drifting Vg axis.
        e1 = self._spin_e1 - e * float(np.dot(self._spin_e1, e))
        n1 = float(np.linalg.norm(e1))
        if n1 < 1e-6:
            e1 = np.cross(e, UP)
            n1 = float(np.linalg.norm(e1))
        e1 /= n1
        e2 = np.cross(e, e1)
        self._spin_e1, self._spin_e2 = e1, e2
        ratio = min(max(nvg / cap, 0.0), 1.0)
        theta = math.acos(ratio)
        ph = 2.0 * math.pi * self.spec.spin_hz * (self.t - self.ignite_t)
        n = e1 * math.cos(ph) + e2 * math.sin(ph)
        return e * math.cos(theta) + n * math.sin(theta)

    def _slew(self, want: np.ndarray, dt: float) -> None:
        """Rate-limit the attitude toward the commanded direction."""
        want = want / max(float(np.linalg.norm(want)), 1e-9)
        cosang = float(np.clip(np.dot(self.axis, want), -1.0, 1.0))
        ang = math.acos(cosang)
        max_step = math.radians(SLEW_DEG_S) * dt
        if ang <= max_step or ang < 1e-9:
            self.axis = want
            return
        f = max_step / ang
        mixed = self.axis * (1.0 - f) + want * f
        self.axis = mixed / float(np.linalg.norm(mixed))

    # ----------------------------------------------------------------- step

    def step(self, dt: float, events: list) -> None:
        if self.done:
            return
        spec = self.spec
        self.t += dt

        if not self._door_done:
            if self.t >= 0.0:
                self._door_done = True
                events.append(("door", self._silo.copy()))
            return
        if self.t < spec.door_s:
            return

        # --- pre-ignition transport out of the ground -------------------
        # Every path in this block RETURNS: powered flight starts on the
        # tick after light-off (no double integration on transition ticks).
        if not self._ignited:
            if spec.launch_mode == "hot":
                # Fire in the hole: S1 lights at the bottom of the tube.
                self.ignite_t = self.t
                self._ignited = True
                mouth = self._silo + UP * 0.5
                events.append(("ignite", mouth))
                return
            # Mortar ride up the TPK, then the unlit hang.
            if not self._ejected:
                self.vel[1] += self._eject_a * dt
                self.pos += self.vel * dt
                if self.pos[1] >= self._silo[1]:
                    self._ejected = True
                    self._eject_t = self.t
                    events.append(("eject", self.pos.copy()))
                return
            self.vel[1] -= GRAVITY * dt
            self.pos += self.vel * dt
            hang = self.t - self._eject_t
            if not self._pallet_done and hang >= spec.hang_s:
                self._pallet_done = True
                events.append(("pallet", self.pos.copy()))
            if hang >= spec.hang_s + 0.35:
                self.ignite_t = self.t
                self._ignited = True
                events.append(("ignite", self.pos.copy()))
            return

        # --- powered + coast flight -------------------------------------
        thrusting = False
        burn = self.t - self.ignite_t
        if not self.rv_only:
            st = spec.stages[self.stage_idx]
            start = sum(s.burn_s for s in spec.stages[:self.stage_idx])
            if burn < start + st.burn_s:
                thrusting = True
                # Thrust follows the guidance law EXACTLY — TVC autopilot
                # bandwidth dwarfs our dt (a 2.5% average alignment lag
                # from slew-limiting the thrust accumulated 180 m/s of
                # unremovable Vg, measured).  The slew-limited axis is
                # the DRAWN attitude only.
                dirc = self._thrust_dir()
                self._slew(dirc, dt)
                a = st.thrust_n / self.mass
                self.vel += dirc * (a * dt)
                self.mass -= st.mdot * dt
                self._burned_in_stage = st.prop_kg * min(
                    1.0, (burn - start) / st.burn_s)
            else:
                # Separation: shed the dry stage.
                self.mass -= st.gross_kg - st.prop_kg
                self._burned_in_stage = 0.0
                events.append(("stage", self.pos.copy()))
                if self.stage_idx + 1 < len(spec.stages):
                    self.stage_idx += 1
                else:
                    self.rv_only = True
                    self.burnout_t = self.t
                    self.mass = spec.bus_kg + self._bus_prop_left
        elif self._bus_prop_left > 0.0 and not self._cut:
            vg = self.vg()
            nvg = float(np.linalg.norm(vg))
            if nvg < VG_TRIM_MS or self._tau() < TAU_GUARD_S:
                self._cut = True
                if spec.cutoff_event:
                    events.append(("cutoff", self.pos.copy()))
            else:
                thrusting = True
                dirc = vg / nvg
                self._slew(dirc, dt)
                mdot = spec.bus_thrust_n / (spec.bus_isp_s * GRAVITY)
                a = spec.bus_thrust_n / self.mass
                self.vel += dirc * (a * dt)
                self.mass -= mdot * dt
                self._bus_prop_left -= mdot * dt
                if self._bus_prop_left <= 0.0:
                    self._cut = True
                    if spec.cutoff_event:
                        events.append(("cutoff", self.pos.copy()))

        self.vel[1] -= GRAVITY * dt
        self.pos += self.vel * dt
        self.apex_m = max(self.apex_m, float(self.pos[1]))
        self._thrusting = thrusting

        # Hot launch: the ring rolls the moment the tail clears the tube.
        if (spec.launch_mode == "hot" and not self._ring_done
                and self.pos[1] >= self._silo[1]):
            self._ring_done = True
            events.append(("smoke_ring",
                           np.array([self._silo[0], self.pos[1],
                                     self._silo[2]])))

        # Impact: descending into the ground ends the flight.  (Ascent is
        # the only time the vehicle is legitimately below ground level, so
        # the vel < 0 gate alone is safe.)
        if self.vel[1] < 0.0:
            g = float(self.ground_h(float(self.pos[0]),
                                    float(self.pos[2])))
            if self.pos[1] <= g:
                self.pos[1] = g
                events.append(("impact", self.pos.copy()))
                self.done = True
                return
        if self.t - (self.ignite_t or 0.0) > spec.toa_s + 180.0:
            self.done = True             # lost round guard

    def heading(self) -> np.ndarray:
        n = float(np.linalg.norm(self.vel))
        return self.vel / n if n > 1e-6 else UP.copy()

    def burning(self) -> bool:
        return bool(getattr(self, "_thrusting", False))

    # ---------------------------------------------------------------- fx
    # Visual layer only — fx.rng never touches the trajectory.  Layered
    # emission follows cinematic_missiles.ScriptedLaunch (jet / clumped
    # billows / veil + flame), scaled to ICBM class and with two extra
    # regimes the S-300 never reaches: vacuum BLOOM above ~9 km and the
    # REENTRY streak on the way back down.

    BLOOM_ALT = 9000.0

    def emit(self, fx, dt: float) -> None:
        if self.done or not self._ignited:
            return
        spec = self.spec
        r = fx.rng
        h = self.axis
        tail = self.pos
        rel_alt = max(0.0, float(tail[1]) - float(self._silo[1]))
        from game.cinematic_missiles import _wind
        wind = _wind(fx, float(tail[1]))
        flame_len = spec.length_m * spec.flame_len_x
        if self.burning():
            # Flame: stretched additive core + the far-visible glow dot.
            slow = 1.0 + 0.2 * math.sin(self.t * 2.0 * math.pi * 8.0)
            self._flame_carry = getattr(self, "_flame_carry", 0.0) \
                + dt * 150.0 * slow
            n_flame = int(self._flame_carry)
            self._flame_carry -= n_flame
            for _ in range(min(n_flame, 4)):
                back = r.uniform(0.0, flame_len)
                frac = back / max(flame_len, 1e-6)
                col = tuple(np.array(spec.flame_core) * (1 - frac)
                            + np.array(spec.flame_edge) * frac)
                size = (1.0 - 0.5 * frac) * (0.11 * flame_len)
                fx.fire.emit(1, tail - h * back, 0.4, -h * 130.0, 8.0,
                             (0.08, 0.26), (size * 0.5, size * 1.6),
                             (col, col), r, stretch=0.025)
            # Far-visibility glow: flame-length scale — a 2x-length sprite
            # blinded the chase cam (audit shot 30, a white ball).
            fx.fire.emit(1, tail - h * flame_len * 0.3, 0.1,
                         (0.0, 0.0, 0.0), 0.0, (0.05, 0.09),
                         (flame_len * 0.8, flame_len * 1.1),
                         ((0.42, 0.37, 0.28), (0.36, 0.29, 0.20)), r)
            if rel_alt > self.BLOOM_ALT:
                # Vacuum bloom: the plume widens into a huge faint cone.
                self._bloom_carry = getattr(self, "_bloom_carry", 0.0) \
                    + dt * 3.0
                nb = int(self._bloom_carry)
                self._bloom_carry -= nb
                if nb:
                    w_bloom = 14.0 + (rel_alt - self.BLOOM_ALT) * 0.004
                    fx.fire.emit(nb, tail - h * flame_len * 0.8,
                                 w_bloom * 0.3, -h * 60.0, 12.0,
                                 (0.8, 1.6),
                                 (w_bloom, w_bloom * 2.6),
                                 ((0.14, 0.12, 0.10), (0.05, 0.045, 0.04)),
                                 r)
        # Reentry streak: the RV coming back down hot.
        if (self.rv_only and self.vel[1] < -200.0
                and 300.0 < rel_alt < 15000.0
                and float(np.linalg.norm(self.vel)) > 450.0):
            self._rv_carry = getattr(self, "_rv_carry", 0.0) + dt * 26.0
            nrv = int(self._rv_carry)
            self._rv_carry -= nrv
            hd = self.heading()
            for _ in range(min(nrv, 3)):
                fx.fire.emit(1, tail - hd * r.uniform(0.0, 14.0), 0.5,
                             -hd * 90.0, 10.0, (0.10, 0.30), (1.2, 3.4),
                             ((1.0, 0.82, 0.55), (1.0, 0.45, 0.15)), r,
                             stretch=0.03)
            return
        # --- smoke column (dies into the bloom regime) -------------------
        tb = self.t - self.ignite_t
        outgassing = self.burning() or (self.burnout_t is not None
                                        and self.t - self.burnout_t < 0.6)
        if not outgassing or rel_alt > self.BLOOM_ALT:
            self._last_smoke_pos = None
            return
        if getattr(self, "_last_smoke_pos", None) is None:
            self._last_smoke_pos = tail.copy()
            return
        seg = tail - self._last_smoke_pos
        dist = float(np.linalg.norm(seg))
        if dist <= 1e-6:
            return
        seg_dir = seg / dist
        # The first ~5 km of pillar carries the scene (research: dense to
        # high altitude, but the budget must live inside SMOKE_CAP).
        ls = 1.0 / (1.0 + (rel_alt / 2600.0) ** 1.6)
        taper = 1.0 / (1.0 + (rel_alt / 1800.0) ** 2)
        wm = spec.width_mult * (1.0 + 0.9 * math.exp(-rel_alt / 400.0))
        dia = spec.diameter_m
        # JET off the nozzle.
        self._jet_carry = getattr(self, "_jet_carry", 0.0) \
            + dist * 0.5 * taper * (spec.smoke_per_m / 1.8)
        n_jet = int(self._jet_carry)
        self._jet_carry -= n_jet
        for _ in range(n_jet):
            radial = np.cross(h, r.standard_normal(3))
            rn = float(np.linalg.norm(radial))
            radial = radial / rn * r.uniform(10.0, 16.0) if rn > 1e-6 \
                else 0.0
            jl = max(ls, 0.35)
            fx.smoke.emit(1, tail - h * r.uniform(1.0, 2.0), 0.8,
                          wind - h * 55.0 + radial, 3.0,
                          (6.0 * jl, 11.0 * jl),
                          (0.5 * dia * wm, 5.5 * dia * wm),
                          (spec.smoke_fresh, spec.smoke_old), r,
                          alpha01=(0.80, 0.08), fade_in=0.06, stretch=0.02)
        # BILLOW clumps along the flown path.
        self._path_m = getattr(self, "_path_m", 0.0) + dist
        self._next_clump = getattr(self, "_next_clump", 0.0)
        gap_scale = 1.8 / max(spec.smoke_per_m, 0.1)
        while self._path_m >= self._next_clump:
            t_along = 1.0 - (self._path_m - self._next_clump) / dist
            t_along = min(max(t_along, 0.0), 1.0)
            center = (self._last_smoke_pos + seg * t_along
                      + np.cross(seg_dir, r.standard_normal(3)) * 1.2)
            eddy = r.normal(0.0, 0.7, 3).astype(np.float64)
            for _ in range(int(r.integers(3, 6))):
                fx.smoke.emit(
                    1, center, 1.8,
                    wind + eddy + np.array([0.0, 0.2, 0.0]), 0.5,
                    (max(8.0, 42.0 * ls), max(12.0, 65.0 * ls)),
                    (1.6 * dia * wm, 15.0 * dia * wm),
                    (spec.smoke_fresh, spec.smoke_old), r,
                    alpha01=(0.55, 0.03), fade_in=0.14)
            self._next_clump += (r.uniform(3.5, 6.5) * gap_scale / taper
                                 if taper > 1e-3 else 1e9)
        # VEIL: the minutes-long pad-level hang.
        self._veil_carry = getattr(self, "_veil_carry", 0.0) \
            + dist * 0.14 * (spec.smoke_per_m / 1.8) * taper
        n_veil = int(self._veil_carry)
        self._veil_carry -= n_veil
        vp = max(12.0, 320.0 * ls * ls)
        for k in range(n_veil):
            p = self._last_smoke_pos + seg * ((k + 0.5) / max(n_veil, 1))
            fx.smoke.emit(1, p, 3.5,
                          wind + np.array([0.0, 0.18, 0.0]), 0.7,
                          (vp * 0.7, vp),
                          (2.2 * dia * wm, 15.0 * dia * wm),
                          (spec.smoke_old, spec.smoke_old), r,
                          alpha01=(0.20, 0.02), fade_in=0.20)
        self._last_smoke_pos = tail.copy()

    # ------------------------------------------------------ event effects

    def ignition_fx(self, fx, pos) -> None:
        """Light-off.  Hot: fire-in-the-hole — flame + smoke erupt in a
        DONUT around the emerging airframe at the tube mouth.  Cold:
        hard hypergolic flash in mid-air (research 2.5)."""
        spec = self.spec
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64)
        d_fb = spec.diameter_m * 2.6
        fx.fire.emit(3, p, 0.4, (0.0, 0.0, 0.0), 0.0, (0.10, 0.18),
                     (d_fb * 1.6, d_fb * 2.2),
                     (spec.flame_core, (1.0, 0.9, 0.6)), r)
        fx.fire.emit(int(26), p, d_fb * 0.30, (0.0, 3.0, 0.0), 6.0,
                     (0.22, 0.5), (d_fb * 0.5, d_fb * 1.3),
                     ((1.0, 0.85, 0.45), spec.flame_edge), r)
        if spec.launch_mode == "hot":
            # The annulus eruption: flame + smoke blasting UP out of the
            # gap between airframe and tube wall — round-3 audit read as
            # a sparkle; a tube full of M55 efflux is a GEYSER.
            idx = fx.fire.emit(64, p + np.array([0.0, 0.6, 0.0]), 1.2,
                               (0.0, 34.0, 0.0), 8.0, (0.35, 0.8),
                               (1.4, 4.2),
                               (spec.flame_core, spec.flame_edge), r,
                               stretch=0.02)
            ring_r = 1.35
            if len(idx):
                ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
                fx.fire.pos[idx, 0] += (np.sin(ang) * ring_r) \
                    .astype(np.float32)
                fx.fire.pos[idx, 2] += (np.cos(ang) * ring_r) \
                    .astype(np.float32)
            from game.cinematic_missiles import _wind
            fx.smoke.emit(80, p + np.array([0.0, 1.0, 0.0]), 2.2,
                          _wind(fx, float(p[1])) + np.array([0., 18., 0.]),
                          6.0, (8.0, 16.0), (3.0, 26.0),
                          (spec.smoke_fresh, spec.smoke_old), r,
                          alpha01=(0.85, 0.06), fade_in=0.05)
        else:
            # Reddish NTO tint on the ignition transient.
            fx.smoke.emit(18, p, 2.0, (0.0, 1.0, 0.0), 2.5, (2.0, 5.0),
                          (2.0, 9.0),
                          ((0.55, 0.36, 0.26), spec.smoke_old), r,
                          alpha01=(0.6, 0.05), fade_in=0.05)

    def smoke_ring_fx(self, fx, pos) -> None:
        """THE Minuteman smoke ring (research 1.4): pressurized silo air
        forced through the circular tube mouth rolls a vortex ring that
        climbs hundreds of feet and lingers as a halo."""
        spec = self.spec
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64) + np.array([0.0, 2.0, 0.0])
        n = 46
        idx = fx.smoke.emit(n, p, 0.5, (0.0, 10.5, 0.0), 0.8,
                            (22.0, 38.0), (2.6, 15.0),
                            (spec.smoke_fresh, spec.smoke_old), r,
                            alpha01=(0.62, 0.03), fade_in=0.10)
        if len(idx):
            ang = np.linspace(0.0, 2.0 * np.pi, len(idx), endpoint=False)
            ring_r = 2.6
            fx.smoke.pos[idx, 0] += (np.sin(ang) * ring_r).astype(np.float32)
            fx.smoke.pos[idx, 2] += (np.cos(ang) * ring_r).astype(np.float32)
            sp = fx.rng.uniform(3.0, 4.6, len(idx))
            fx.smoke.vel[idx, 0] += (np.sin(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 2] += (np.cos(ang) * sp).astype(np.float32)

    def eject_fx(self, fx, pos) -> None:
        """Cold mortar exit: the huge dark PAD-gas puff venting from the
        tube mouth as 208 t climbs out unlit (research 2.4/2.5-3)."""
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64)
        mouth = np.array([self._silo[0], self._silo[1] + 1.5,
                          self._silo[2]])
        from game.cinematic_missiles import _wind
        w = _wind(fx, float(mouth[1]))
        fx.smoke.emit(70, mouth, 3.0, w + np.array([0.0, 9.0, 0.0]), 4.0,
                      (16.0, 34.0), (3.0, 24.0),
                      ((0.42, 0.38, 0.34), (0.31, 0.30, 0.29)), r,
                      alpha01=(0.8, 0.05), fade_in=0.06)
        idx = fx.smoke.emit(50, mouth, 2.0, (0.0, 1.8, 0.0), 0.8,
                            (10.0, 22.0), (2.5, 16.0),
                            ((0.48, 0.44, 0.39), (0.36, 0.35, 0.33)), r,
                            alpha01=(0.7, 0.05), fade_in=0.05,
                            stretch=0.03)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            sp = r.uniform(14.0, 30.0, len(idx))
            fx.smoke.vel[idx, 0] = (np.sin(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 2] = (np.cos(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 1] = r.uniform(0.5, 2.5, len(idx)) \
                .astype(np.float32)
        # Thin dark wake clinging to the rising airframe.
        fx.smoke.emit(10, p, 1.2, (0.0, 6.0, 0.0), 2.0, (4.0, 8.0),
                      (1.5, 6.0), ((0.40, 0.37, 0.34), (0.32, 0.31, 0.30)),
                      r, alpha01=(0.5, 0.05), fade_in=0.05)

    def pallet_fx(self, fx, pos) -> None:
        """The spent pressure pallet kicked sideways off the tail just
        before light-off — a smoking slug (research 2.6-5)."""
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64)
        side = np.array([math.sin(1.1), 0.0, math.cos(1.1)])
        fx.fire.emit(5, p, 0.4, side * 16.0 - UP * 2.0, 4.0, (0.3, 0.7),
                     (0.5, 1.4), ((1.0, 0.75, 0.4), (1.0, 0.45, 0.12)), r)
        fx.smoke.emit(10, p, 0.6, side * 14.0 - UP * 1.0, 3.0,
                      (2.5, 5.0), (0.8, 4.0),
                      ((0.45, 0.42, 0.38), (0.35, 0.34, 0.32)), r,
                      alpha01=(0.6, 0.06), fade_in=0.03)

    def stage_fx(self, fx, pos) -> None:
        """Separation: a hanging puff + brief flash; the spent stage's
        tumble reads through the puff at long range."""
        spec = self.spec
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64)
        rel_alt = max(0.0, float(p[1]) - float(self._silo[1]))
        ls = 1.0 / (1.0 + (rel_alt / 2600.0) ** 1.6)
        fx.fire.emit(8, p, spec.diameter_m * 1.5, (0.0, 0.0, 0.0), 8.0,
                     (0.15, 0.4),
                     (spec.diameter_m * 1.2, spec.diameter_m * 3.0),
                     (spec.flame_core, spec.flame_edge), r)
        fx.smoke.emit(16, p, spec.diameter_m * 2.0, (0.0, 0.0, 0.0), 4.0,
                      (max(6.0, 30.0 * ls), max(10.0, 55.0 * ls)),
                      (spec.diameter_m * 2.0, spec.diameter_m * 14.0),
                      (spec.smoke_fresh, spec.smoke_old), r,
                      alpha01=(0.4, 0.02), fade_in=0.15)

    def impact_fx(self, fx, pos) -> None:
        """RV ground impact: dust sheet, flash, rising column, lingering
        skirt (conventional-scale placeholder — plan open question 1)."""
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64) + np.array([0.0, 1.0, 0.0])
        from game.cinematic_missiles import _wind
        w = _wind(fx, float(p[1]))
        fx.fire.emit(4, p, 1.0, (0.0, 0.0, 0.0), 0.0, (0.12, 0.22),
                     (16.0, 26.0), ((1.0, 0.97, 0.85), (1.0, 0.8, 0.4)), r)
        fx.fire.emit(48, p, 3.0, (0.0, 14.0, 0.0), 9.0, (0.3, 0.9),
                     (2.0, 7.0), ((1.0, 0.85, 0.5), (1.0, 0.45, 0.1)), r)
        idx = fx.smoke.emit(120, p, 3.0, (0.0, 1.5, 0.0), 0.8,
                            (3.0, 7.0), (3.0, 22.0),
                            ((0.52, 0.47, 0.40), (0.42, 0.39, 0.35)), r,
                            alpha01=(0.8, 0.06), fade_in=0.04,
                            stretch=0.035)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            sp = r.uniform(40.0, 70.0, len(idx))
            fx.smoke.vel[idx, 0] = (np.sin(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 2] = (np.cos(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 1] = r.uniform(1.0, 4.0, len(idx)) \
                .astype(np.float32)
        fx.smoke.emit(60, p + np.array([0.0, 4.0, 0.0]), 5.0,
                      w + np.array([0.0, 7.0, 0.0]), 3.0,
                      (20.0, 45.0), (6.0, 42.0),
                      ((0.50, 0.46, 0.41), (0.40, 0.39, 0.37)), r,
                      alpha01=(0.6, 0.04), fade_in=0.10)
        fx.smoke.emit(40, p, 9.0, w + np.array([0.0, 1.0, 0.0]), 1.2,
                      (35.0, 60.0), (14.0, 50.0),
                      ((0.55, 0.52, 0.48), (0.46, 0.45, 0.43)), r,
                      alpha01=(0.32, 0.02), fade_in=0.2)

    def pad_blast_fx(self, fx, pos) -> None:   # S-300 event names never
        pass                                   # fire for ICBMs; kept for

    def pad_roll_fx(self, fx, pos) -> None:    # duck-type safety.
        pass
