"""Telemetry overlay (HUD): flight block, launcher block, camera/controls
hint line and the terminal target bracket.

Pure screen-space layout on top of ``engine.text.TextRenderer`` — this
module issues only draw_text / draw_rect / draw_lines calls (no direct GL),
so it imports headless. World points are projected with the same camera
matrices the renderer computed for the frame (proj @ view_rot @
camera-relative position), exactly like the scene pass.
"""

from __future__ import annotations

import numpy as np

from engine.text import BODY_SIZE, HEADER_SIZE
from sim.arsenal import BASTION, ONIKS, S300, S300_TEL
from sim.physics import mach
from world.generation import BASE_POS, SAM_SITE_POS

# Phase text comes from the missiles' duck-typed ``phase_label`` property
# (Task S4): Missile and SamMissile phase enums reuse the same int values,
# so the HUD never compares raw phase ints across classes.

# --- Layout tuning -------------------------------------------------------------

MARGIN = 12                 # px, panel offset from the top-left corner
PANEL_W = 268               # px, telemetry panel width
PANEL_PAD = 10              # px, inner padding of panels
LINE_H = 22                 # px, row pitch of the telemetry block
VALUE_X = 104               # px, label -> value column offset inside the panel
HEADER_GAP = 6              # px, extra gap under the header line
HINT_MARGIN = 10            # px, hint line offset from the bottom edge

PANEL_RGBA = (0.03, 0.06, 0.05, 0.55)        # translucent dark panel fill
LABEL_COL = (0.60, 0.72, 0.64, 1.0)          # muted green-gray labels
VALUE_COL = (0.92, 0.97, 0.92, 1.0)          # near-white values
HEADER_COL = (0.95, 0.85, 0.45, 1.0)         # amber headline
ARMED_COL = (0.45, 1.00, 0.55, 1.0)          # status green
RELOAD_COL = (1.00, 0.72, 0.25, 1.0)         # status amber
TERMINAL_COL = (1.00, 0.55, 0.40, 1.0)       # TERMINAL phase pops red-ish
HINT_COL = (0.85, 0.90, 0.85, 0.92)          # bottom hint text

# Target bracket: 4 corner L's sized with the locked ship's on-screen extent.
BRACKET_COL = (1.0, 0.36, 0.24, 0.95)
BRACKET_SIZE_FACTOR = 0.65  # bracket half-size = ship length * this (in px)
BRACKET_MIN_PX = 18.0       # px, never collapses below this
BRACKET_MAX_PX = 220.0      # px, never engulfs the screen
BRACKET_CORNER_FRAC = 0.38  # corner leg length as a fraction of the half-size
BRACKET_LINE_W = 2.0        # px stroke
BRACKET_TEXT_GAP = 6.0      # px between the bracket and the range text

CONTROLS_HINT = ("TAB platform  C cam  M map  SPACE launch  1/2 profile  "
                 "P pause  N step  -/= time  F2 shot  ESC menu")


def world_to_screen(sandbox, pos_f64, w: float, h: float):
    """Project a world point to screen pixels with this frame's matrices.

    Returns (x, y) with origin top-left, or None when the point is at/behind
    the camera plane.
    """
    renderer = sandbox.renderer
    rel = sandbox.camera.rel(pos_f64)
    clip = renderer.proj @ renderer.view_rot @ np.array(
        [rel[0], rel[1], rel[2], 1.0])
    if clip[3] <= 1e-9:
        return None
    inv = 1.0 / clip[3]
    return ((clip[0] * inv * 0.5 + 0.5) * w,
            (1.0 - (clip[1] * inv * 0.5 + 0.5)) * h)


def _fmt_clock(t: float) -> str:
    """Sim clock as MM:SS, growing to H:MM:SS past an hour."""
    t = max(0.0, float(t))
    hh, rem = divmod(int(t), 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"


def _missile_target_pos(m):
    """Duck-typed aim point: locked ship (Oniks terminal) > target aircraft
    (SamMissile) > planned target point."""
    ship = getattr(m, "locked_ship", None)
    if ship is not None:
        return ship.pos
    tgt = getattr(m, "target", None)
    if tgt is not None:
        return tgt.pos
    return m.target_point


def _bracket_target(m):
    """The entity the corner bracket frames: the Oniks' locked ship, or the
    SAM's target aircraft once the terminal seeker (truth) is tracking it."""
    ship = getattr(m, "locked_ship", None)
    if ship is not None:
        return ship
    tgt = getattr(m, "target", None)
    if (tgt is not None and m.phase_label == "TERMINAL"
            and getattr(tgt, "alive", False)):
        return tgt
    return None


class HUD:
    """Draws the sandbox telemetry overlay through a shared TextRenderer."""

    def __init__(self, text):
        self.text = text

    # ------------------------------------------------------------------ draw

    def draw(self, sandbox, w: int, h: int) -> None:
        """Queue and flush the full overlay for this frame."""
        m = sandbox.followed
        if m is not None and not getattr(m, "alive", False):
            m = None
        if m is not None:
            self._flight_block(sandbox, m)
            tgt = _bracket_target(m)
            if tgt is not None:
                self._target_bracket(sandbox, m, tgt, w, h)
        else:
            self._launcher_block(sandbox)
        self._hint_flash(sandbox, w, h)
        self._camera_line(sandbox, w, h)
        self.text.flush(w, h)

    # ---------------------------------------------------------------- blocks

    def _block(self, header: str, rows) -> None:
        """Panel at the top-left: header + (label, value, color) rows."""
        head_h = self.text.line_height(HEADER_SIZE)
        height = PANEL_PAD * 2 + head_h + HEADER_GAP + len(rows) * LINE_H
        self.text.draw_rect(MARGIN, MARGIN, PANEL_W, height, PANEL_RGBA)
        tx = MARGIN + PANEL_PAD
        ty = MARGIN + PANEL_PAD
        self.text.draw_text(tx, ty, header, HEADER_COL, HEADER_SIZE)
        ty += head_h + HEADER_GAP
        for label, value, col in rows:
            self.text.draw_text(tx, ty + 2, label, LABEL_COL)
            self.text.draw_text(tx + VALUE_X, ty + 2, value, col)
            ty += LINE_H

    def _flight_block(self, sandbox, m) -> None:
        """In-flight telemetry for the followed missile (Oniks or SAM)."""
        speed = float(np.linalg.norm(m.vel))
        alt = float(m.pos[1])
        tgt = _missile_target_pos(m)
        rng_km = float(np.hypot(tgt[0] - m.pos[0], tgt[2] - m.pos[2])) / 1e3
        label = m.phase_label
        phase_col = TERMINAL_COL if label == "TERMINAL" else VALUE_COL
        rows = [
            ("PHASE", label, phase_col),
            ("MACH", f"{float(mach(speed, alt)):.2f}", VALUE_COL),
            ("ALT", f"{alt:,.0f} m", VALUE_COL),
            ("SPD", f"{speed:,.0f} m/s", VALUE_COL),
            ("RNG", f"{rng_km:,.1f} km", VALUE_COL),
        ]
        fuel = getattr(m, "fuel", None)
        if fuel is not None:                # ramjet sustainer fuel
            rows.append(("FUEL", f"{100.0 * fuel / m.weapon.fuel_mass:.0f}%",
                         VALUE_COL))
        else:                               # solid motor propellant (SAM)
            rows.append(("PROP",
                         f"{100.0 * m.propellant / m.weapon.propellant_mass:.0f}%",
                         VALUE_COL))
        rows += [
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(sandbox.world.sim_time), VALUE_COL),
        ]
        self._block(m.weapon.display_name.upper(), rows)

    def _launcher_block(self, sandbox) -> None:
        """Active platform's launcher status while nothing is followed."""
        if sandbox.active_platform == "s300":
            self._s300_block(sandbox)
        else:
            self._bastion_block(sandbox)

    def _bastion_block(self, sandbox) -> None:
        world = sandbox.world
        if world.launcher_armed:
            status, col = "ARMED", ARMED_COL
        else:
            # Epsilon: fixed-step decrements leave reload_left ~1e-13 above
            # the exact second, which would ceil one second too high.
            status = f"RELOADING {int(np.ceil(world.reload_left - 1e-9))} s"
            col = RELOAD_COL
        rows = [
            ("STATUS", status, col),
            ("WEAPON", ONIKS.display_name.upper(), VALUE_COL),
            ("PROFILE", sandbox.profile.upper(), VALUE_COL),
            ("TARGET", self._target_summary(sandbox, BASE_POS), VALUE_COL),
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        self._block(BASTION.display_name.upper(), rows)

    def _s300_block(self, sandbox) -> None:
        world = sandbox.world
        if world.sam_ammo <= 0:
            status, col = "EMPTY", RELOAD_COL
        elif world.sam_launcher_armed:
            status, col = "ARMED", ARMED_COL
        else:
            status = ("RELOADING "
                      f"{int(np.ceil(world.sam_reload_left - 1e-9))} s")
            col = RELOAD_COL
        rows = [
            ("STATUS", status, col),
            ("WEAPON", S300.display_name.upper(), VALUE_COL),
            ("AMMO", f"{world.sam_ammo}/{S300_TEL.ammo}", VALUE_COL),
            ("TARGET", self._target_summary(sandbox, SAM_SITE_POS),
             VALUE_COL),
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        self._block(S300_TEL.display_name.upper(), rows)

    @staticmethod
    def _target_summary(sandbox, origin) -> str:
        tp = sandbox.target_point
        if tp is None:
            return "none"
        dx = float(tp[0]) - origin[0]
        dz = float(tp[2]) - origin[2]
        brg = int(round(np.degrees(np.arctan2(dx, dz)))) % 360
        return f"BRG {brg:03d}  {np.hypot(dx, dz) / 1e3:.0f} km"

    @staticmethod
    def _scale_text(sandbox) -> str:
        eff = sandbox.effective_time_scale()
        txt = f"x{eff:g}"
        if eff != sandbox.controls.requested_scale:
            txt += " (launch)"      # accel locked to 1x during EJECT/BOOST
        return txt

    # ------------------------------------------------------------- hint line

    def _hint_flash(self, sandbox, w: int, h: int) -> None:
        """Transient one-line hint (e.g. 'S-300: SELECT AIR TARGET') above
        the camera/controls line, while sandbox.hint_left > 0."""
        if sandbox.hint_left <= 0.0 or not sandbox.hint_text:
            return
        lh = self.text.line_height(BODY_SIZE)
        tw = self.text.text_width(sandbox.hint_text)
        x = (w - tw) * 0.5
        y = h - 2.0 * (lh + HINT_MARGIN) - 12.0
        self.text.draw_rect(x - 10, y - 4, tw + 20, lh + 8, PANEL_RGBA)
        self.text.draw_text(x, y, sandbox.hint_text, RELOAD_COL)

    def _camera_line(self, sandbox, w: int, h: int) -> None:
        """Bottom-center: camera mode + controls hint."""
        line = f"CAM {sandbox.rig.mode.upper()}    {CONTROLS_HINT}"
        tw = self.text.text_width(line)
        lh = self.text.line_height(BODY_SIZE)
        x = (w - tw) * 0.5
        y = h - lh - HINT_MARGIN
        self.text.draw_rect(x - 10, y - 4, tw + 20, lh + 8, PANEL_RGBA)
        self.text.draw_text(x, y, line, HINT_COL)

    # -------------------------------------------------------- target bracket

    def _target_bracket(self, sandbox, m, target, w: int, h: int) -> None:
        """4 corner lines around the tracked target (ship hull or aircraft)
        + missile range text. Sized by the target's largest extent."""
        center = (np.asarray(target.pos, dtype=np.float64)
                  + np.array([0.0, getattr(target, "height", 0.0) * 0.5,
                              0.0]))
        pt = world_to_screen(sandbox, center, w, h)
        if pt is None:
            return
        x, y = pt
        dist = float(np.linalg.norm(center - sandbox.camera.eye))
        px_per_m = ((h * 0.5)
                    / (np.tan(sandbox.camera.fov_y * 0.5) * max(dist, 1.0)))
        extent = max(target.length, getattr(target, "wingspan", 0.0))
        half = float(np.clip(extent * BRACKET_SIZE_FACTOR * px_per_m,
                             BRACKET_MIN_PX, BRACKET_MAX_PX))
        if (x < -half or x > w + half or y < -half or y > h + half):
            return
        leg = half * BRACKET_CORNER_FRAC
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                cx, cy = x + sx * half, y + sy * half
                self.text.draw_lines(
                    [(cx - sx * leg, cy), (cx, cy), (cx, cy - sy * leg)],
                    BRACKET_COL, BRACKET_LINE_W)
        rng_m = float(np.linalg.norm(np.asarray(target.pos, dtype=np.float64)
                                     - m.pos))
        label = f"{rng_m / 1e3:.1f} km"
        self.text.draw_text(x - self.text.text_width(label) * 0.5,
                            y + half + BRACKET_TEXT_GAP, label, BRACKET_COL)
