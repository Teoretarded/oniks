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
    shake_amp=1.4, cutoff_event=False)

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

    def __init__(self, spec: IcbmSpec, silo, target, ground_h):
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

    # ------------------------------------------------- fx hooks (P3 fills)

    def emit(self, fx, dt: float) -> None:
        pass

    def ignition_fx(self, fx, pos) -> None:
        pass

    def pad_blast_fx(self, fx, pos) -> None:
        pass

    def pad_roll_fx(self, fx, pos) -> None:
        pass
