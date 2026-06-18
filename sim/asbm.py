"""AsbmMissile: quasi-ballistic top-attack anti-ship ballistic missile
(M4-A "Bastion-K"), a thin subclass of sim.sam.SamMissile.

The airframe REUSES the SamMissile machine verbatim for the parts that make a
lofted top-attack trajectory emerge from physics: the cold catapult eject, the
long solid boost, the high midcourse loft (energy management high in thin air),
the post-burnout coast, the terminal proportional-navigation core and the
proximity fuse.  The ONLY override is the terminal seeker: instead of the
SamMissile's air-target PN onto its launch target, the MaRV terminal phase
ACQUIRES the nearest alive SHIP inside a seeker cone (ported from
sim.missile.Missile._acquire_lock) and homes onto its TRUE position — the
anti-ship terminal that turns the ballistic dive onto a maneuvering hull.

Fog / no-cheat (project law): BOOST and MIDCOURSE fly on the dead-reckoned
player ContactBoard estimate (``contact_estimate_fn``, identical to every
SamMissile) — the round is launched on the STALE ship picture.  Only the
terminal MaRV seeker sees truth (it locks a real ship and the proximity fuse
checks the true hull), exactly like every other round's terminal/fuse.  A
shot launched on a frozen, stale estimate therefore MISSES a hull that moved
away — the miss EMERGES from guiding on a wandering/stale point, never a roll.

Determinism: reuses the SamMissile seeded streams unchanged; same seed ->
identical trajectory.  GL-free, pure numpy/math.
"""

import math

import numpy as np

from sim.sam import SPH_TERMINAL, SamMissile


class _FrozenGhost:
    """A dead aim point at a fixed world position — the round's committed target
    when the MaRV uncages on an EMPTY cone (a stale picture left the real ship
    outside the basket).  The inherited SamMissile terminal PN + proximity fuse
    read ``pos``/``velocity()``; flying this ghost carries the round into empty
    sea at the stale estimate, which is the honest stale-picture miss (the real
    hull is never killed because the fuse checks THIS dead point, not truth).
    ``kill`` is a harmless no-op so the fuse's duck-typed kill call is safe."""

    is_air = False
    alive = True

    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64).copy()

    def velocity(self):
        return np.zeros(3)

    def kill(self):
        pass            # the ghost is empty sea — nothing to kill


class AsbmMissile(SamMissile):
    """SamMissile with a terminal nearest-ship-in-cone MaRV seeker.

    Constructor signature mirrors SamMissile.  ``target`` at launch is the
    ship the shot is aimed at (a contact-estimate closure drives boost/
    midcourse); the terminal seeker uncages once at handover and acquires the
    nearest alive ship inside its GROUND FOOTPRINT, committing onto truth for
    the dive + fuse (or onto a frozen ghost on an empty footprint -> miss).

    seeker_footprint_m / seeker_range default to the class constants below and
    are read off the SamDef when present (so a future def can tune them) — the
    SamDef does not carry seeker fields today, so the class-level fallbacks
    define the basket.
    """

    # MaRV terminal seeker GROUND FOOTPRINT radius.  A ballistic MaRV uncages
    # its seeker at reentry and searches a finite patch of sea directly under
    # the descending vehicle.  The lock gate is the GROUND offset (horizontal
    # distance) from the missile to a hull — NOT an off-velocity cone, because
    # the steep dive makes the velocity vector a poor seeker reference (the hull
    # sits steeply BELOW the shallow midcourse-capped velocity).
    #
    # 4000 m is the MEASURED discriminator (tools/probe_asbm_flyoff.py-style
    # ground-offset sweep at terminal handover, where the steep arc hands over
    # ~3 km downrange-SHORT of the aim point — so the footprint must clear ~3.2
    # km to lock a correctly-aimed hull):
    #     picture            ground offset to true hull at uncage
    #     STATIC / aimed-true       ~2.0-3.2 km   -> INSIDE  -> acquire & kill
    #     FRESH/live track          ~0.9 km       -> INSIDE  -> acquire & kill
    #     STALE @ 18 m/s (35 kn)    ~6.1 km       -> OUTSIDE -> miss
    #     STALE @ 30 m/s            ~9.3 km       -> OUTSIDE -> miss
    # A fresh/aimed picture lands the round over the hull (inside the footprint);
    # a stale picture leaves the round over the OLD position, the hull having
    # steamed kilometres clear of the footprint — the seeker finds empty sea and
    # the round dives into the stale point (the honest physics-not-dice stale
    # miss).
    SEEKER_FOOTPRINT_M = 4000.0
    SEEKER_RANGE_M = 60_000.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # MaRV lock state.  The seeker UNCAGES ONCE, at terminal handover: it
        # locks the nearest alive ship inside the ground footprint at that
        # instant and stays locked (committed terminal, mirroring
        # Missile._acquire_lock's "once locked, stays locked").  If the footprint
        # is empty at uncage the round commits to the frozen midcourse estimate
        # for the rest of the dive — a single ballistic seeker-uncage event, NOT
        # a continuous re-search (so a stale picture that walked the hull out of
        # the footprint is an honest miss, never silently recovered).
        self._marv_uncaged = False
        sdef = self.weapon
        self._seeker_footprint = float(
            getattr(sdef, "seeker_footprint_m", self.SEEKER_FOOTPRINT_M))
        self._seeker_range = float(
            getattr(sdef, "seeker_range", self.SEEKER_RANGE_M))

    def _acquire_ship_lock(self, world):
        """MaRV seeker uncage: pick the nearest alive SHIP whose GROUND offset
        (horizontal distance) from the missile is inside the seeker footprint
        AND whose slant range is inside the seeker range, and commit
        ``self.target`` onto it (so the inherited terminal PN + the proximity
        fuse both home on the real hull).

        If NO ship is in the footprint at uncage, the round commits to a
        _FrozenGhost at the last contact estimate (the stale midcourse picture)
        — it then dives into empty sea there.  This is the honest stale miss:
        the round cannot home on a hull the seeker never found, and the fuse
        checks the dead ghost point, never the true (moved-away) hull."""
        best, best_g = None, self._seeker_footprint
        px, py, pz = self.pos.tolist()
        for ship in getattr(world, "ships", ()):
            if not getattr(ship, "alive", True):
                continue
            sp = ship.pos
            rx = float(sp[0]) - px
            ry = float(sp[1]) - py
            rz = float(sp[2]) - pz
            slant = math.sqrt(rx * rx + ry * ry + rz * rz)
            if slant >= self._seeker_range:
                continue
            ground = math.hypot(rx, rz)
            if ground >= best_g:
                continue
            best, best_g = ship, ground
        if best is not None:
            self.target = best          # commit: PN + fuse now read this hull
        else:
            # Empty footprint: commit to the stale picture, dive into empty sea.
            # ``_lock_pos`` was seeded at the MIDCOURSE->TERMINAL handover from
            # the (then-current) contact estimate — the STALE midcourse point,
            # not truth — so the ghost sits where the dead-reckoned picture said
            # the ship was.  Falls back to the current truth bearing only if the
            # handover never seeded it (defensive; it always does).
            if self._lock_pos is not None:
                self.target = _FrozenGhost(self._lock_pos)
            else:
                tx, ty, tz, _, _, _ = self._target_state()
                self.target = _FrozenGhost((tx, ty, tz))

    def _fuse_check(self):
        """The inherited proximity fuse, but a _FrozenGhost detonation is NOT a
        target kill: when the round commits to a ghost (an empty-sea stale
        point) and reaches it, the SamMissile fuse would set killed_target /
        call kill — neither should count, the hull is kilometres away.  We let
        the base fuse run (so the round still DIES at the ghost point, ending
        the flight) then scrub the false kill flag for a ghost target."""
        hit = super()._fuse_check()
        if hit and isinstance(self.target, _FrozenGhost):
            self.killed_target = False     # empty sea: no hull was killed
        return hit

    def update(self, dt, world):
        """SamMissile.update, with the MaRV seeker uncaged ONCE the moment the
        round enters terminal.  The single-uncage acquisition runs BEFORE the
        inherited terminal PN/fuse read ``self.target`` — so a hull caught in
        the footprint is committed for both the dive and the proximity fuse.  If
        the footprint is empty at uncage (a badly stale picture left the ship
        outside the basket), the round flies the frozen midcourse estimate to
        the sea: an honest stale-picture miss, not a re-search that recovers it."""
        if (self.alive and self.phase >= SPH_TERMINAL
                and not self._marv_uncaged):
            self._marv_uncaged = True
            self._acquire_ship_lock(world)
        super().update(dt, world)
