"""Task 20: tactical map transforms (plan tests, GL-free).

Covers the pure MapView world<->screen mapping, zoom-at-cursor invariance,
contact click-picking against a ContactBoard, and the waypoint append/clear
helpers. Task S4 adds the air picture: the platform pick filter
(air-only for the S-300, surface-only for the Bastion) and the air
diamond/altitude-tag symbol helpers. The GL texture/draw side of
game.tactical_map is never touched here (GL imports are deferred into
TacticalMap.__init__, LOCKED test convention).
"""

import numpy as np

from game.tactical_map import (MAX_WAYPOINTS, PICK_RADIUS_PX, ZOOM_MAX_MPP,
                               ZOOM_MIN_MPP, MapView, add_waypoint,
                               air_alt_text, clear_waypoints, contact_symbol,
                               pick_contact)
from sim.contacts import ContactBoard

W, H = 1600, 900


def view(center=(0.0, 255_000.0), mpp=400.0):
    return MapView(W, H, center, mpp)


def board(tracks):
    """ContactBoard with hand-set tracks (pos, vel, age); never refreshes."""
    b = ContactBoard((0.0, -180.0))
    for sid, (pos, vel, age) in tracks.items():
        b.tracks[sid] = dict(pos=np.asarray(pos, dtype=np.float64),
                             vel=np.asarray(vel, dtype=np.float64),
                             age=float(age), t_next=1e18)
    return b


# ------------------------------------------------------- world <-> screen

def test_world_screen_roundtrip_exact():
    v = view(center=(12_345.0, 200_000.0), mpp=250.0)
    for xz in [(0.0, 0.0), (-350_000.0, -50_000.0), (350_000.0, 560_000.0),
               (12_345.0, 200_000.0), (-87_654.3, 432_109.8)]:
        back = v.screen_to_world(v.world_to_screen(xz))
        assert abs(float(back[0]) - xz[0]) < 1e-6
        assert abs(float(back[1]) - xz[1]) < 1e-6


def test_screen_orientation_north_up_east_right():
    v = view()
    cx, cy = v.world_to_screen(v.center_xz)
    assert abs(cx - W / 2) < 1e-9 and abs(cy - H / 2) < 1e-9
    ex, ey = v.world_to_screen((v.center_xz[0] + 40_000.0, v.center_xz[1]))
    nx, ny = v.world_to_screen((v.center_xz[0], v.center_xz[1] + 40_000.0))
    assert ex > cx and abs(ey - cy) < 1e-9      # east -> right
    assert ny < cy and abs(nx - cx) < 1e-9      # north -> up
    assert abs((ex - cx) - 40_000.0 / v.meters_per_px) < 1e-9


# --------------------------------------------------------- zoom at cursor

def test_zoom_at_cursor_keeps_cursor_world_point_fixed():
    v = view(mpp=400.0)
    cursor = (1_234.0, 567.0)               # off-center on purpose
    anchor = v.screen_to_world(cursor)
    for factor in (0.8, 0.8, 1.25, 0.5, 2.0, 0.8, 1.6):
        v.zoom_at(cursor, factor)
        sx, sy = v.world_to_screen(anchor)
        assert abs(sx - cursor[0]) <= 0.5
        assert abs(sy - cursor[1]) <= 0.5


def test_zoom_clamps_to_plan_range():
    assert ZOOM_MIN_MPP == 12.0 and ZOOM_MAX_MPP == 800.0
    v = view(mpp=400.0)
    cursor = (300.0, 700.0)
    anchor = v.screen_to_world(cursor)
    for _ in range(40):
        v.zoom_at(cursor, 0.5)
    assert v.meters_per_px == ZOOM_MIN_MPP
    sx, sy = v.world_to_screen(anchor)       # invariance holds at the clamp
    assert abs(sx - cursor[0]) <= 0.5 and abs(sy - cursor[1]) <= 0.5
    for _ in range(40):
        v.zoom_at(cursor, 2.0)
    assert v.meters_per_px == ZOOM_MAX_MPP


# ------------------------------------------------------------ click pick

def test_click_pick_selects_nearest_contact_within_14px_else_none():
    v = view(center=(0.0, 200_000.0), mpp=400.0)
    a = (10_000.0, 0.0, 205_000.0)
    b = (10_000.0 + 12.0 * 400.0, 0.0, 205_000.0)   # 12 px east of a
    brd = board({"a": (a, (0.0, 0.0, 0.0), 0.0),
                 "b": (b, (0.0, 0.0, 0.0), 0.0)})
    pa = v.world_to_screen((a[0], a[2]))
    # 5 px east of a: inside 14 px of both, nearest is a
    assert pick_contact(v, brd, 0.0, (pa[0] + 5.0, pa[1])) == "a"
    # 8 px east of a -> 4 px west of b: nearest is b
    assert pick_contact(v, brd, 0.0, (pa[0] + 8.0, pa[1])) == "b"
    # 13.9 px below a (b is further): still picks a
    assert pick_contact(v, brd, 0.0, (pa[0], pa[1] + 13.9)) == "a"
    # 15 px below a, > 14 px from b too: None
    assert pick_contact(v, brd, 0.0, (pa[0], pa[1] + 15.0)) is None
    # far empty ocean: None
    assert pick_contact(v, brd, 0.0, (40.0, 40.0)) is None
    assert PICK_RADIUS_PX == 14.0


def test_click_pick_uses_dead_reckoned_position():
    v = view(center=(0.0, 200_000.0), mpp=400.0)
    pos = (-20_000.0, 0.0, 190_000.0)
    vel = (80.0, 0.0, 0.0)                  # 100 s stale: drifted 8 km east
    brd = board({"drift": (pos, vel, 100.0)})
    est_px = v.world_to_screen((pos[0] + 8_000.0, pos[2]))
    raw_px = v.world_to_screen((pos[0], pos[2]))
    assert pick_contact(v, brd, 123.0, est_px) == "drift"
    assert pick_contact(v, brd, 123.0, raw_px) is None   # 20 px off the estimate


def test_pick_contact_platform_air_filter():
    """Task S4: LMB picks air contacts when the S-300 is active (air_only
    True), ships when the Bastion is (air_only False); default unfiltered."""
    v = view(center=(0.0, 200_000.0), mpp=400.0)
    ship_pos = (10_000.0, 0.0, 205_000.0)
    air_pos = (10_000.0 + 5.0 * 400.0, 6_500.0, 205_000.0)   # 5 px east
    brd = board({"tanker_01": (ship_pos, (0.0, 0.0, 0.0), 0.0),
                 "air_patrol_00": (air_pos, (0.0, 0.0, 0.0), 0.0)})
    brd.tracks["air_patrol_00"]["is_air"] = True
    spx = v.world_to_screen((ship_pos[0], ship_pos[2]))
    apx = v.world_to_screen((air_pos[0], air_pos[2]))
    # unfiltered: nearest of any kind (back-compat with the v1 behavior)
    assert pick_contact(v, brd, 0.0, spx) == "tanker_01"
    # s300 active: clicking right on the ship still picks the diamond 5 px out
    assert pick_contact(v, brd, 0.0, spx, air_only=True) == "air_patrol_00"
    # bastion active: clicking right on the diamond still picks the ship
    assert pick_contact(v, brd, 0.0, apx, air_only=False) == "tanker_01"
    # air-only with no air contact within 14 px -> None (not the nearby ship)
    far = (spx[0], spx[1] + 300.0)
    assert pick_contact(v, brd, 0.0, far, air_only=True) is None
    assert pick_contact(v, brd, 0.0, (apx[0], apx[1] + 300.0),
                        air_only=False) is None


def test_air_symbol_selection_and_altitude_text():
    """Task S4: air tracks draw as diamonds with an altitude tag; ships keep
    the course triangle (their tracks may predate the is_air key)."""
    assert contact_symbol(dict(is_air=True)) == "air"
    assert contact_symbol(dict(is_air=False)) == "surface"
    assert contact_symbol(dict()) == "surface"
    assert air_alt_text(6_500.0) == "6.5k"
    assert air_alt_text(4_000.0) == "4.0k"
    assert air_alt_text(12_340.0) == "12.3k"


# -------------------------------------------------- waypoint append/clear

def test_waypoint_append_and_clear_logic():
    wps = []
    assert add_waypoint(wps, (1_000.0, 2_000.0)) is True
    assert add_waypoint(wps, np.array([3_000.0, 4_000.0])) is True
    assert wps == [(1_000.0, 2_000.0), (3_000.0, 4_000.0)]
    assert all(isinstance(c, float) for wp in wps for c in wp)
    while len(wps) < MAX_WAYPOINTS:
        assert add_waypoint(wps, (5.0, 6.0)) is True
    assert add_waypoint(wps, (7.0, 8.0)) is False     # full: append refused
    assert len(wps) == MAX_WAYPOINTS
    clear_waypoints(wps)
    assert wps == []
    assert add_waypoint(wps, (9.0, 10.0)) is True     # usable again after clear


# -------------------------------------------------- plain-coordinate aim

def test_ground_aim_point_targets_the_local_surface():
    """Task 23 spec acceptance: an LMB click on an elevated land site must
    aim the terminal dive at the ground there, not at y=0 under it; over
    water the aim point stays at sea level."""
    from game.tactical_map import ground_aim_point
    from world.generation import SITES, terrain_height_scalar

    hx, hz = SITES[2]["pos"]                       # HARBOR KILO, on land
    p = ground_aim_point((hx, hz))
    assert p.dtype == np.float64 and p.shape == (3,)
    assert p[1] == terrain_height_scalar(float(hx), float(hz)) > 0.0
    assert (p[0], p[2]) == (hx, hz)
    sea = ground_aim_point((0.0, 200_000.0))       # mid-ocean click
    assert sea[1] == 0.0
