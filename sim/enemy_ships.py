"""Enemy ship entities for COMBAT mode (pure numpy, GL-free, SI units, +Y up).

Currently contains:

  Destroyer — Arleigh Burke-class surface combatant.

  Unlike the merchant ships in sim/ships.py a Destroyer does NOT follow a
  shipping lane. It loiters around a fixed anchor point on a racetrack orbit
  (two straight legs joined by 180-degree turns), giving it a natural sweeping
  radar coverage pattern while keeping it in a defined patrol area.

Navigation design
-----------------
The racetrack is defined by the anchor, a heading (the long-axis direction of
the two parallel legs), and the patrol_radius_m (half-length of each leg).
The four racetrack waypoints are computed once in __init__ and the Destroyer
cycles through them endlessly, using the same rate-limited rudder logic as
Ship (TURN_RATE rad/s). Because Destroyer subclasses Ship it inherits the full
damage ladder (ST_ALIVE, ST_BURNING, ST_SINKING, ST_GONE) and the hull OBB
unchanged; only the navigation section of update() is replaced.

Radar
-----
A SPY-1-class Radar is built in __init__ and its pos array is kept in sync with
the ship's pos array each update so horizon math always uses the current mast
position. The Radar object lives as ``self.radar`` for integration-layer access
(RadarNetwork, contact gating, ELINT detection).

Magazine state
--------------
sm2_ammo and ciws_ammo are simple integer counters; sm2_reload_timer counts
down between SM-2 launches (enforces the fire-control channel limit). Engagement
logic (target selection, guidance, warhead dispatch) is intentionally absent
here — it belongs in the combat integration layer where the full track picture
and all weapon defs are available.
"""

import math

import numpy as np

import sim.radar as _radar_mod
from sim.ships import (BURN_SPEED_FRAC, BURN_TIME, HULL_DRAFT,
                       LIST_MAX, LIST_RAMP_TIME, SHIP_TYPES, SINK_GONE_TIME,
                       SINK_RATE, TURN_RATE, ST_ALIVE, ST_BURNING,
                       ST_GONE, ST_SINKING, Ship)

# SPY-1 antenna height above the waterline: the mast top is
# ``height``=30 m, but the rotating planar array sits at 20 m.  This is
# the value passed to Radar so horizon math uses the correct sensor altitude.
_SPY1_ANTENNA_M = 20.0

# SPY-1 detection ranges (metres) by target size class.  Horizon limits
# lo-lo targets automatically — a 15 m sea-skimmer is invisible beyond
# ~30–40 km from a 20 m mast regardless of the 300 km nominal range.
_SPY1_RANGES = {
    "ship":    300_000.0,
    "fighter": 300_000.0,
    "missile": 300_000.0,
    "stealth":  30_000.0,    # drone detected at ~10% of normal range (spec §3)
}

# Default magazine loads
_SM2_AMMO_DEFAULT  = 24
_CIWS_AMMO_DEFAULT = 1500     # rounds; CIWS is a gun, not missiles
_SM2_RELOAD_S      = 3.0      # seconds between SM-2 launches (fire-control limit)
_SM6_AMMO_DEFAULT  = 6        # long-range SM-6 area-air rounds per destroyer
_SM6_RELOAD_S      = 6.0      # seconds between SM-6 launches (separate channel)
# Phase 3 land-attack magazine: 8 of the 90 Mk 41 cells loaded with TLAM —
# a typical mixed strike/air-defense loadout for a Burke on station (the
# rest of the magazine is the 24 SM-2s above plus unmodeled VLA/ESSM).
_TOMAHAWK_AMMO_DEFAULT = 8

# Racetrack geometry: the two legs run along the patrol heading ±patrol_radius
# from the anchor, and the turn waypoints are offset perpendicular by
# RACETRACK_HALF_WIDTH.  Kept small relative to patrol_radius so that the
# furthest waypoint (diagonal distance sqrt(r² + w²)) stays comfortably inside
# the patrol_radius + ship_length loiter bound checked by tests and the world
# builder.  At 400 m, diagonal excess over patrol_radius is only ~10 m, which
# is well below the ~155 m slack the ship_length provides.
_RACETRACK_HALF_WIDTH = 400.0


def _build_racetrack(anchor_xz, heading_deg, patrol_radius_m):
    """Return the four racetrack waypoints as a (4, 2) float64 array (XZ plane).

    The loop runs: far-left -> far-right -> near-right -> near-left -> repeat.
    «far» and «near» are along the patrol heading from the anchor; «left» and
    «right» are perpendicular (port / starboard of the long axis).
    """
    h_rad = math.radians(heading_deg)
    # Unit vectors along the long axis and across it (right = clockwise 90 deg)
    fwd_x, fwd_z =  math.sin(h_rad),  math.cos(h_rad)
    rgt_x, rgt_z =  math.cos(h_rad), -math.sin(h_rad)

    ax, az = float(anchor_xz[0]), float(anchor_xz[1])
    r = float(patrol_radius_m)
    w = _RACETRACK_HALF_WIDTH

    # far  (+r along heading), near (-r along heading)
    wps = np.array([
        [ax + fwd_x * r - rgt_x * w, az + fwd_z * r - rgt_z * w],  # far-left
        [ax + fwd_x * r + rgt_x * w, az + fwd_z * r + rgt_z * w],  # far-right
        [ax - fwd_x * r + rgt_x * w, az - fwd_z * r + rgt_z * w],  # near-right
        [ax - fwd_x * r - rgt_x * w, az - fwd_z * r - rgt_z * w],  # near-left
    ], dtype=np.float64)
    return wps


class Destroyer(Ship):
    """Arleigh Burke-class enemy destroyer: racetrack loiter, SPY-1, SM-2, CIWS.

    Parameters
    ----------
    ship_id : str
        Unique identifier; also used to name the SPY-1 radar (``{ship_id}_spy1``).
    anchor_xz : array-like of shape (2,)
        (X, Z) world-space centre of the patrol area in metres.
    heading_deg : float
        Long-axis compass heading of the racetrack (0 = north, clockwise).
    patrol_radius_m : float
        Half-length of each straight leg (metres); the ship stays within
        patrol_radius_m + ship_length / 2 of the anchor when healthy.
    sm2_ammo : int
        Initial SM-2 magazine count.
    ciws_ammo : int
        Initial CIWS ammunition (rounds).
    tomahawk_ammo : int
        Initial Tomahawk land-attack magazine (Phase 3; fired by
        sim/enemy_strikes.py, never by the ship itself).
    """

    # Not airborne — ContactBoard duck-typing; explicit False avoids getattr
    # surprises if someone checks the attribute directly.
    is_air = False

    def __init__(self, ship_id, anchor_xz, heading_deg=0.0,
                 patrol_radius_m=8_000.0,
                 sm2_ammo=_SM2_AMMO_DEFAULT,
                 ciws_ammo=_CIWS_AMMO_DEFAULT,
                 tomahawk_ammo=_TOMAHAWK_AMMO_DEFAULT):

        # Build a minimal one-segment «lane» so the Ship superclass can
        # initialise its lane-following state from it.  We place the ship at
        # the anchor and aim it along the patrol heading; the Destroyer will
        # immediately switch to its own racetrack logic in update().
        h_rad = math.radians(heading_deg)
        ax, az = float(anchor_xz[0]), float(anchor_xz[1])
        stub_lane = [
            (ax, az),
            (ax + math.sin(h_rad) * 100.0, az + math.cos(h_rad) * 100.0),
        ]
        # Start at the anchor (lane_t0=0.0) heading along the patrol heading.
        super().__init__(ship_id, "destroyer", stub_lane, lane_t0=0.0)

        self._anchor_xz = np.array([ax, az], dtype=np.float64)
        self._patrol_radius_m = float(patrol_radius_m)
        self._heading_deg = float(heading_deg)

        # Pre-compute the four racetrack waypoints; _rt_wp indexes into them.
        self._rt_wps = _build_racetrack(anchor_xz, heading_deg, patrol_radius_m)
        self._rt_wp = 0          # index of the next waypoint to steer towards

        # --- SPY-1 radar ---
        # The pos array is the same object as self.pos so updates propagate
        # automatically — we only need to copy the Y coordinate each tick
        # (the ship sinks; the antenna moves with it; see update()).
        self.radar = _radar_mod.Radar(
            radar_id=f"{ship_id}_spy1",
            pos=self.pos.copy(),     # own copy; kept in sync in update()
            antenna_m=_SPY1_ANTENNA_M,
            ranges=dict(_SPY1_RANGES),
        )

        # --- Magazine state ---
        self.sm2_ammo        = int(sm2_ammo)
        self.ciws_ammo       = int(ciws_ammo)
        self.tomahawk_ammo   = int(tomahawk_ammo)
        # sm2_reload_s is a class-level constant; the per-instance timer counts
        # down from it each time the integration layer fires a round.
        self.sm2_reload_s    = _SM2_RELOAD_S
        self.sm2_reload_timer = 0.0   # > 0 means the fire-control channel is busy
        # SM-6: separate long-range channel (240 km) — reaches the recon drone
        # and high Oniks the 150 km SM-2 cannot.
        self.sm6_ammo        = _SM6_AMMO_DEFAULT
        self.sm6_reload_s    = _SM6_RELOAD_S
        self.sm6_reload_timer = 0.0

    # -------------------------------------------------------------------------
    # Navigation helpers

    def _advance_racetrack(self, px, pz):
        """Advance the racetrack waypoint index when the ship is close enough
        or has overshot (same dual criterion as Ship._advance_waypoint)."""
        wx, wz = float(self._rt_wps[self._rt_wp, 0]), \
                 float(self._rt_wps[self._rt_wp, 1])
        dx, dz = wx - px, wz - pz
        dist = math.hypot(dx, dz)
        behind = (dx * math.sin(self.heading)
                  + dz * math.cos(self.heading)) < 0.0
        # Reuse the same radii constants from ships.py so the feel is identical.
        from sim.ships import WAYPOINT_RADIUS, WAYPOINT_BEHIND_RADIUS
        if dist < WAYPOINT_RADIUS or (behind and dist < WAYPOINT_BEHIND_RADIUS):
            self._rt_wp = (self._rt_wp + 1) % len(self._rt_wps)

    # -------------------------------------------------------------------------
    # Core update — only navigation is overridden; damage path is reproduced
    # faithfully from Ship.update() to avoid breaking the inherited states.

    def update(self, dt):
        """Advance one sim step: damage states first, then racetrack navigation.

        The damage handling is a direct transcription of Ship.update() so that
        ST_BURNING, ST_SINKING, and ST_GONE behave identically regardless of
        which navigation loop is active.  We cannot simply call ``super().update``
        because Ship.update() would also run the lane-following code, which we
        must replace.

        Radar sync is done at the very end (after all pos mutations) so that
        radar.pos always reflects the position at the close of this tick.
        """
        # --- SM-2 reload timer (fire-control channel) -----------------------
        if self.sm2_reload_timer > 0.0:
            self.sm2_reload_timer = max(0.0, self.sm2_reload_timer - dt)
        if self.sm6_reload_timer > 0.0:
            self.sm6_reload_timer = max(0.0, self.sm6_reload_timer - dt)

        # --- damage states (verbatim from Ship.update, early-returns removed
        #     so the radar sync at the bottom always runs) -------------------
        if self.state == ST_GONE:
            pass  # nothing moves; fall through to radar sync
        elif self.state == ST_SINKING:
            self.sink_elapsed += dt
            self.list_angle = LIST_MAX * min(
                1.0, self.sink_elapsed / LIST_RAMP_TIME)
            self.pos[1] -= SINK_RATE * dt
            if self.sink_elapsed >= SINK_GONE_TIME:
                self.state = ST_GONE
        else:
            # ST_ALIVE or ST_BURNING
            if self.state == ST_BURNING:
                self.burn_timer -= dt
                if self.burn_timer <= 0.0:
                    self.state = ST_SINKING
                    # No navigation this tick — fall through to radar sync.

            # Only navigate while alive or burning (not when burn just flipped
            # to sinking this tick, which is harmless to skip).
            if self.state in (ST_ALIVE, ST_BURNING):
                # --- racetrack navigation (replaces lane-following) ---------
                speed = self.speed * (
                    BURN_SPEED_FRAC if self.state == ST_BURNING else 1.0)
                px = float(self.pos[0])
                pz = float(self.pos[2])

                self._advance_racetrack(px, pz)
                wx = float(self._rt_wps[self._rt_wp, 0])
                wz = float(self._rt_wps[self._rt_wp, 1])

                bearing = math.atan2(wx - px, wz - pz)
                err = (bearing - self.heading + math.pi) % (2.0 * math.pi) - math.pi
                limit = TURN_RATE * dt
                self.heading += min(max(err, -limit), limit)
                self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi

                self.pos[0] = px + math.sin(self.heading) * speed * dt
                self.pos[2] = pz + math.cos(self.heading) * speed * dt

        # --- keep radar in sync after all pos mutations this tick -----------
        self.radar.pos[0] = self.pos[0]
        self.radar.pos[1] = self.pos[1]
        self.radar.pos[2] = self.pos[2]
