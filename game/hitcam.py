"""X-RAY HIT CAM — the full-screen slow-mo damage cutaway (2026-07-06 spec).

When a player round connects under the subsystem damage model, the combat
shell opens this overlay for a few real-time seconds: a side-view X-ray
schematic of the struck hull built from the SAME module grid the sim used
(sim/damage_model.GRID_BY_TYPE), the impact point, the modules this hit
killed lit red, flooding compartments shading blue, the fire glow, and a
consequence readout ("MAIN ENGINE ROOM — DESTROYED", "MAGAZINE DETONATION
— SHIP IS LOST").  The sim NEVER pauses — the shell only slows time to
SLOWMO_SCALE while the cam is up (forensics-overlay pattern), and every
fact drawn comes from the WRITE-ONLY ``m.hitcam`` stamp the damage model
left on the dead round (render/AAR layer only; the digest is untouched).

GL-free at import: only engine-side draw calls happen inside draw(), via
the state's TextRenderer.
"""

from __future__ import annotations

HITCAM_S = 5.0             # real seconds the cutaway stays up
SLOWMO_SCALE = 0.25        # sim-time multiplier while the cam is up

# Palette (matches the wardroom-dusk HUD language: dark field, hot accents)
_BG = (0.02, 0.03, 0.05, 0.92)
_HULL = (0.55, 0.62, 0.70)
_WATER = (0.16, 0.38, 0.55, 0.35)
_MODULE = (0.20, 0.26, 0.34, 0.9)
_MODULE_EDGE = (0.38, 0.46, 0.56)
_DEAD = (0.55, 0.10, 0.08, 0.95)
_DEAD_NEW = (1.00, 0.22, 0.10, 1.0)
_FLOOD = (0.10, 0.35, 0.75)
_FIRE = (1.00, 0.55, 0.10)
_INK = (0.92, 0.90, 0.86)
_ACCENT = (1.0, 0.62, 0.2)
_KILL = (1.0, 0.25, 0.15)

_SHIP_NAMES = {
    "destroyer": "DESTROYER (BURKE)",
    "aaw_destroyer": "AIR-DEFENSE ESCORT (BURKE)",
    "ground_attack_destroyer": "STRIKE ESCORT (BURKE)",
    "flagship": "FLAGSHIP (TICONDEROGA)",
    "carrier": "CARRIER (NIMITZ)",
    "cargo": "CARGO SHIP", "tanker": "TANKER", "warship": "PATROL SHIP",
}

_MODULE_LABELS = {
    "vls_aft_64": "AFT VLS (64 CELLS)", "vls_fwd_32": "FWD VLS (32 CELLS)",
    "vls_aft_61": "AFT VLS (61 CELLS)", "vls_fwd_61": "FWD VLS (61 CELLS)",
    "mer2_port": "MAIN ENGINE ROOM 2", "mer1_stbd": "MAIN ENGINE ROOM 1",
    "aux1_gtg": "AUX MACHINERY 1", "aux2": "AUX MACHINERY 2",
    "er_aft": "AFT ENGINE ROOM", "er_fwd": "FWD ENGINE ROOM",
    "spy_fwd": "SPY-1 ARRAYS (FWD)", "spy_aft": "SPY-1 ARRAYS (AFT)",
    "mast": "SENSOR MAST", "bridge": "BRIDGE", "cic": "COMBAT INFO CENTER",
    "island": "ISLAND", "hangar": "HANGAR", "fuel_f76": "FUEL BUNKERS",
    "fuel": "FUEL BUNKERS", "jp5_fuel": "JP-5 AVIATION FUEL",
    "magazine_fwd": "FWD MAGAZINE", "magazine_aft": "AFT MAGAZINE",
    "reactors": "REACTOR SPACES", "machinery": "MACHINERY",
    "engine_room": "ENGINE ROOM", "bridge_accom": "SUPERSTRUCTURE",
}

_KIND_CONSEQUENCE = {
    "propulsion": "PROPULSION HIT - TARGET SLOWING",
    "sensors": "RADAR BLINDED",
    "vls": "MISSILE CELLS DESTROYED",
    "magazine": "MAGAZINE HIT",
    "c2": "COMMAND SPACES HIT",
    "fire": "FUEL RUPTURED - FEEDING THE FIRE",
    "aviation": "HANGAR HIT",
}


class HitCam:
    """Owns the current cutaway snapshot + its real-time countdown."""

    def __init__(self, state):
        self.state = state              # combat shell: .text lives here
        self.snap: dict | None = None
        self.left = 0.0
        self.enabled = True             # future settings toggle

    # ------------------------------------------------------------- control

    @property
    def active(self) -> bool:
        return self.snap is not None and self.left > 0.0

    def notify(self, snap: dict) -> None:
        """A player round connected: show its stamped snapshot (a
        catastrophe replaces whatever was up; otherwise newest wins too)."""
        if not self.enabled:
            return
        self.snap = snap
        self.left = HITCAM_S

    def tick(self, dt_real: float) -> None:
        if self.left > 0.0:
            self.left -= dt_real
            if self.left <= 0.0:
                self.snap = None

    def dismiss(self) -> None:
        self.left = 0.0
        self.snap = None

    # -------------------------------------------------------------- render

    def draw(self, w: int, h: int) -> None:
        if not self.active:
            return
        s = self.snap
        text = self.state.text
        text.draw_rect(0, 0, w, h, _BG)

        # Layout: schematic pane (left 62%), consequence column (right).
        px = int(w * 0.06)
        py = int(h * 0.16)
        pw = int(w * 0.56)
        ph = int(h * 0.58)

        title = f"HIT - {_SHIP_NAMES.get(s['ship_type'], s['ship_type'].upper())}"
        text.draw_text(px, int(h * 0.07), title, _ACCENT, 28)
        sub = (f"{s['weapon'].upper()}  IMPACT {s['ke'] / 1e6:.0f} MJ  "
               + ("PENETRATED HULL" if s["penetrated"] else "SURFACE BURST"))
        text.draw_text(px, int(h * 0.11), sub, _INK, 18)

        self._schematic(text, s, px, py, pw, ph)
        self._readout(text, s, px + pw + int(w * 0.04), py, w, h)

        text.draw_text(px, int(h * 0.88),
                       "X-RAY HIT CAM - TIME SLOWED  (ESC TO DISMISS)",
                       (0.6, 0.6, 0.6), 14)

    # The side-view cutaway: hull outline, waterline, module grid boxes,
    # flooding bins, fire glow, impact marker.
    def _schematic(self, text, s, px, py, pw, ph) -> None:
        # y-grid range drawn: -1 (keel) .. +1.4 (masthead)
        def X(z_frac):                       # stern left -> bow right
            return px + z_frac * pw

        def Y(y_grid):
            return py + (1.4 - y_grid) / 2.4 * ph

        wl = Y(0.0)
        keel = Y(-1.0)
        deck = Y(0.18)

        # Water field below the waterline.
        text.draw_rect(px - 12, wl, pw + 24, py + ph - wl + 12, _WATER)

        # Hull band (keel..deck) + a bow wedge line + deck line.
        text.draw_rect(X(0.0), deck, pw, keel - deck, (*_HULL, 0.18))
        text.draw_lines([(X(0.0), deck), (X(0.97), deck),
                         (X(1.0), wl), (X(0.97), keel),
                         (X(0.0), keel), (X(0.0), deck)], (*_HULL, 1.0), 2.0)
        text.draw_lines([(px - 12, wl), (px + pw + 12, wl)],
                        (0.5, 0.75, 0.95, 0.9), 1.5)

        # Flooding compartment bins along the hull bottom.
        flood = s.get("flood", ())
        n = max(1, len(flood))
        for i, level in enumerate(flood):
            if level <= 0.005:
                continue
            x0 = X(i / n) + 2
            x1 = X((i + 1) / n) - 2
            top = keel + (wl - keel) * min(1.0, level)   # fills upward
            text.draw_rect(x0, top, x1 - x0, keel - top,
                           (*_FLOOD, 0.35 + 0.5 * min(1.0, level)))

        # Fire glow band around the burning region — drawn UNDER the module
        # boxes so the dead-module reds stay legible on top of it.
        fire = float(s.get("fire", 0.0))
        if fire > 0.03:
            fz = float(s.get("fire_z", 0.5))
            half = 0.06 + 0.10 * fire
            text.draw_rect(X(max(0.0, fz - half)), deck - 8,
                           X(min(1.0, fz + half)) - X(max(0.0, fz - half)),
                           (keel - deck) + 8, (*_FIRE, 0.14 + 0.22 * fire))

        # Module boxes.
        new_dead = set(s.get("new_dead", ()))
        all_dead = set(s.get("all_dead", ()))
        for row in s["grid"]:
            name, z0, z1, y0, y1, _xh, _kind = row
            x0, x1 = X(z0), X(z1)
            yt, yb = Y(min(y1, 1.4)), Y(max(y0, -1.0))
            if name in new_dead:
                col = _DEAD_NEW
            elif name in all_dead:
                col = _DEAD
            else:
                col = _MODULE
            text.draw_rect(x0 + 1, yt + 1, max(2, x1 - x0 - 2),
                           max(2, yb - yt - 2), col)
            text.draw_lines([(x0, yt), (x1, yt), (x1, yb), (x0, yb),
                             (x0, yt)], (*_MODULE_EDGE, 0.8), 1.0)

        # Impact marker: crosshair at the entry point.
        iz, iy, _ix = s["impact"]
        cx, cy = X(iz), Y(max(-1.0, min(1.4, iy)))
        text.draw_lines([(cx - 10, cy - 10), (cx + 10, cy + 10)],
                        (*_ACCENT, 1.0), 2.5)
        text.draw_lines([(cx - 10, cy + 10), (cx + 10, cy - 10)],
                        (*_ACCENT, 1.0), 2.5)

    def _readout(self, text, s, x0, y0, w, h) -> None:
        y = y0
        lh = int(h * 0.045)

        def line(msg, col=_INK, size=18):
            nonlocal y
            text.draw_text(x0, y, msg, col, size)
            y += lh

        new_dead = list(s.get("new_dead", ()))
        kinds = s.get("kinds", {})
        if not new_dead and not s.get("penetrated"):
            line("SUPERFICIAL DAMAGE", _INK)
        for name in new_dead:
            line(_MODULE_LABELS.get(name, name.upper()) + " - DESTROYED",
                 _DEAD_NEW)
            cons = _KIND_CONSEQUENCE.get(kinds.get(name, ""), "")
            if cons:
                line("   " + cons, _INK, 14)
        if s.get("breach_m2", 0.0) > 0.05:
            line(f"HULL BREACH {s['breach_m2']:.1f} m2 - FLOODING", _FLOOD[:3])
        if s.get("fire", 0.0) > 0.05:
            line(f"FIRE ONBOARD - INTENSITY {int(s['fire'] * 100)}%",
                 _FIRE[:3])
        if s.get("dead_in_water"):
            line("TARGET DEAD IN THE WATER", _KILL)
        if s.get("catastrophe"):
            y += lh // 2
            line("MAGAZINE DETONATION", _KILL, 28)
            line("SHIP IS LOST", _KILL, 28)
