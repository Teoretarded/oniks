"""Reusable COMBAT playtest harness.

Two entry points, sharing one findings ledger:

* ``build_world(seed, **cfg)`` — construct a CombatWorld WITHOUT a GL context
  (pure sim). Fast; use it to test generation, determinism and variety across
  many seeds.
* ``Battle(seed, **cfg)`` — a full headless App + combat session, with clean
  primitives to drive real inputs (keys, map clicks, camera), fast-forward the
  sim, capture screenshots and query state. Use it for in-game verification.

``finding(category, ...)`` appends to a JSONL ledger that persists across
separate battle processes; ``write_report()`` renders it to markdown. Crash-prone
probes (camera zoom on arbitrary objects) go through ``Battle.try_zoom`` which
catches the crash, logs it, and lets the hunt continue instead of dying.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from world.combat import CombatWorld  # noqa: E402  (pure sim — no GL)
from world.combat_config import CombatConfig  # noqa: E402

RENDERS = "renders"
FINDINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "playtest_findings.jsonl")
CURRENT_BATTLE = ""


# --------------------------------------------------------------- findings ----

def set_battle(name):
    global CURRENT_BATTLE
    CURRENT_BATTLE = name
    print(f"\n=== BATTLE: {name} ===", flush=True)


def reset_findings():
    if os.path.exists(FINDINGS_FILE):
        os.remove(FINDINGS_FILE)


def finding(category, title, detail="", evidence=""):
    """Record a SUSPECTED issue. category in CRASHER/LOGIC/BALANCE/COSMETIC/QOL.

    These are suspicions to be triaged, not confirmed bugs."""
    rec = dict(category=category, title=title, detail=detail,
               evidence=evidence, battle=CURRENT_BATTLE)
    with open(FINDINGS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(f"  [FIND/{category}] {title}" + (f" — {detail}" if detail else ""),
          flush=True)


def write_report(path="tools/playtest_report.md"):
    recs = []
    if os.path.exists(FINDINGS_FILE):
        with open(FINDINGS_FILE, encoding="utf-8") as fh:
            recs = [json.loads(ln) for ln in fh if ln.strip()]
    order = ["CRASHER", "LOGIC", "BALANCE", "COSMETIC", "QOL"]
    lines = ["# COMBAT playtest findings", "", f"{len(recs)} findings.", ""]
    for k in order:
        group = [r for r in recs if r["category"] == k]
        if not group:
            continue
        lines.append(f"## {k} ({len(group)})")
        lines.append("")
        for r in group:
            lines.append(f"- **{r['title']}**  _(battle: {r['battle']})_")
            if r.get("detail"):
                lines.append(f"  - {r['detail']}")
            if r.get("evidence"):
                lines.append(f"  - `{r['evidence']}`")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"\n[report] {path}: {len(recs)} findings", flush=True)


# ------------------------------------------------ GL-free world build --------

def build_world(seed, **cfg):
    """Construct a CombatWorld with no GL context — pure sim, fast."""
    return CombatWorld(CombatConfig(seed=seed, **cfg))


def world_signature(w):
    """Compact, deterministic fingerprint of a freshly built world (t=0)."""
    ships = sorted((round(float(s.pos[0]) / 1000.0),
                    round(float(s.pos[2]) / 1000.0)) for s in w.ships)
    return dict(
        n_ships=len(w.ships),
        ships_km=ships,
        n_sites=len(getattr(w, "sites", []) or []),
        n_aircraft=len(getattr(w, "aircraft", []) or []),
        n_pantsir=len(getattr(w, "pantsirs", None) or
                      getattr(w, "pantsir_units", None) or []),
        n_enemy_radar=len(getattr(w, "enemy_radars", None) or []),
    )


# ----------------------------------------------- full battle (App + GL) ------

class Battle:
    """A headless combat session with player-style input + camera primitives."""

    def __init__(self, seed, **cfg):
        from main import App
        self.app = App(hidden=True)
        self.cfg = CombatConfig(seed=seed, **cfg)
        self.app.start_combat(self.cfg)
        self.state = self.app.state
        self.world = self.state.world
        self.seed = seed

    # ---- time ----
    def fast(self, seconds):
        """Step the sim only (no render) for ``seconds`` of sim time."""
        from main import PHYS_DT
        for _ in range(int(seconds / PHYS_DT)):
            self.state.sim_step(PHYS_DT)

    def settle(self, frames=18):
        """Render a few frames so the camera rig / effects catch up."""
        from main import PHYS_DT
        for _ in range(frames):
            self.state.render(PHYS_DT)

    # ---- inputs ----
    def key(self, k):
        self.state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k,
                                                    unicode="", mod=0))
        self.state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))

    def tab_to(self, platform, max_tabs=10):
        for _ in range(max_tabs):
            if self.state.active_platform == platform:
                return True
            self.key(pygame.K_TAB)
        return self.state.active_platform == platform

    def open_map(self, deadline=120 * 90):
        """Open the tactical map and render until the MapView exists (what
        click() needs) AND the raster is ready — see playtest_killchain."""
        from main import PHYS_DT
        from game import tactical_map as tm
        self.state.map_open = True
        d = 0
        while (self.state.tactical_map.view is None
               or tm.get_map_pixels() is None) and d < deadline:
            self.state.sim_step(PHYS_DT)
            self.state.render(PHYS_DT)
            d += 1
        return self.state.tactical_map.view is not None

    def close_map(self):
        self.state.map_open = False

    def click(self, xz, button=1):
        if self.state.tactical_map.view is None:
            self.open_map()
        sx, sy = self.state.tactical_map.view.world_to_screen(
            (float(xz[0]), float(xz[1])))
        for et in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            self.state.handle_event(pygame.event.Event(et, button=button,
                                                       pos=(int(sx), int(sy))))
        return int(sx), int(sy)

    # ---- camera ----
    def follow(self, obj, mode="orbit", dist=8.0):
        self.state.followed = obj
        self.state.rig.set_mode(mode)
        self.state.rig.retarget()
        if dist is not None:
            self.state.rig._orbit_dist = dist
            self.state.rig._orbit_dist_target = dist

    def try_zoom(self, obj, label, dist=8.0, frames=8):
        """Follow + orbit + zoom an object and render. Catch any crash, log it
        as a CRASHER finding, restore state, return the exception (or None)."""
        prev_map, prev_followed = self.state.map_open, self.state.followed
        try:
            self.state.map_open = False
            self.follow(obj, "orbit", dist)
            self.settle(frames)
            return None
        except Exception as e:
            tb = traceback.format_exc().strip().splitlines()
            finding("CRASHER", f"camera zoom crash: {label}",
                    detail=f"orbit {dist} m on {label} ({type(obj).__name__})",
                    evidence=(tb[-1] if tb else str(e)))
            return e
        finally:
            self.state.followed, self.state.map_open = prev_followed, prev_map

    # ---- capture ----
    def shot(self, name, note=""):
        self.settle(18)
        os.makedirs(RENDERS, exist_ok=True)
        pygame.image.save(self.app.window.read_pixels_to_surface(),
                          os.path.join(RENDERS, f"{name}.png"))
        print(f"  [shot] {name}.png  {note}", flush=True)

    # ---- queries ----
    def player_missiles(self):
        return [m for m in self.world.missiles
                if not getattr(m, "is_hostile", False)]

    def hostile_missiles(self):
        return [m for m in self.world.missiles
                if getattr(m, "is_hostile", False)]

    def surface_tracks(self):
        return [cid for cid, t in self.world.contacts.tracks.items()
                if not t.get("is_air")]

    def picture(self):
        w = self.world
        trk = w.contacts.tracks
        air = sum(1 for t in trk.values() if t.get("is_air"))
        struct = [s.kind for s in getattr(w, "structures", [])
                  if getattr(s, "alive", True)]
        return (f"t={w.sim_time:6.0f}s tracks={len(trk)}(air {air}/"
                f"surf {len(trk) - air}) oniks={getattr(w, '_oniks_ammo', None)} "
                f"missiles={len(w.missiles)} base={'/'.join(struct)} "
                f"def={getattr(w, 'defeated', '?')} "
                f"vic={getattr(w, 'victorious', '?')}")

    def close(self):
        try:
            pygame.quit()
        except Exception:
            pass
