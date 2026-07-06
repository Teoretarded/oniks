"""Damage-model calibration matrix (measure-don't-guess, F2-P4).

usage: python -m tools.probe_damage_matrix

Fires each weapon class into each hull at three aim heights (waterline /
deck / superstructure) under the SUBSYSTEM model and prints, per cell:
KE (J), penetrated?, breach m^2, modules killed, fire peak, outcome
(SURVIVES-CRIPPLED / SINKS-FLOOD / SINKS-COOKOFF / SINKS-GUTTED) and the
time to loss.  Numbers go into
docs/research/damage_model_calibration (run log) — the two-sided test
bands in tests/test_damage_model.py cite this table.

Headless, GL-free, deterministic (no RNG anywhere in the model).
"""

from __future__ import annotations

import numpy as np

from sim.damage import apply_missile_hits
from sim.damage_model import step_ships
from sim.ships import ST_SINKING, Ship
from sim.enemy_ships import Destroyer

DT = 1.0 / 120.0
RUN_S = 1200.0            # 20 min of DoT per shot

# weapon-class stand-ins: (label, live mass kg, terminal speed m/s,
#                          warhead kg, nose hardness)
WEAPONS = [
    ("oniks",   2500.0,  680.0, 250.0, 1.0),
    ("zircon",  3200.0, 1500.0, 300.0, 1.0),
    ("kalibr",  1500.0,  240.0, 450.0, 1.0),
    ("kh31p",    600.0,  700.0,  87.0, 0.2),
    ("swarm",     45.0,  250.0,   8.0, 1.0),
]
# aim heights vs waterline (m): below-WL / main deck / superstructure
AIMS = [("waterline", -1.5), ("deck", 6.0), ("topside", 18.0)]
# hull, z-fraction aimed at (mid-MER vs mid-VLS tells the story)
HULLS = [("destroyer_mer", 0.36), ("destroyer_vls", 0.65)]


class _Round:
    class _W:
        def __init__(self, wh, hd):
            self.warhead_mass, self.nose_hardness = wh, hd
            self.weapon_id = "probe"

    def __init__(self, prev_pos, pos, vel, mass, wh, hd):
        self.prev_pos = np.asarray(prev_pos, dtype=np.float64)
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.asarray(vel, dtype=np.float64)
        self.alive, self.is_hostile = True, False
        self.impact_pos, self.phase = None, 0
        self.mass, self.weapon = float(mass), self._W(wh, hd)


def _shot(zf, y_wl, mass, speed, wh, hd):
    ship = Destroyer("probe", (0.0, 200_000.0), heading_deg=0.0)
    zc = float(ship.pos[2]) - ship.length * 0.5 + zf * ship.length
    x0 = float(ship.pos[0]) - 60.0
    r = _Round((x0, y_wl, zc), (x0 + speed * DT * 30.0, y_wl, zc),
               (speed, 0.0, 0.0), mass, wh, hd)
    ev = []
    apply_missile_hits([r], [ship], ev, damage_model="subsystem")
    st = getattr(ship, "_dmg", None)
    ke = getattr(r, "impact_ke", 0.0)
    fire_peak, t_loss, cause = 0.0, None, "SURVIVES"
    if any(k == "magazine_detonation" for k, _ in ev):
        cause, t_loss = "SINKS-COOKOFF", 0.0
    t = 0.0
    while t < RUN_S and ship.state != ST_SINKING:
        step_ships([ship], DT, ev)
        if st:
            fire_peak = max(fire_peak, st.fire)
        t += DT
    if ship.state == ST_SINKING and t_loss is None:
        t_loss = t
        if any(k == "magazine_detonation" for k, _ in ev):
            cause = "SINKS-COOKOFF"
        elif st and st.flooded_count() >= st.sink_flooded:
            cause = "SINKS-FLOOD"
        else:
            cause = "SINKS-GUTTED"
    mods = sorted(st.dead_modules) if st else []
    breach = sum(st.breach) if st else 0.0
    flooded = st.flooded_count() if st else 0
    return dict(ke=ke, breach=breach, mods=mods, fire=fire_peak,
                flooded=flooded, cause=cause, t_loss=t_loss)


def main() -> None:
    print(f"{'hull':<15}{'weapon':<9}{'aim':<11}{'KE MJ':>8}{'breach':>7}"
          f"{'flood':>6}{'firepk':>7}  outcome (t)          modules")
    for hull, zf in HULLS:
        for label, mass, speed, wh, hd in WEAPONS:
            for aim, y in AIMS:
                r = _shot(zf, y, mass, speed, wh, hd)
                t = "" if r["t_loss"] is None else f" @{r['t_loss']:.0f}s"
                print(f"{hull:<15}{label:<9}{aim:<11}"
                      f"{r['ke'] / 1e6:>8.1f}{r['breach']:>7.1f}"
                      f"{r['flooded']:>6d}{r['fire']:>7.2f}  "
                      f"{r['cause'] + t:<20}  {','.join(r['mods'])}")


if __name__ == "__main__":
    main()
