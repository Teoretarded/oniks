"""Back-plot feature byte-identical gate: a 3000-step same-seed digest of the
DEFAULT-config CombatWorld that EXERCISES the commander back-plot pipeline.

Task A (the back_plot_surface() extract) MUST leave this digest unchanged
(bit-identical) vs the pre-refactor HEAD.  Task B (the reliability buff) is the
ONE allowed, documented exception: the digest WILL change after Task B because
the commander localizes launches more reliably; the new digest is captured and
pinned in this file's PINNED_DIGEST so it is itself reproducible.

It fires a lo-lo (sea-skim) Oniks salvo from the real Bastion pad toward the
fleet band so the world's commander feed runs process_missile_track on real
tracks, then SHA-256-hashes every dynamic datum (ship pos/state/ammo, every
missile pos/vel/alive, event count) AND the commander's back-plot/cluster state
(raw fix count + estimates + cluster centroids + targetable flags) every 50
steps.

Run: python tools/wf_backplot_digest.py   (prints the digest; exit 0)
"""

import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0

# Pinned post-Task-B digest. Task A (the back_plot_surface extract) left this
# digest BIT-IDENTICAL to pre-change HEAD; Task B (the reliability buff) is the
# ONE allowed, documented change — the 16 000-step window reaches back-plot
# formation, where the buffed level-skimmer projection now records fixes at the
# coastal-setback line (z = -300) instead of the bare waterline (z = 0), shifting
# the commander back-plot state. This pin makes the post-buff battle reproducible.
PINNED_DIGEST = "bba4b1b52292beae4b8143ff5971c4aed21d05573a1d3c15dd92e34598d936b5"


def _f(h, x):
    h.update(struct.pack("<d", float(x)))


def _vec(h, v):
    for c in v:
        _f(h, c)


def _hash_commander_backplot(h, cw):
    """Hash the enemy commander's back-plot pipeline state (the path the extract
    + the buff touch). Robust to the commander not yet existing.

    DETERMINISM NOTE: a real-world back-plot fix's ``track_id`` is
    ``hostile_{id(missile):x}`` — derived from a Python object id (a memory
    address), which is NOT reproducible across processes. We deliberately do NOT
    hash the track_id; we hash the GEOMETRIC/NUMERIC fix content (estimate,
    error, cluster centroid, fix count, targetable), which IS deterministic and
    is exactly what the extract (unchanged) and the buff (z shifted by the
    setback) affect. Fixes are sorted by their estimate so dict/order effects
    cannot perturb the digest."""
    cmd = getattr(cw, "commander", None)
    if cmd is None:
        h.update(b"NOCMD")
        return
    pic = cmd.picture
    bps = sorted(getattr(pic, "_back_plots", []),
                 key=lambda b: (float(b.estimated_pos[0]),
                                float(b.estimated_pos[1]), float(b.error_m)))
    h.update(struct.pack("<i", len(bps)))
    for bp in bps:
        _vec(h, bp.estimated_pos)
        _f(h, bp.error_m)
    clusters = sorted(getattr(pic, "clusters", []),
                      key=lambda c: (float(c.centre[0]), float(c.centre[1])))
    h.update(struct.pack("<i", len(clusters)))
    for c in clusters:
        _vec(h, c.centre)
        h.update(struct.pack("<i", len(c.fixes)))
        h.update(b"\x01" if c.targetable else b"\x00")


def digest(steps=16_000, seed=1337):
    cfg = CombatConfig(seed=seed)
    cw = CombatWorld(cfg)
    h = hashlib.sha256()

    # Fire lo-lo (sea-skim) Oniks salvos from the real Bastion pad toward the
    # fleet band — the realistic leak the commander back-plots. The horizon
    # (16 000 steps = ~133 s) is set from the MEASURED flight: a lo-lo round is
    # first detected ~114 s after launch (~350 km AWACS slant), so this window
    # REACHES back-plot formation — the digest actually EXERCISES the buffed
    # level-skimmer projection (Task A leaves it bit-identical; Task B changes it,
    # which is the one allowed, documented digest change, pinned below).
    target = np.array([0.0, 0.0, 220_000.0])
    fire_steps = {60, 360, 660}
    for i in range(steps):
        if i in fire_steps:
            cw.launch("lo-lo", target)
        cw.step(DT)
        if i % 50 == 0:
            for s in cw.ships:
                _vec(h, s.pos)
                h.update(struct.pack("<i", int(s.state)))
                h.update(struct.pack("<i", int(getattr(s, "sm2_ammo", 0))))
                h.update(struct.pack("<i", int(getattr(s, "sm6_ammo", 0))))
                h.update(struct.pack("<i",
                         int(getattr(s, "tomahawk_ammo", 0))))
            for m in cw.missiles:
                _vec(h, m.pos)
                _vec(h, m.vel)
                h.update(b"\x01" if m.alive else b"\x00")
            h.update(struct.pack("<i", len(cw.events)))
            h.update(struct.pack("<i", len(cw.missiles)))
            _hash_commander_backplot(h, cw)
    h.update(struct.pack("<i", len(cw.missiles)))
    for s in cw.ships:
        _vec(h, s.pos)
    _hash_commander_backplot(h, cw)
    return h.hexdigest()


if __name__ == "__main__":
    d = digest()
    print("BACKPLOT_DEFAULT_DIGEST", d)
    if PINNED_DIGEST is not None:
        print("PINNED", PINNED_DIGEST,
              "MATCH" if d == PINNED_DIGEST else "MISMATCH")
