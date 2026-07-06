"""X-RAY HIT CAM v2 — War-Thunder-style animated damage cutaway.

Visual grammar per the NORMATIVE research doc
docs/research/warthunder_hitcam_visual_language_2026-07-06.md:
translucent ghost hull with SOLID color-coded module boxes inside, the
shell's path drawn as a bright line (green = penetrated, red = stopped at
the plate), a hard beat-pause at the entry flash, then a thin fragment fan
spraying forward from the burst, modules flashing white on the frame their
ray reaches them and easing to their new state color
(steel -> yellow -> orange -> red -> charred), a stacking damage feed, and
TWO synchronized orthographic views (SIDE over TOP/plan, sharing the
fore-aft axis) to fake the 3D read.

Everything animates off the cam's own real-time clock; the sim never
pauses (time slows to SLOWMO_SCALE).  Every fact drawn comes from the
WRITE-ONLY ``m.hitcam`` stamp (render/AAR layer; digest untouched).
GL-free at import; only the state's TextRenderer is touched in draw().
"""

from __future__ import annotations

import math

HITCAM_S = 6.5             # real seconds the cutaway plays
SLOWMO_SCALE = 0.25        # sim-time multiplier while the cam is up

# ------------------------------------------------------------------ timeline
T_BEAT = 0.45              # freeze beat: tracer flies in, world holds breath
T_ENTRY_FLASH = 0.25       # entry star/ring fade time
T_PATH = 0.50              # interior path grows entry -> detonation
T_FAN = 0.30               # fragment fan extends
T_STAGGER = 0.14           # per-module flash / feed-line stagger
T_FLASH = 0.15             # white -> state-color ease per module

# ------------------------------------------------- palette (research doc §G)
_BG = (0.02, 0.03, 0.05, 0.93)
_GHOST = (0.54, 0.59, 0.63)            # #8A97A0 cool steel ghost hull
_GHOST_FILL_A = 0.16
_MOD_FINE = (0.42, 0.47, 0.51, 0.95)   # neutral steel (solid guts)
_MOD_EDGE = (0.60, 0.66, 0.72)
_ST_LIGHT = (0.95, 0.78, 0.27)         # #F2C744 light damage
_ST_DAMAGED = (0.94, 0.54, 0.14)       # #F08A24 damaged
_ST_CRIPPLED = (0.89, 0.23, 0.18)      # #E23B2E crippled / dead this hit
_ST_CHARRED = (0.11, 0.11, 0.12)       # #1B1B1E destroyed (older hits)
_AMMO_TINT = (0.72, 0.55, 0.22, 0.95)  # warm: the eye jumps to hazards
_FUEL_TINT = (0.37, 0.55, 0.35, 0.95)  # #5FA05A olive fuel block
_PATH_PEN = (0.36, 0.88, 0.42)         # #5BE06A penetrator line
_PATH_STOP = (0.89, 0.23, 0.18)        # stopped-at-plate red
_TRACER = (1.0, 1.0, 1.0)
_FRAG = (1.0, 0.85, 0.35)
_WATER = (0.16, 0.38, 0.55, 0.30)
_INK = (0.92, 0.90, 0.86)
_MUTED = (0.55, 0.55, 0.55)
_ACCENT = (1.0, 0.62, 0.2)
_KILL = (1.0, 0.25, 0.15)
_FLOOD = (0.16, 0.45, 0.85)
_FIRE = (1.0, 0.55, 0.10)

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

_KIND_VERB = {
    "propulsion": "TARGET SLOWING",
    "sensors": "RADAR BLINDED",
    "vls": "MISSILE CELLS DESTROYED",
    "magazine": "MAGAZINE WRECKED",
    "c2": "COMMAND DEGRADED",
    "fire": "FUEL FEEDING THE FIRE",
    "aviation": "HANGAR BURNING",
}

_Y_TOP = 1.4               # grid vertical ceiling (masthead)
_Y_BOT = -1.0              # keel


class HitCam:
    """Owns the current cutaway snapshot + the animation clock."""

    def __init__(self, state):
        self.state = state
        self.snap: dict | None = None
        self.left = 0.0
        self.enabled = True

    # ------------------------------------------------------------- control

    @property
    def active(self) -> bool:
        return self.snap is not None and self.left > 0.0

    @property
    def t(self) -> float:
        """Seconds into the playback."""
        return HITCAM_S - self.left

    def notify(self, snap: dict) -> None:
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
        t = self.t
        text.draw_rect(0, 0, w, h, _BG)

        # Layout: two stacked views left (share the z axis), feed right.
        px = int(w * 0.055)
        pw = int(w * 0.58)
        side_y = int(h * 0.17)
        side_h = int(h * 0.40)
        top_y = side_y + side_h + int(h * 0.045)
        top_h = int(h * 0.185)

        title = f"HIT - {_SHIP_NAMES.get(s['ship_type'], s['ship_type'].upper())}"
        text.draw_text(px, int(h * 0.055), title, _ACCENT, 28)
        sub = (f"{s['weapon'].upper()}  {s['ke'] / 1e6:.0f} MJ  "
               + ("PENETRATED HULL" if s["penetrated"]
                  else "STOPPED AT THE PLATE"))
        text.draw_text(px, int(h * 0.10), sub, _INK, 18)
        text.draw_text(px, side_y - 20, "SIDE VIEW", _MUTED, 14)
        text.draw_text(px, top_y - 20, "PLAN VIEW", _MUTED, 14)

        anim = self._anim_state(s, t)
        self._side_view(text, s, anim, px, side_y, pw, side_h)
        self._top_view(text, s, anim, px, top_y, pw, top_h)
        self._feed(text, s, anim, px + pw + int(w * 0.045), side_y, w, h)

        text.draw_text(px, int(h * 0.92),
                       "X-RAY HIT CAM - TIME SLOWED  (ESC TO DISMISS)",
                       _MUTED, 14)

    # ------------------------------------------------------- animation math

    @staticmethod
    def _anim_state(s, t: float) -> dict:
        """Where the playback clock sits: tracer progress, path progress,
        fan progress, and each new-dead module's flash age."""
        tracer = min(1.0, t / T_BEAT)
        path = 0.0 if t < T_BEAT else min(1.0, (t - T_BEAT) / T_PATH)
        fan_t0 = T_BEAT + T_PATH
        fan = 0.0 if t < fan_t0 else min(1.0, (t - fan_t0) / T_FAN)
        flashes = {}
        for i, name in enumerate(s.get("new_dead", ())):
            t_i = fan_t0 + T_FAN * 0.4 + i * T_STAGGER
            flashes[name] = None if t < t_i else min(1.0, (t - t_i) / T_FLASH)
        n_feed = sum(1 for v in flashes.values() if v is not None)
        return {"tracer": tracer, "path": path, "fan": fan,
                "flashes": flashes, "entry_age": max(0.0, t - T_BEAT),
                "boom": s.get("catastrophe") and t >= fan_t0,
                "n_feed": n_feed, "t": t}

    def _module_color(self, s, anim, name: str, kind: str):
        """The state-color LAW: steel -> yellow -> orange -> red -> charred;
        new kills flash white then ease to red on their ray's frame."""
        col = self._module_color_raw(s, anim, name, kind)
        if kind == "fire":                  # fuel wash stays a wash even
            return (*col[:3], min(col[3], 0.35))   # when burnt/charred
        return col

    def _module_color_raw(self, s, anim, name: str, kind: str):
        flash = anim["flashes"].get(name)
        if name in s.get("new_dead", ()):
            if flash is None:               # its ray has not landed yet
                return self._kind_tint(kind)
            if flash < 1.0:                 # white -> crippled-red ease
                k = flash
                return (1.0 - (1.0 - _ST_CRIPPLED[0]) * k,
                        1.0 - (1.0 - _ST_CRIPPLED[1]) * k,
                        1.0 - (1.0 - _ST_CRIPPLED[2]) * k, 1.0)
            return (*_ST_CRIPPLED, 1.0)
        if name in s.get("all_dead", ()):   # destroyed in an EARLIER hit
            return (*_ST_CHARRED, 0.97)
        dose = s.get("dose", {}).get(name, 0.0)
        tough = s.get("toughness", {}).get(name, 1.0e9)
        r = dose / tough if tough > 0 else 0.0
        if r >= 0.66:
            return (*_ST_DAMAGED, 0.95)
        if r >= 0.25:
            return (*_ST_LIGHT, 0.95)
        return self._kind_tint(kind)

    @staticmethod
    def _kind_tint(kind: str):
        if kind in ("vls", "magazine"):
            return _AMMO_TINT               # hazards read warm at a glance
        if kind == "fire":
            # Fuel spans half the hull: a faint wash, never a solid mass
            # that buries the machinery drawn inside its footprint.
            return (*_FUEL_TINT[:3], 0.28)
        return _MOD_FINE

    @staticmethod
    def _draw_order(grid):
        """Large boxes first so small ones stay visible on top (the fuel
        bunkers span half the hull and must never bury an engine room)."""
        def area(row):
            _n, z0, z1, y0, y1, xh, _k = row
            return (z1 - z0) * (min(y1, _Y_TOP) - max(y0, _Y_BOT)) * xh
        return sorted(grid, key=area, reverse=True)

    # ------------------------------------------------------------ side view

    def _side_view(self, text, s, anim, px, py, pw, ph) -> None:
        def X(z):
            return px + z * pw

        def Y(y):
            return py + (_Y_TOP - y) / (_Y_TOP - _Y_BOT) * ph

        wl, keel, deck = Y(0.0), Y(_Y_BOT), Y(0.18)
        text.draw_rect(px - 10, wl, pw + 20, py + ph - wl + 10, _WATER)

        # Ghost hull: frosted shell + raked bow + deck sheer.
        hull = [(X(0.0), deck), (X(0.86), deck), (X(1.0), Y(0.30)),
                (X(1.0), wl), (X(0.965), keel), (X(0.02), keel),
                (X(0.0), Y(-0.6)), (X(0.0), deck)]
        text.draw_rect(X(0.0), deck, X(0.97) - X(0.0), keel - deck,
                       (*_GHOST, _GHOST_FILL_A))
        text.draw_lines(hull, (*_GHOST, 0.95), 2.0)
        text.draw_lines([(px - 10, wl), (px + pw + 10, wl)],
                        (0.5, 0.75, 0.95, 0.8), 1.2)

        # Flooding bins (under the modules).
        flood = s.get("flood", ())
        n = max(1, len(flood))
        for i, level in enumerate(flood):
            if level <= 0.005:
                continue
            top = keel + (wl - keel) * min(1.0, level)
            text.draw_rect(X(i / n) + 2, top, X((i + 1) / n) - X(i / n) - 4,
                           keel - top, (*_FLOOD, 0.30 + 0.45 * min(1.0, level)))

        # Fire glow (under the modules).
        fire = float(s.get("fire", 0.0))
        if fire > 0.03 and anim["path"] >= 1.0:
            fz = float(s.get("fire_z", 0.5))
            half = 0.05 + 0.09 * fire
            flick = 0.85 + 0.15 * math.sin(anim["t"] * 9.0)
            text.draw_rect(X(max(0.0, fz - half)), deck - 6,
                           X(min(1.0, fz + half)) - X(max(0.0, fz - half)),
                           keel - deck + 6,
                           (*_FIRE, (0.12 + 0.20 * fire) * flick))

        # Solid module boxes (largest first: guts stay visible).
        for row in self._draw_order(s["grid"]):
            name, z0, z1, y0, y1, _xh, kind = row
            x0, x1 = X(z0), X(z1)
            yt, yb = Y(min(y1, _Y_TOP)), Y(max(y0, _Y_BOT))
            col = self._module_color(s, anim, name, kind)
            text.draw_rect(x0 + 1, yt + 1, max(2, x1 - x0 - 2),
                           max(2, yb - yt - 2), col)
            edge = (_ST_CRIPPLED if name in s.get("all_dead", ())
                    else _MOD_EDGE)
            text.draw_lines([(x0, yt), (x1, yt), (x1, yb), (x0, yb),
                             (x0, yt)], (*edge, 0.85), 1.0)

        # Shot path in this projection: z on X, grid-y on Y.
        e = s.get("entry", s.get("impact", (0.5, 0.0, 0.0)))
        d = s.get("det", e)
        self._shot(text, s, anim,
                   (X(e[0]), Y(self._cl(e[1]))),
                   (X(d[0]), Y(self._cl(d[1]))), pw)

        if anim["boom"]:
            # Detonation burst: white core, hot ring, long radial rays —
            # reads as a blast, not a smear (research §C HE alternative).
            bx, by = X(d[0]), Y(self._cl(d[1]))
            r = pw * 0.085
            text.draw_rect(bx - r * 0.35, by - r * 0.35, r * 0.7, r * 0.7,
                           (1.0, 0.95, 0.85, 0.9))
            for ang in range(0, 360, 20):
                c = math.cos(math.radians(ang))
                sn = math.sin(math.radians(ang))
                text.draw_lines([(bx + c * r * 0.4, by + sn * r * 0.4),
                                 (bx + c * r * 2.2, by + sn * r * 2.2)],
                                (1.0, 0.55, 0.15, 0.75), 2.0)

    # ------------------------------------------------------------- top view

    def _top_view(self, text, s, anim, px, py, pw, ph) -> None:
        def X(z):
            return px + z * pw

        def Y(xf):                          # beam fraction -1..1 -> screen
            return py + (1.0 - xf) * 0.5 * ph

        # Plan hull: parallel mid-body, pointed bow, chamfered stern.
        hull = [(X(0.02), Y(0.72)), (X(0.72), Y(0.78)), (X(1.0), Y(0.0)),
                (X(0.72), Y(-0.78)), (X(0.02), Y(-0.72)), (X(0.0), Y(-0.5)),
                (X(0.0), Y(0.5)), (X(0.02), Y(0.72))]
        text.draw_rect(X(0.0), Y(0.8), pw, Y(-0.8) - Y(0.8),
                       (*_GHOST, _GHOST_FILL_A * 0.8))
        text.draw_lines(hull, (*_GHOST, 0.95), 2.0)

        for row in self._draw_order(s["grid"]):
            name, z0, z1, _y0, _y1, xh, kind = row
            x0, x1 = X(z0), X(z1)
            yt, yb = Y(xh), Y(-xh)
            col = self._module_color(s, anim, name, kind)
            text.draw_rect(x0 + 1, yt + 1, max(2, x1 - x0 - 2),
                           max(2, yb - yt - 2), col)

        e = s.get("entry", s.get("impact", (0.5, 0.0, 0.0)))
        d = s.get("det", e)
        self._shot(text, s, anim,
                   (X(e[0]), Y(max(-1.0, min(1.0, e[2])))),
                   (X(d[0]), Y(max(-1.0, min(1.0, d[2])))), pw,
                   fan=False)

    @staticmethod
    def _cl(y):
        return max(_Y_BOT, min(_Y_TOP, y))

    # ------------------------------------------------- shot path + frag fan

    def _shot(self, text, s, anim, p_entry, p_det, pw, fan=True) -> None:
        ex, ey = p_entry
        dx_, dy_ = p_det[0] - ex, p_det[1] - ey
        seg = math.hypot(dx_, dy_)
        if seg < 1e-6:
            ux, uy = -1.0, 0.0
            dx_, dy_ = 0.0, 0.0
        else:
            ux, uy = dx_ / seg, dy_ / seg

        # Incoming tracer during the beat: a bright head flying at the hull.
        if anim["tracer"] < 1.0:
            run = pw * 0.30
            sx, sy = ex - ux * run, ey - uy * run
            k = anim["tracer"]
            hx, hy = sx + (ex - sx) * k, sy + (ey - sy) * k
            text.draw_lines([(hx - ux * 26, hy - uy * 26), (hx, hy)],
                            (*_TRACER, 0.9), 2.0)
            text.draw_rect(hx - 2, hy - 2, 4, 4, (*_TRACER, 1.0))
            return

        # Entry flash: hot star + fading ring.
        age = anim["entry_age"]
        if age < T_ENTRY_FLASH:
            a = 1.0 - age / T_ENTRY_FLASH
            r = 6 + 26 * (age / T_ENTRY_FLASH)
            for ang in range(0, 360, 45):
                c, sn = math.cos(math.radians(ang)), math.sin(
                    math.radians(ang))
                text.draw_lines([(ex, ey), (ex + c * r, ey + sn * r)],
                                (*_TRACER, a), 1.5)
        text.draw_rect(ex - 3, ey - 3, 6, 6, (*_ACCENT, 1.0))

        # Interior path (green = through the hull; red = stopped).
        col = _PATH_PEN if s["penetrated"] else _PATH_STOP
        k = anim["path"]
        if k > 0.0 and seg > 1e-6:
            mx, my = ex + dx_ * k, ey + dy_ * k
            text.draw_lines([(ex, ey), (mx, my)], (*col, 0.95), 2.5)
            text.draw_rect(mx - 2.5, my - 2.5, 5, 5, (*_TRACER, 0.9))
        if not s["penetrated"] and k >= 1.0:
            # Non-pen: red splash at the plate, no interior damage rays.
            text.draw_rect(p_det[0] - 5, p_det[1] - 5, 10, 10,
                           (*_PATH_STOP, 0.85))
            return

        # Fragment fan from the detonation node, +/-22 deg forward cone.
        if fan and anim["fan"] > 0.0 and s["penetrated"]:
            nx, ny = p_det
            text.draw_rect(nx - 3, ny - 3, 6, 6, (*_FIRE, 1.0))
            base = math.atan2(uy, ux)
            reach = pw * max(0.06, min(0.16, s.get("blast_frac", 0.08)))
            n_rays = 12
            for i in range(n_rays):
                f = (i / (n_rays - 1)) * 2.0 - 1.0      # -1..1 across cone
                ang = base + math.radians(22.0) * f
                ln = reach * (0.55 + 0.45 * (1.0 - abs(f))) * anim["fan"]
                text.draw_lines(
                    [(nx, ny), (nx + math.cos(ang) * ln,
                                ny + math.sin(ang) * ln)],
                    (*_FRAG, 0.75 * (1.0 - 0.4 * abs(f))), 1.2)

    # ------------------------------------------------------------- the feed

    def _feed(self, text, s, anim, x0, y0, w, h) -> None:
        y = y0
        lh = int(h * 0.042)

        def line(msg, col=_INK, size=18):
            nonlocal y
            text.draw_text(x0, y, msg, col, size)
            y += lh

        # Damage feed: one line per killed module, appearing with its flash.
        new_dead = list(s.get("new_dead", ()))
        kinds = s.get("kinds", {})
        shown = anim["n_feed"]
        for name in new_dead[:shown]:
            line(_MODULE_LABELS.get(name, name.upper()) + " - DESTROYED",
                 _ST_CRIPPLED)
            verb = _KIND_VERB.get(kinds.get(name, ""), "")
            if verb:
                line("   " + verb, _INK, 14)
        if not new_dead and anim["path"] >= 1.0:
            line("SUPERFICIAL DAMAGE" if not s.get("penetrated")
                 else "NO CRITICAL SYSTEMS HIT", _MUTED)

        if anim["path"] >= 1.0:
            if s.get("breach_m2", 0.0) > 0.05:
                line(f"HULL BREACH {s['breach_m2']:.1f} m2 - FLOODING",
                     _FLOOD[:3])
            if s.get("fire", 0.0) > 0.05:
                line(f"FIRE ONBOARD - {int(s['fire'] * 100)}%", _FIRE[:3])
            if s.get("dead_in_water"):
                line("TARGET DEAD IN THE WATER", _KILL)
            # Buoyancy proxy: how much reserve the flooding has eaten.
            flood = s.get("flood", ())
            if flood:
                buoy = max(0.0, 1.0 - sum(flood) / len(flood))
                bw, bh = int(w * 0.16), 8
                y += 6
                text.draw_text(x0, y, f"BUOYANCY {int(buoy * 100)}%",
                               _INK, 14)
                y += lh - 6
                text.draw_rect(x0, y, bw, bh, (0.2, 0.24, 0.3, 0.9))
                bcol = _FLOOD if buoy > 0.45 else (0.9, 0.3, 0.2)
                text.draw_rect(x0, y, bw * buoy, bh, (*bcol, 1.0))
                y += lh

        if anim["boom"]:
            y += lh // 2
            line("MAGAZINE DETONATION", _KILL, 28)
            line("SHIP IS LOST", _KILL, 28)
