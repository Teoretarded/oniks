"""TEST MAP articles: the 6-DOF test hopper and its bland test chamber.

Deliberately imports NO other model file — the user's directive for the
test map is all-new geometry. Pure meshdata (GL-free).

Model space (LOCKED conventions): +Z forward = the vehicle's nose, +Y up,
meters, origin at the geometric center — matching sim/sixdof.py, whose
quaternion maps body +Z to world attitude.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_grid, make_lathe)

# Test-article paint: high-vis orange / white photogrammetry scheme.
ORANGE = (0.85, 0.42, 0.12)
WHITE = (0.88, 0.88, 0.86)
DARK = (0.16, 0.16, 0.18)
STEEL = (0.35, 0.36, 0.38)
BLUE = (0.22, 0.42, 0.72)      # spin dart livery
GREEN = (0.30, 0.62, 0.34)     # TVC stick livery
RED_P = (0.72, 0.20, 0.16)     # tractor livery
PURPLE = (0.48, 0.28, 0.70)    # hybrid control article
CYAN = (0.20, 0.68, 0.72)      # instrument / RCS markings
YELLOW = (0.88, 0.68, 0.12)    # pulse / hazard markings
BLACK = (0.055, 0.06, 0.065)

HOPPER_LENGTH = 3.0
HOPPER_DIAMETER = 0.36


def build_test_hopper() -> MeshData:
    """The 6-DOF hopper: banded cylinder, lathe nose cone, 4 fins, nozzle
    skirt. Sized exactly to the sim def (3.0 m x 0.36 m)."""
    b = MeshBuilder()
    r = 0.5 * HOPPER_DIAMETER
    half = 0.5 * HOPPER_LENGTH
    nose_len = 0.55
    tail = -half
    body_len = HOPPER_LENGTH - nose_len

    # Alternating photogrammetry bands up the body (along +Z).
    bands = 6
    seg_len = body_len / bands
    for i in range(bands):
        z0 = tail + i * seg_len
        color = ORANGE if i % 2 == 0 else WHITE
        b.add_mesh(make_cylinder(r, seg_len, 20, color, axis="z",
                                 offset=(0.0, 0.0, z0 + 0.5 * seg_len),
                                 cap_ends=(i == 0)))

    # Nose cone: lathe profile from body radius to a rounded tip.
    prof = [(half - nose_len, r)]
    for k in range(1, 6):
        f = k / 6.0
        prof.append((half - nose_len + f * nose_len,
                     r * math.cos(f * math.pi * 0.5) ** 0.8))
    prof.append((half, 0.0))
    b.add_mesh(make_lathe(prof, 20, ORANGE))

    # Four fins at the tail, cross pattern (fin lies in a plane; rotate
    # copies about Z).
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        ca, sa = math.cos(ang), math.sin(ang)
        rot = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        fin = make_fin(root_chord=0.55, tip_chord=0.28, span=0.34,
                       sweep=0.20, thickness=0.02, color=WHITE)
        # Fin chords extend aft (-Z) from the leading edge: put the LE at
        # tail+0.55 so the trailing edge lands exactly on the tail plane.
        b.add_mesh(fin, offset=(r * ca * 1.02, r * sa * 1.02, tail + 0.55),
                   rotation=rot)

    # Nozzle skirt + dark throat, slightly proud of the tail.
    b.add_mesh(make_lathe([(tail - 0.12, 0.10), (tail + 0.02, 0.15),
                           (tail + 0.10, 0.17)], 16, STEEL))
    b.add_mesh(make_cylinder(0.09, 0.10, 12, DARK, axis="z",
                             offset=(0.0, 0.0, tail - 0.10)))
    return b.build()


def build_spin_dart() -> MeshData:
    """The spin-stabilized dart: slim blue/white barber-pole body (the
    stripes make roll VISIBLE), long lathe nose, four small fins with a
    visible cant, canted nozzle ring at the tail. 1.8 m x 0.16 m."""
    b = MeshBuilder()
    r = 0.08
    half = 0.9
    nose_len = 0.42
    tail = -half
    body_len = 1.8 - nose_len

    bands = 8                       # barber pole: thin alternating rings
    seg = body_len / bands
    for i in range(bands):
        z0 = tail + i * seg
        color = BLUE if i % 2 == 0 else WHITE
        b.add_mesh(make_cylinder(r, seg, 16, color, axis="z",
                                 offset=(0.0, 0.0, z0 + 0.5 * seg),
                                 cap_ends=(i == 0)))
    prof = [(half - nose_len, r)]
    for k in range(1, 5):
        f = k / 5.0
        prof.append((half - nose_len + f * nose_len,
                     r * (1.0 - f * f) ** 0.7))
    prof.append((half, 0.0))
    b.add_mesh(make_lathe(prof, 16, BLUE))

    for k in range(4):              # small fins, canted 8 deg for show
        ang = k * math.pi * 0.5
        ca, sa = math.cos(ang), math.sin(ang)
        rot_z = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        cant = math.radians(8.0)
        cc, cs = math.cos(cant), math.sin(cant)
        rot_cant = np.array([[cc, 0.0, cs], [0.0, 1.0, 0.0],
                             [-cs, 0.0, cc]])
        fin = make_fin(root_chord=0.22, tip_chord=0.12, span=0.14,
                       sweep=0.08, thickness=0.012, color=WHITE)
        b.add_mesh(fin, offset=(r * ca, r * sa, tail + 0.24),
                   rotation=rot_z @ rot_cant)
    b.add_mesh(make_lathe([(tail - 0.06, 0.045), (tail + 0.02, 0.07)],
                          12, STEEL))
    return b.build()


def build_tvc_stick() -> MeshData:
    """The TVC balancing stick: tall thin pencil, green control band at
    the top (avionics), bare white tube, wide gimbal skirt at the base
    with four actuator pods. No fins — the FCS is the stability.
    3.6 m x 0.30 m."""
    b = MeshBuilder()
    r = 0.15
    half = 1.8
    nose_len = 0.4
    tail = -half

    b.add_mesh(make_cylinder(r, 0.5, 18, GREEN, axis="z",
                             offset=(0.0, 0.0, half - nose_len - 0.25)))
    b.add_mesh(make_cylinder(r, 3.6 - nose_len - 0.5, 18, WHITE, axis="z",
                             offset=(0.0, 0.0,
                                     tail + 0.5 * (3.6 - nose_len - 0.5)),
                             cap_ends=True))
    prof = [(half - nose_len, r), (half - 0.12, r * 0.55), (half, 0.0)]
    b.add_mesh(make_lathe(prof, 18, GREEN))

    # Gimbal skirt: flared lathe + four actuator pods around it.
    b.add_mesh(make_lathe([(tail - 0.10, 0.11), (tail + 0.08, 0.17),
                           (tail + 0.22, 0.19)], 16, STEEL))
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        b.add_mesh(make_box((0.06, 0.06, 0.22), DARK,
                            offset=(0.20 * math.cos(ang),
                                    0.20 * math.sin(ang), tail + 0.18)))
    b.add_mesh(make_cylinder(0.075, 0.1, 12, DARK, axis="z",
                             offset=(0.0, 0.0, tail - 0.08)))
    return b.build()


def build_tractor() -> MeshData:
    """The pendulum-fallacy tractor: hopper-sized red/white tube with the
    MOTOR POD ON TOP — a flared tractor nozzle ring up high and a blunt
    cargo dome at the bottom. Reads instantly as 'the engine pulls'.
    3.0 m x 0.36 m."""
    b = MeshBuilder()
    r = 0.18
    half = 1.5
    tail = -half

    # Blunt cargo dome at the BOTTOM (no nozzle down here).
    prof = [(tail, 0.0)]
    for k in range(1, 5):
        f = k / 5.0
        prof.append((tail + f * 0.30, r * math.sin(f * math.pi * 0.5)))
    b.add_mesh(make_lathe(prof, 18, WHITE))

    bands = 4
    body_len = 2.1
    seg = body_len / bands
    for i in range(bands):
        z0 = tail + 0.30 + i * seg
        color = RED_P if i % 2 == 0 else WHITE
        b.add_mesh(make_cylinder(r, seg, 18, color, axis="z",
                                 offset=(0.0, 0.0, z0 + 0.5 * seg),
                                 cap_ends=False))

    # Motor pod on TOP: narrower drum + upward flare + dark exhaust ring
    # (exhaust is ducted outward past the body, LES-tower style).
    pod_z = tail + 0.30 + body_len
    b.add_mesh(make_cylinder(0.12, 0.34, 16, STEEL, axis="z",
                             offset=(0.0, 0.0, pod_z + 0.17)))
    b.add_mesh(make_lathe([(pod_z + 0.34, 0.12), (half + 0.05, 0.16)],
                          16, RED_P))
    b.add_mesh(make_cylinder(0.05, 0.12, 10, DARK, axis="z",
                             offset=(0.0, 0.0, half + 0.02)))
    for k in range(4):              # small stabilizer strakes low down
        ang = k * math.pi * 0.5 + math.pi * 0.25
        ca, sa = math.cos(ang), math.sin(ang)
        rot = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        fin = make_fin(root_chord=0.4, tip_chord=0.22, span=0.2,
                       sweep=0.12, thickness=0.016, color=RED_P)
        b.add_mesh(fin, offset=(r * ca, r * sa, tail + 0.70), rotation=rot)
    return b.build()


def build_returner() -> MeshData:
    """Reusable 4.8 m booster with grid fins, landing legs and one deep-
    throttling gimballed bell. Its silhouette makes the landing job obvious."""
    b = MeshBuilder()
    r, half, tail = 0.26, 2.4, -2.4
    # Stainless/black test-booster bands.
    for i, color in enumerate((WHITE, STEEL, WHITE, BLACK, WHITE, STEEL)):
        z0 = tail + i * 0.70
        b.add_mesh(make_cylinder(r, 0.70, 22, color, axis="z",
                                 offset=(0.0, 0.0, z0 + 0.35),
                                 cap_ends=(i == 0)))
    b.add_mesh(make_lathe([(1.80, r), (2.18, r * 0.72), (half, 0.0)],
                          22, WHITE))
    # Four grid-fin slabs high on the stage.
    for k in range(4):
        ang = k * math.pi * 0.5
        ca, sa = math.cos(ang), math.sin(ang)
        rot = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        fin = make_fin(root_chord=0.42, tip_chord=0.42, span=0.34,
                       sweep=0.0, thickness=0.035, color=BLACK)
        b.add_mesh(fin, offset=(r * ca, r * sa, 1.28), rotation=rot)
    # Splayed landing legs, represented as long structural fins.
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        ca, sa = math.cos(ang), math.sin(ang)
        rot = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        leg = make_fin(root_chord=0.82, tip_chord=0.24, span=0.48,
                       sweep=-0.18, thickness=0.045, color=STEEL)
        b.add_mesh(leg, offset=(r * ca, r * sa, tail + 0.85), rotation=rot)
    b.add_mesh(make_lathe([(tail - 0.28, 0.13), (tail - 0.05, 0.23),
                           (tail + 0.20, 0.19)], 20, DARK))
    b.add_mesh(make_cylinder(0.09, 0.12, 14, BLACK, axis="z",
                             offset=(0.0, 0.0, tail - 0.25)))
    return b.build()


def build_gyro_gimbal() -> MeshData:
    """Spin/TVC hybrid with visible purple roll bands, canted side jets and
    an oversized cyan gimbal ring."""
    b = MeshBuilder()
    r, half, tail = 0.12, 1.35, -1.35
    for i in range(9):
        z0 = tail + i * 0.25
        b.add_mesh(make_cylinder(r, 0.25, 18,
                                 PURPLE if i % 2 == 0 else WHITE,
                                 axis="z", offset=(0.0, 0.0, z0 + 0.125),
                                 cap_ends=(i == 0)))
    b.add_mesh(make_lathe([(0.90, r), (1.18, r * 0.62), (half, 0.0)],
                          18, CYAN))
    # Tangential roll-jet pods around the motor section.
    for k in range(4):
        ang = k * math.pi * 0.5
        ca, sa = math.cos(ang), math.sin(ang)
        axis = "x" if k % 2 == 0 else "y"
        b.add_mesh(make_cylinder(0.035, 0.22, 10, CYAN, axis=axis,
                                 offset=(0.16 * ca, 0.16 * sa, tail + 0.35)))
    b.add_mesh(make_lathe([(tail - 0.13, 0.075), (tail + 0.02, 0.14),
                           (tail + 0.16, 0.17)], 16, STEEL))
    b.add_mesh(make_cylinder(0.16, 0.035, 18, CYAN, axis="z",
                             offset=(0.0, 0.0, tail + 0.18)))
    return b.build()


def _build_flip_brake(opened: bool) -> MeshData:
    b = MeshBuilder()
    r, half, tail = 0.21, 1.60, -1.60
    b.add_mesh(make_cylinder(r, 2.70, 20, WHITE, axis="z",
                             offset=(0.0, 0.0, tail + 1.35), cap_ends=True))
    b.add_mesh(make_lathe([(1.10, r), (1.42, 0.13), (half, 0.0)],
                          20, ORANGE))
    b.add_mesh(make_cylinder(r * 1.03, 0.22, 20, BLACK, axis="z",
                             offset=(0.0, 0.0, -0.65)))
    # Four drag petals: small/tucked in the closed mesh, enormous when open.
    span = 0.58 if opened else 0.18
    color = ORANGE if opened else STEEL
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        ca, sa = math.cos(ang), math.sin(ang)
        rot = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        petal = make_fin(root_chord=0.72, tip_chord=0.62, span=span,
                         sweep=0.02, thickness=0.035, color=color)
        b.add_mesh(petal, offset=(r * ca, r * sa, tail + 0.78), rotation=rot)
    b.add_mesh(make_lathe([(tail - 0.12, 0.09), (tail + 0.04, 0.18)],
                          16, DARK))
    return b.build()


def build_flip_brake() -> MeshData:
    return _build_flip_brake(False)


def build_flip_brake_open() -> MeshData:
    return _build_flip_brake(True)


def build_rcs_needle() -> MeshData:
    """Vacuum-control needle with two bright reaction-jet belts."""
    b = MeshBuilder()
    r, half, tail = 0.10, 1.25, -1.25
    b.add_mesh(make_cylinder(r, 2.15, 16, BLACK, axis="z",
                             offset=(0.0, 0.0, tail + 1.075), cap_ends=True))
    b.add_mesh(make_lathe([(0.90, r), (1.10, 0.055), (half, 0.0)],
                          16, CYAN))
    for z in (-0.58, 0.55):
        b.add_mesh(make_cylinder(r * 1.08, 0.12, 16, YELLOW, axis="z",
                                 offset=(0.0, 0.0, z)))
        for k in range(4):
            ang = k * math.pi * 0.5
            ca, sa = math.cos(ang), math.sin(ang)
            axis = "x" if k % 2 == 0 else "y"
            b.add_mesh(make_cylinder(0.026, 0.18, 8, STEEL, axis=axis,
                                     offset=(0.13 * ca, 0.13 * sa, z)))
    b.add_mesh(make_lathe([(tail - 0.08, 0.05), (tail + 0.04, 0.085)],
                          12, DARK))
    return b.build()


def build_pulse_lander() -> MeshData:
    """Compact gold/white lander with a four-chamber pulse motor and legs."""
    b = MeshBuilder()
    r, half, tail = 0.24, 1.45, -1.45
    for i, color in enumerate((YELLOW, WHITE, YELLOW, WHITE, YELLOW)):
        z0 = tail + i * 0.50
        b.add_mesh(make_cylinder(r, 0.50, 20, color, axis="z",
                                 offset=(0.0, 0.0, z0 + 0.25),
                                 cap_ends=(i == 0)))
    b.add_mesh(make_lathe([(1.05, r), (1.30, 0.13), (half, 0.0)],
                          20, WHITE))
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        ca, sa = math.cos(ang), math.sin(ang)
        # Distinct pulse chambers and landing feet.
        b.add_mesh(make_lathe([(tail - 0.12, 0.045), (tail + 0.03, 0.075)],
                              10, DARK), offset=(0.11 * ca, 0.11 * sa, 0.0))
        rot = np.array([[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]])
        leg = make_fin(root_chord=0.48, tip_chord=0.18, span=0.30,
                       sweep=-0.10, thickness=0.035, color=STEEL)
        b.add_mesh(leg, offset=(r * ca, r * sa, tail + 0.48), rotation=rot)
    return b.build()


def build_test_ground(half_extent: float = 1000.0, tile: float = 50.0
                      ) -> MeshData:
    """The bland test chamber: a flat checkerboard plate. No terrain,
    no water, no props — the map IS the control group."""
    n = int(2 * half_extent / tile)
    xs = np.linspace(-half_extent, half_extent, n + 1)
    zs = np.linspace(-half_extent, half_extent, n + 1)
    heights = np.zeros((n + 1, n + 1))
    colors = np.empty((n + 1, n + 1, 3), dtype=np.float64)
    for i in range(n + 1):
        for j in range(n + 1):
            checker = (i + j) % 2 == 0
            colors[i, j] = (0.30, 0.31, 0.30) if checker else (0.24, 0.25,
                                                               0.24)
    return make_grid(xs, zs, heights, colors)


def build_launch_pad(size: float = 6.0) -> MeshData:
    """A painted pad square under the hopper: concrete plate + orange
    corner wedges so scale and attitude read on camera."""
    b = MeshBuilder()
    b.add_mesh(make_cylinder(size * 0.5, 0.08, 24, (0.44, 0.45, 0.46),
                             axis="y", offset=(0.0, 0.04, 0.0)))
    for k in range(4):
        ang = k * math.pi * 0.5 + math.pi * 0.25
        b.add_mesh(make_cylinder(0.12, 0.5, 10, ORANGE, axis="y",
                                 offset=(size * 0.42 * math.cos(ang), 0.25,
                                         size * 0.42 * math.sin(ang))))
    return b.build()
