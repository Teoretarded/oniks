"""Model builder tests: every builder returns a finite mesh with unit normals;
key real-world dimensions are enforced (GL-free; builders use engine.meshdata)."""

import numpy as np

import models.oniks as oniks_model
from models.aircraft_model import build_fast_aircraft, build_patrol_aircraft
from models.bastion import build_bastion_tel
from models.common import PALETTE
from models.missiles import (build_40n6, build_48n6, build_57e6,
                             build_aim9x, build_harm, build_jassm,
                             build_sm2, build_sm6, build_tomahawk,
                             build_zircon)
from models.oniks import build_oniks, build_oniks_nose_cap
from models.s300 import build_s300_missile, build_s300_tel
from models.ships_models import build_cargo, build_tanker, build_warship
from models.structures import build_fuel_depot, build_harbor, build_radar_station


def _check(md):
    assert md.vertices.dtype == np.float32 and md.indices.dtype == np.uint32
    assert md.indices.max() < len(md.vertices)
    assert np.isfinite(md.vertices).all()
    n = md.vertices[:, 3:6]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-3)


def _color_mask(md, key):
    return np.all(np.isclose(md.vertices[:, 6:9], PALETTE[key], atol=1e-4),
                  axis=1)


def test_all_builders_finite_unit_normals():
    for md in (build_oniks(),
               build_oniks(nose_cap=True),
               build_oniks(nose_cap=True, wings_folded=True),
               build_oniks_nose_cap(),
               build_bastion_tel(elevation_deg=0.0),
               build_bastion_tel(elevation_deg=88.0),
               build_s300_tel(elevation_deg=0.0),
               build_s300_tel(elevation_deg=90.0),
               build_s300_missile(),
               build_48n6(), build_40n6(), build_sm2(), build_57e6(),
               build_tomahawk(), build_jassm(), build_harm(), build_aim9x(),
               build_zircon(), build_sm6(),
               build_patrol_aircraft(), build_fast_aircraft(),
               build_cargo(), build_tanker(), build_warship(),
               build_radar_station(), build_fuel_depot(), build_harbor()):
        _check(md)


# --- Task OM2: Oniks v2 reference dimensions ----------------------------------


def test_oniks_dimensions():
    md = build_oniks()
    z = md.vertices[:, 2]
    # bare round 8.6 m within 2 cm, mid-body origin (cone tip at +4.30)
    assert abs((z.max() - z.min()) - 8.6) <= 0.02
    assert abs(z.max() - 4.30) <= 0.02
    # 8.9 m including the nose cap (the reference's TPK-round figure)
    zc = build_oniks(nose_cap=True).vertices[:, 2]
    assert abs((zc.max() - zc.min()) - 8.9) <= 0.02
    # body diameter 0.67 m: body-colored lathe stays within r 0.34
    body = _color_mask(md, "oniks_body")
    assert body.any()
    r = np.linalg.norm(md.vertices[body, 0:2], axis=1)
    assert r.max() <= 0.34


def test_oniks_intake_annulus():
    """Signature 1: sharp cone protruding ~0.45 m ahead of the lip out of a
    deep-black annulus recessed >= 0.4 m."""
    md = build_oniks()
    z = md.vertices[:, 2]
    blk = _color_mask(md, "intake_black")
    assert blk.any()
    duct_z = md.vertices[blk, 2]
    assert duct_z.max() - duct_z.min() >= 0.40       # genuinely recessed duct
    assert abs((z.max() - duct_z.max()) - 0.45) <= 0.03   # cone protrusion
    # knife-edge lip at ~70-75% of body diameter (lip ring outer r ~0.245)
    lip = md.vertices[(md.vertices[:, 2] >= duct_z.max() - 0.01)
                      & ~blk & (np.linalg.norm(md.vertices[:, 0:2],
                                               axis=1) > 0.05)]
    r_lip = np.linalg.norm(lip[:, 0:2], axis=1)
    assert 0.23 <= r_lip.max() <= 0.26


def test_oniks_wings():
    """Signatures 3/4/9: huge-root clipped-delta wings on the rear half with a
    1.7 m deployed span, small in-line tail rudders, and a folded state lying
    flat against the body."""
    md = build_oniks()
    wing = _color_mask(md, "oniks_wing")
    assert wing.any()
    r = np.linalg.norm(md.vertices[wing, 0:2], axis=1)
    assert abs(r.max() - 0.85) <= 0.02               # deployed span 1.70 m
    # the wide wing tips live on the rear half of the body
    tips = md.vertices[wing & (np.linalg.norm(md.vertices[:, 0:2],
                                              axis=1) >= 0.84)]
    assert tips[:, 2].max() <= -1.0 and tips[:, 2].min() >= -2.9
    # small in-line rudders at the extreme tail, span well under the wings'
    rud = md.vertices[wing & (md.vertices[:, 2] < -3.5)]
    assert len(rud)
    assert np.linalg.norm(rud[:, 0:2], axis=1).max() <= 0.66
    # folded: every surface hugs the body (in-tube look)
    folded = build_oniks(wings_folded=True)
    fw = _color_mask(folded, "oniks_wing")
    rf = np.linalg.norm(folded.vertices[fw, 0:2], axis=1)
    assert rf.max() <= 0.55


def test_oniks_nose_cap_part():
    """The jettisoned SUO cap: 1.35 m cone, base at its local origin."""
    md = build_oniks_nose_cap()
    z = md.vertices[:, 2]
    assert abs(z.min()) <= 0.01
    assert abs((z.max() - z.min()) - 1.35) <= 0.02
    r = np.linalg.norm(md.vertices[:, 0:2], axis=1)
    assert r.max() <= 0.36


def test_oniks_booster_retired():
    """Task OM2: no external booster model — the real booster hides inside
    the ramjet duct; separation is a slug out the nozzle (game/sandbox.py)."""
    assert not hasattr(oniks_model, "build_oniks_booster")


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


# --- Dedicated non-Oniks missile models --------------------------------------


def _span(md, axis):
    p = md.vertices[:, axis]
    return float(p.max() - p.min())


def _radius(md):
    verts = md.vertices if hasattr(md, "vertices") else md
    return np.linalg.norm(verts[:, 0:2], axis=1)


def test_dedicated_missile_lengths():
    expected = (
        (build_tomahawk, 6.25),
        (build_jassm, 4.27),
        (build_harm, 4.17),
        (build_aim9x, 3.00),
        (build_48n6, 7.50),
        (build_40n6, 8.00),
        (build_sm2, 6.55),
        (build_57e6, 3.17),
        (build_zircon, 9.00),
        (build_sm6, 6.55),
    )
    for build, length in expected:
        md = build()
        assert abs(_span(md, 2) - length) <= 0.04, build.__name__


def test_cruise_missile_silhouettes_are_distinct():
    tom = build_tomahawk()
    jas = build_jassm()
    harm = build_harm()
    aim = build_aim9x()

    assert _span(tom, 0) >= 2.45      # deployed straight wings
    assert _span(jas, 0) >= 2.25      # broad stealth trapezoid wings
    assert _span(jas, 1) < _span(tom, 1) * 1.15
    assert _radius(harm).max() < 0.55 # slim HARM, smaller than Tomahawk/JASSM
    assert _radius(aim).max() < 0.34  # AIM-9X stays very small
    canards = aim.vertices[(aim.vertices[:, 2] > 0.55)
                           & (_radius(aim) > 0.12)]
    tail = aim.vertices[(aim.vertices[:, 2] < -0.95)
                        & (_radius(aim) > 0.15)]
    assert len(canards) and len(tail)


def test_sam_missile_silhouettes_are_distinct():
    n48 = build_48n6()
    n40 = build_40n6()
    sm2 = build_sm2()
    e57 = build_57e6()

    assert _span(n40, 2) > _span(n48, 2) + 0.45
    assert 0.50 <= _radius(n48).max() <= 0.85
    assert 0.45 <= _radius(sm2).max() <= 0.75
    assert _span(sm2, 0) < _span(n48, 0) * 1.05
    rear = e57.vertices[e57.vertices[:, 2] < -0.75]
    front = e57.vertices[e57.vertices[:, 2] > 0.30]
    assert _radius(rear).max() > _radius(front).max() * 1.8


def test_future_missile_prototype_silhouettes_are_distinct():
    zircon = build_zircon()
    sm6 = build_sm6()

    # Zircon: speculative scramjet/lifting-body look, not a round Standard tube.
    assert _span(zircon, 0) >= 1.45
    assert _span(zircon, 1) < _span(zircon, 0) * 0.75
    underside = zircon.vertices[(zircon.vertices[:, 1] < -0.20)
                                & (zircon.vertices[:, 2] > -1.5)
                                & (zircon.vertices[:, 2] < 1.7)]
    assert len(underside)

    # SM-6: fatter Mk 72 booster aft, narrower Standard/AMRAAM nose forward.
    rear = sm6.vertices[sm6.vertices[:, 2] < -1.75]
    front = sm6.vertices[sm6.vertices[:, 2] > -0.6]
    assert _radius(rear).max() > _radius(front).max() * 1.35
    assert 0.70 <= _radius(sm6).max() <= 0.82


def test_s300_tel_fits_box_when_erect():
    md = build_s300_tel(elevation_deg=90.0)
    p = md.vertices[:, 0:3]
    ext = p.max(axis=0) - p.min(axis=0)
    assert ext[0] <= 4.0           # width (east-west)
    assert 9.0 <= ext[1] <= 10.0   # Task OM2: erect height 9-10 m
    assert ext[2] <= 14.5          # ~13 m chassis + the rear tube overhang
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


# --- Task OM2: 5P85 TEL proportions per s300_reference.md ---------------------


def test_s300_tel_rear_block_towers():
    """Signature 1: erect tube tops at ~9-9.5 m, the whole block at the rear
    (aft of the rear axles); stowed tubes overhang the tail."""
    md = build_s300_tel(elevation_deg=90.0)
    tube = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["tube_grey"],
                             atol=1e-4), axis=1)
    assert 8.9 <= md.vertices[tube, 1].max() <= 9.6
    up = md.vertices[tube & (md.vertices[:, 1] > 5.0)]
    assert up[:, 2].max() < -4.0            # block fully on the rear overhang
    stowed = build_s300_tel(elevation_deg=0.0)
    tube_s = np.all(np.isclose(stowed.vertices[:, 6:9], PALETTE["tube_grey"],
                               atol=1e-4), axis=1)
    assert stowed.vertices[tube_s, 2].min() <= -6.6   # past the 13 m frame


def test_s300_tel_clamp_rings():
    """Signature 4: 3-4 circumferential clamp rings per tube, spread along
    the barrel (distinct height bands when erect)."""
    md = build_s300_tel(elevation_deg=90.0)
    ring = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["tube_ring"],
                             atol=1e-4), axis=1)
    assert ring.any()
    ys = md.vertices[ring, 1]
    assert ys.max() - ys.min() >= 4.0       # spread along the 8 m tube
    bands = np.unique(np.round(ys / 0.5))   # >= 3 distinct ring stations
    assert len(bands) >= 3


def test_s300_tel_dome_caps_and_f3s_cabin():
    """Signatures 7/10: black dome bottom caps hanging just off the ground
    when erect; boxy F3S electronics cabin (cab-tall) behind the cab."""
    md = build_s300_tel(elevation_deg=90.0)
    dome = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["exhaust_ring"],
                             atol=1e-4), axis=1)
    low = md.vertices[dome & (md.vertices[:, 1] < 1.2)]
    assert len(low)
    assert 0.3 <= low[:, 1].min() <= 1.0    # domes hang just off the ground
    green = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["s300_green"],
                              atol=1e-4), axis=1)
    f3s = md.vertices[green & (md.vertices[:, 2] > 1.0)
                      & (md.vertices[:, 2] < 3.85)]
    assert len(f3s)
    assert f3s[:, 1].max() >= 3.2           # cabin nearly as tall as the cab


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
