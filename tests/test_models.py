"""Model builder tests: every builder returns a finite mesh with unit normals;
key real-world dimensions are enforced (GL-free; builders use engine.meshdata)."""

import numpy as np

from models.aircraft_model import build_fast_aircraft, build_patrol_aircraft
from models.bastion import build_bastion_tel
from models.common import PALETTE
from models.oniks import build_oniks, build_oniks_booster
from models.s300 import build_s300_missile, build_s300_tel
from models.ships_models import build_cargo, build_tanker, build_warship
from models.structures import build_fuel_depot, build_harbor, build_radar_station


def _check(md):
    assert md.vertices.dtype == np.float32 and md.indices.dtype == np.uint32
    assert md.indices.max() < len(md.vertices)
    assert np.isfinite(md.vertices).all()
    n = md.vertices[:, 3:6]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-3)


def test_all_builders_finite_unit_normals():
    for md in (build_oniks(), build_oniks_booster(),
               build_bastion_tel(elevation_deg=0.0),
               build_bastion_tel(elevation_deg=88.0),
               build_s300_tel(elevation_deg=0.0),
               build_s300_tel(elevation_deg=90.0),
               build_s300_missile(),
               build_patrol_aircraft(), build_fast_aircraft(),
               build_cargo(), build_tanker(), build_warship(),
               build_radar_station(), build_fuel_depot(), build_harbor()):
        _check(md)


def test_oniks_dimensions():
    md = build_oniks()
    z = md.vertices[:, 2]
    # 8.9 m long within 1 cm, mid-body origin (nose at +4.45)
    assert abs((z.max() - z.min()) - 8.9) <= 0.01
    assert abs(z.max() - 4.45) <= 0.01
    # body diameter 0.67 m: body-colored lathe stays within r 0.34
    body = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["missile_body"],
                             atol=1e-4), axis=1)
    assert body.any()
    r = np.linalg.norm(md.vertices[body, 0:2], axis=1)
    assert r.max() <= 0.34


def test_booster_dimensions():
    md = build_oniks_booster()
    r = np.linalg.norm(md.vertices[:, 0:2], axis=1)
    assert abs(r.max() - 0.30) <= 0.01


def test_tel_fits_box_when_elevated():
    md = build_bastion_tel(elevation_deg=88.0)
    p = md.vertices[:, 0:3]
    ext = p.max(axis=0) - p.min(axis=0)
    assert ext[0] <= 4.0    # width (east-west)
    assert ext[1] <= 10.0   # height with canisters raised
    assert ext[2] <= 13.0   # length (north-south)
    assert p[:, 1].min() >= -0.01  # nothing below the ground plane


def test_tel_elevation_raises_canisters():
    stowed = build_bastion_tel(elevation_deg=0.0)
    raised = build_bastion_tel(elevation_deg=88.0)
    assert raised.vertices[:, 1].max() > stowed.vertices[:, 1].max() + 4.0


def test_ship_dimensions():
    # (builder, length over all, beam) — real-scale, plan-locked
    for build, length, beam in ((build_cargo, 180.0, 28.0),
                                (build_tanker, 240.0, 40.0),
                                (build_warship, 150.0, 19.0)):
        md = build()
        p = md.vertices[:, 0:3]
        assert abs((p[:, 2].max() - p[:, 2].min()) - length) <= 1.0, build.__name__
        assert abs((p[:, 0].max() - p[:, 0].min()) - beam) <= 1.0, build.__name__
        # origin at the waterline center: hull straddles z = 0 evenly
        assert abs(p[:, 2].max() + p[:, 2].min()) <= 2.0, build.__name__
        # nothing deeper than 2 m below the waterline
        assert p[:, 1].min() >= -2.001, build.__name__


def test_structures_above_ground():
    for build in (build_radar_station, build_fuel_depot, build_harbor):
        md = build()
        assert md.vertices[:, 1].min() >= -2.001, build.__name__


def test_radar_station_radome_on_top():
    md = build_radar_station()
    y = md.vertices[:, 1]
    top = md.vertices[y >= y.max() - 0.5]
    assert np.all(np.isclose(top[:, 6:9], PALETTE["radar_white"], atol=1e-4))


def test_fuel_depot_tank_height():
    md = build_fuel_depot()
    white = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["tank_white"],
                              atol=1e-4), axis=1)
    assert white.any()
    y = md.vertices[white, 1]
    # 12 m cylinder walls topped by domes (dome adds a few meters, not a tower)
    assert 12.0 <= y.max() <= 16.0


# --- Task S3: S-300 expansion models -----------------------------------------


def test_s300_palette_additions():
    # locked by the expansion plan
    assert PALETTE["s300_green"] == (0.30, 0.34, 0.26)
    assert PALETTE["tube_grey"] == (0.42, 0.44, 0.42)
    assert PALETTE["aircraft_grey"] == (0.58, 0.62, 0.68)
    assert PALETTE["aircraft_dark"] == (0.30, 0.33, 0.38)


def test_s300_missile_dimensions():
    md = build_s300_missile()
    z = md.vertices[:, 2]
    # 7.5 m long within 2 cm, mid-body origin (nose at +3.75)
    assert abs((z.max() - z.min()) - 7.5) <= 0.02
    assert abs(z.max() - 3.75) <= 0.02
    # body diameter 0.515 m: body-colored lathe stays within r 0.26
    body = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["missile_body"],
                             atol=1e-4), axis=1)
    assert body.any()
    r = np.linalg.norm(md.vertices[body, 0:2], axis=1)
    assert r.max() <= 0.26
    # fins present and clipped: fin-colored verts stay inside r 0.80
    fins = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["fin"],
                             atol=1e-4), axis=1)
    assert fins.any()
    rf = np.linalg.norm(md.vertices[fins, 0:2], axis=1)
    assert 0.5 <= rf.max() <= 0.80


def test_s300_tel_fits_box_when_erect():
    md = build_s300_tel(elevation_deg=90.0)
    p = md.vertices[:, 0:3]
    ext = p.max(axis=0) - p.min(axis=0)
    assert ext[0] <= 4.0           # width (east-west)
    assert 8.0 <= ext[1] <= 10.0   # vertical 8.2 m tubes raised
    assert ext[2] <= 13.8          # ~13 m chassis (+ tube overhang)
    assert p[:, 1].min() >= -0.01  # nothing below the ground plane


def test_s300_tel_erection_raises_tubes():
    stowed = build_s300_tel(elevation_deg=0.0)
    raised = build_s300_tel(elevation_deg=90.0)
    assert stowed.vertices[:, 1].max() <= 4.2     # travel height
    assert raised.vertices[:, 1].max() > stowed.vertices[:, 1].max() + 4.0


def test_s300_tel_four_tube_block():
    md = build_s300_tel(elevation_deg=90.0)
    tube = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["tube_grey"],
                             atol=1e-4), axis=1)
    up = md.vertices[tube & (md.vertices[:, 1] > 5.0)]
    assert len(up)                  # raised tube walls exist
    # 2 x 2 block: tubes on both sides of x = 0 and at two z stations
    assert (up[:, 0] > 0.3).any() and (up[:, 0] < -0.3).any()
    assert (up[:, 2].max() - up[:, 2].min()) >= 2.2


def test_aircraft_dimensions():
    # (builder, length, wingspan) per the locked numbers, within 0.5 m
    for build, length, span in ((build_patrol_aircraft, 30.0, 35.0),
                                (build_fast_aircraft, 20.0, 14.0)):
        md = build()
        p = md.vertices[:, 0:3]
        assert abs((p[:, 2].max() - p[:, 2].min()) - length) <= 0.5, build.__name__
        assert abs((p[:, 0].max() - p[:, 0].min()) - span) <= 0.5, build.__name__
        # origin near the center of mass: fuselage straddles z = 0
        assert abs(p[:, 2].max() + p[:, 2].min()) <= 2.0, build.__name__
        # wings symmetric about the fuselage
        assert abs(p[:, 0].max() + p[:, 0].min()) <= 0.1, build.__name__


def test_patrol_aircraft_has_nacelles():
    md = build_patrol_aircraft()
    dark = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["aircraft_dark"],
                             atol=1e-4), axis=1)
    nac = md.vertices[dark & (np.abs(md.vertices[:, 0]) > 3.0)]
    assert len(nac)                 # underwing pods clear of the fuselage
    assert (nac[:, 0] > 3.0).any() and (nac[:, 0] < -3.0).any()
    assert nac[:, 1].max() <= 0.0   # slung BELOW the wing plane
