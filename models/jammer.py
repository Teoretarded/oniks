"""Procedural EA-18G Growler-class escort jammer model.

The Growler is an F/A-18F Super Hornet derivative — NOT a 707-based AWACS — so
this model REUSES ``models.fighter.build_fighter`` for the airframe and bolts
on the electronic-attack signature that tells a Growler apart from a plain
fighter (and, more importantly for the player, from the E-2/E-3 AWACS that the
escort jammer used to share a mesh with):

  - Two underwing ALQ-99/ALQ-249 tactical jamming pods on wing pylons.
  - One centreline ALQ-99 pod under the belly.
  - Two wingtip ALQ-218 receiver pods (the wingtip fairings that replace the
    Super Hornet's wingtip missile rails — the most recognisable Growler cue).

Each ALQ-99 pod carries a dark ram-air-turbine (RAT) fairing at its nose — the
little bullet that drives the jammer's generator.  The pods wear a distinct
``jammer_pod`` paint so the kit reads as electronic-attack equipment rather
than ordnance.

Real scale (inherited from the Super Hornet airframe): 18.3 m long, 13.6 m
wing span.  Model space: forward = +Z (nose at +z_max), up = +Y, origin at the
centre of mass (mid-fuselage).  Pure numpy, GL-free.
"""

from __future__ import annotations

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder
from models.common import PALETTE
from models.fighter import build_fighter

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

_POD = PALETTE["jammer_pod"]      # distinct EW-pod paint (sets the kit apart)
_DARK = PALETTE["aircraft_dark"]  # RAT fairing noses / receiver caps
_GREY = PALETTE["aircraft_grey"]  # pylons (match the airframe)

_SEG = 14   # cylinder segments (pods are small — modest budget)


def _alq99_pod(b: MeshBuilder, x: float, y: float, z: float,
               length: float, radius: float, pylon_to_y: float) -> None:
    """One ALQ-99-class jamming pod: a canoe body, a dark RAT nose bullet at
    the front (+Z) end, and a thin pylon up to ``pylon_to_y`` (the wing/belly
    it hangs from).  Centred at (x, y, z)."""
    half = length * 0.5
    # Pod body (canoe).
    b.add_mesh(make_cylinder(radius, length, _SEG, _POD, axis="z",
                             offset=(x, y, z)))
    # Ram-air-turbine fairing: a short dark bullet just ahead of the nose.
    b.add_mesh(make_cylinder(radius * 0.6, 0.5, _SEG, _DARK, axis="z",
                             offset=(x, y, z + half + 0.2)))
    # Pylon: a thin strut from the pod top up to the wing/belly.
    top_y = y + radius
    strut_h = pylon_to_y - top_y
    if strut_h > 0.0:
        b.add_mesh(make_box((0.18, strut_h, 1.0), _GREY,
                            offset=(x, top_y + strut_h * 0.5, z)))


def _wingtip_pod(b: MeshBuilder, x: float, y: float, z: float) -> None:
    """One ALQ-218 wingtip receiver pod: a slim fairing with a dark nose cap,
    sitting at the wingtip (the Growler's signature replacement for the
    Super Hornet's wingtip missile rails).  Centred at (x, y, z)."""
    length, radius = 2.0, 0.18
    b.add_mesh(make_cylinder(radius, length, _SEG - 2, _POD, axis="z",
                             offset=(x, y, z)))
    # Dark nose cap (the antenna fairing) at the front.
    b.add_mesh(make_cylinder(radius * 0.55, 0.4, _SEG - 4, _DARK, axis="z",
                             offset=(x, y, z + length * 0.5 + 0.15)))


def build_jammer() -> MeshData:
    """EA-18G Growler escort jammer: the Super Hornet airframe plus the
    electronic-attack pod kit (2 underwing + 1 centreline ALQ-99 pods, 2
    wingtip ALQ-218 receiver pods).

    Model space: forward = +Z, up = +Y, origin at mid-fuselage.
    """
    b = MeshBuilder()

    # The Super Hornet airframe, reused verbatim (a Growler IS a Super Hornet).
    b.add_mesh(build_fighter())

    # Two underwing ALQ-99 jamming pods, hung from the wings (wing at y ~ -0.25).
    for sx in (1.0, -1.0):
        _alq99_pod(b, x=sx * 2.6, y=-0.95, z=0.6,
                   length=3.6, radius=0.33, pylon_to_y=-0.25)

    # One centreline ALQ-99 pod under the belly (fuselage bottom ~ y -0.85).
    _alq99_pod(b, x=0.0, y=-1.05, z=-0.3,
               length=4.0, radius=0.34, pylon_to_y=-0.85)

    # Two wingtip ALQ-218 receiver pods (just inboard of the ~6.85 m wingtips).
    for sx in (1.0, -1.0):
        _wingtip_pod(b, x=sx * 6.75, y=-0.20, z=-0.6)

    return b.build()
