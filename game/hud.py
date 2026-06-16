"""Telemetry overlay (HUD): flight block, launcher block, corner micro-
labels, the F1 controls overlay and the terminal target bracket.

Task UI (normative: docs/research/ui_reference.md §4): the permanent
bottom hint bar is REMOVED — the entire resting footprint is a bottom-right
``F1 CONTROLS`` micro-label with the bare camera-mode text stacked above
it. F1 toggles a centered overlay generated live from the binding table
(so it can never lie after a rebind); contextual one-liners (COMMITTED,
S-300: SELECT AIR TARGET) keep the existing hint_flash mechanism. The
telemetry panel gains the menu language's chrome: 1px border, amber corner
ticks and the header rule.

Pure screen-space layout on top of ``engine.text.TextRenderer`` — this
module issues only draw_text / draw_rect / draw_lines calls (no direct GL),
so it imports headless. World points are projected with the same camera
matrices the renderer computed for the frame (proj @ view_rot @
camera-relative position), exactly like the scene pass.
"""

from __future__ import annotations

import numpy as np

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.keybinds import ACTIONS
from game.states import (ACCENT_DIM, BG0, MUTED, TEXT_COL, draw_header_rule,
                         draw_panel)
from sim.arsenal import BASTION, N40N6, N40N6_AMMO, ONIKS, S300, S300_TEL
from sim.physics import mach
from sim.recon import RWR_LOCK
from world.generation import BASE_POS, SAM_SITE_POS

# Phase text comes from the missiles' duck-typed ``phase_label`` property
# (Task S4): Missile and SamMissile phase enums reuse the same int values,
# so the HUD never compares raw phase ints across classes.

# --- Layout tuning -------------------------------------------------------------

MARGIN = 16                 # px, panel offset from the top-left corner (8px grid)
PANEL_W = 268               # px, telemetry panel width
PANEL_PAD = 16              # px, inner padding of panels (spec §1.5)
LINE_H = 24                 # px, row pitch of the telemetry block (8px grid)
VALUE_X = 104               # px, label -> value column offset inside the panel
HEADER_GAP = 12             # px, gap under the header rule
HINT_MARGIN = 10            # px, hint line offset from the bottom edge
CORNER_MARGIN = 16          # px, bottom-right micro-label inset (spec §4.1)
CAM_LABEL_GAP = 24          # px, camera-mode text stacked above F1 CONTROLS
PANEL_ALPHA = 0.55          # HUD panel fill alpha (menus use 0.92)

PANEL_RGBA = (0.043, 0.078, 0.071, 0.55)     # translucent dark panel fill
LABEL_COL = (0.60, 0.72, 0.64, 1.0)          # muted green-gray labels
VALUE_COL = (0.92, 0.97, 0.92, 1.0)          # near-white values
HEADER_COL = (0.95, 0.85, 0.45, 1.0)         # amber headline
ARMED_COL = (0.45, 1.00, 0.55, 1.0)          # status green
RELOAD_COL = (1.00, 0.72, 0.25, 1.0)         # status amber
TERMINAL_COL = (1.00, 0.55, 0.40, 1.0)       # TERMINAL phase pops red-ish
DANGER_COL = (1.00, 0.36, 0.24, 1.0)         # destroyed / defeat (states.py DANGER)

# COMBAT Phase 3: radar-silence readout + the lose-condition banner.
# Phase 5b adds the mirrored win banner (spec 2.2: all enemy ships + the
# airfield destroyed — world/combat.py ``victorious``).  Defeat outranks
# victory if both somehow latch in one frame (losing the Bastion is final).
RADAR_EMITTING = "EMITTING"
RADAR_SILENT = "SILENT"
RADAR_DESTROYED = "DESTROYED"
DEFEAT_TEXT = "BASTION DESTROYED - DEFEAT"
VICTORY_TEXT = "ENEMY FORCE DESTROYED - VICTORY"
DEFEAT_Y_FRAC = 0.24        # banner center height as a fraction of the screen
DEFEAT_PAD_X = 28           # px panel padding around the banner text
DEFEAT_PAD_Y = 18

F1_LABEL = "F1 CONTROLS"    # the HUD's entire permanent hint footprint
OVERLAY_W = 460             # px, F1 overlay panel width
OVERLAY_ROW_H = 24          # px, overlay binding-row pitch
OVERLAY_DIM = 24            # px, dim-rect margin around the overlay panel
OVERLAY_FOOTER = "F1 CLOSE   REBIND IN SETTINGS"

# Target bracket: 4 corner L's sized with the locked ship's on-screen extent.
BRACKET_COL = (1.0, 0.36, 0.24, 0.95)
BRACKET_SIZE_FACTOR = 0.65  # bracket half-size = ship length * this (in px)
BRACKET_MIN_PX = 18.0       # px, never collapses below this
BRACKET_MAX_PX = 220.0      # px, never engulfs the screen
BRACKET_CORNER_FRAC = 0.38  # corner leg length as a fraction of the half-size
BRACKET_LINE_W = 2.0        # px stroke
BRACKET_TEXT_GAP = 6.0      # px between the bracket and the range text


def radar_status_row(world):
    """The COMBAT radar-emissions row for the launcher blocks, or None when
    the session world has no radar station (SANDBOX) — pure, unit-testable.
    Returns ("RADAR", status, color)."""
    radar = getattr(world, "radar_station", None)
    if radar is None:
        return None
    if not radar.alive:
        return ("RADAR", RADAR_DESTROYED, DANGER_COL)
    if radar.emitting:
        return ("RADAR", RADAR_EMITTING, ARMED_COL)
    return ("RADAR", RADAR_SILENT, RELOAD_COL)


def pantsir_status_row(world, engaging: bool = False):
    """The COMBAT Pantsir point-defense summary row for the ground-launcher
    blocks, or None when the session world fields no Pantsirs (SANDBOX, or a
    COMBAT setup with PANTSIR_COUNT 0) — pure, unit-testable.

    Returns ``("PANTSIR", text, color)`` where text is either
    ``"n UP  M<missiles> G<guns>"`` (alive-unit count + pooled 57E6 and
    30 mm ammo across the LIVE units), ``"ENGAGING"`` (amber flash latched
    for a short window after any unit launches — see CombatState), or
    ``"DOWN"`` (red, every Pantsir destroyed)."""
    units = getattr(world, "pantsirs", None)
    if not units:
        return None
    alive = [u for u in units if u.alive]
    if not alive:
        return ("PANTSIR", "DOWN", DANGER_COL)
    if engaging:
        return ("PANTSIR", "ENGAGING", RELOAD_COL)
    missiles = sum(u.missile_ammo for u in alive)
    guns = sum(u.gun_ammo for u in alive)
    return ("PANTSIR", f"{len(alive)} UP  M{missiles} G{guns}", ARMED_COL)


def oniks_ammo_row(world):
    """The COMBAT Oniks magazine row for the Bastion launcher block, or None
    when the Oniks magazine is infinite (SANDBOX — ``_oniks_ammo`` is None) —
    pure, unit-testable.

    Returns ``("AMMO", text, color)`` where text is ``"<n>/<cap>"`` (green
    while rounds remain), or ``"0/<cap> RLDG <s>s"`` (amber, magazine empty
    and the refill timer running — the renewable-but-rate-limited armory
    mechanic, world/world.py ``_arm_magazines``)."""
    ammo = getattr(world, "_oniks_ammo", None)
    if ammo is None:
        return None                         # sandbox: infinite, no row
    cap = getattr(world, "_oniks_mag_cap", ammo)
    if ammo > 0:
        return ("AMMO", f"{ammo}/{cap}", ARMED_COL)
    # Empty: surface the refill countdown so the player knows when it returns.
    left = getattr(world, "_oniks_mag_reload_left", 0.0)
    return ("AMMO", f"0/{cap} RLDG {int(np.ceil(left - 1e-9))}s", RELOAD_COL)


def drone_panel_rows(world) -> list[tuple]:
    """The recon-drone platform's panel rows (Phase 4) — pure, GL-free,
    unit-testable. (label, value, color) tuples:

      STATUS   AIRBORNE / DOWN (red)
      RESPAWN  countdown, only while down
      ALT/SPD  flight telemetry, only while up
      SENSORS  'ELINT n' heard-emitter count + 'SAR UP'
      RWR      highest-priority alert: 'LOCK brg' (red) > 'SPIKE brg'
               (amber) > 'CLEAR' (green)
    """
    drone = getattr(world, "drone", None)
    if drone is None or not drone.alive:
        left = getattr(world, "drone_respawn_left", 0.0)
        return [
            ("STATUS", "DOWN", DANGER_COL),
            ("RESPAWN", f"{int(np.ceil(left - 1e-9))} s", RELOAD_COL),
        ]
    speed = float(np.hypot(drone.vel[0], drone.vel[2]))
    rows = [
        ("STATUS", "AIRBORNE", ARMED_COL),
        ("ALT", f"{drone.pos[1]:,.0f} m", VALUE_COL),
        ("SPD", f"{speed:,.0f} m/s", VALUE_COL),
        ("SENSORS",
         f"ELINT {len(world.elint.heard_emitters())}  SAR UP", VALUE_COL),
    ]
    alerts = world.rwr.alerts()
    if alerts:
        level, brg = alerts[0]              # LOCK sorts before SPIKE
        col = DANGER_COL if level == RWR_LOCK else RELOAD_COL
        rows.append(("RWR", f"{level} {int(round(brg)) % 360:03d}", col))
    else:
        rows.append(("RWR", "CLEAR", ARMED_COL))
    return rows


def s300_round_panel(world, sam_round: str):
    """S-300 readout with the Phase-5b round select — pure, unit-testable
    (shared by the HUD panel and the tactical-map strip).

    Returns ``(status, color, weapon_name, ammo_text)``: status reflects
    the SELECTED round's readiness (its own stock + the shared tube
    reload timer — both rounds index through the same 5P85 reload cycle,
    world/world.py launch_sam doc); ammo_text always shows BOTH stocks so
    the player sees the whole magazine at a glance.
    """
    if sam_round == "40n6":
        ammo = world.sam_ammo_40n6
        armed = world.sam_40n6_launcher_armed
        name = N40N6.display_name.upper()
    else:
        ammo = world.sam_ammo
        armed = world.sam_launcher_armed
        name = S300.display_name.upper()
    if ammo <= 0:
        status, col = "EMPTY", RELOAD_COL
    elif armed:
        status, col = "ARMED", ARMED_COL
    else:
        # Epsilon: fixed-step decrements leave the timer ~1e-13 above the
        # exact second, which would ceil one second too high.
        status = f"RELOADING {int(np.ceil(world.sam_reload_left - 1e-9))} s"
        col = RELOAD_COL
    ammo_text = (f"48N6 {world.sam_ammo}/{S300_TEL.ammo} "
                 f"40N6 {world.sam_ammo_40n6}/{N40N6_AMMO}")
    return status, col, name, ammo_text


def overlay_rows(keybinds) -> list[tuple]:
    """F1 overlay rows from the LIVE binding table: ("header", group) and
    ("row", label, key_name) in registry order — pure, unit-testable."""
    rows: list[tuple] = []
    group = None
    for a in ACTIONS:
        if a.group != group:
            group = a.group
            rows.append(("header", group))
        rows.append(("row", a.label, keybinds.name_for(a.id)))
    return rows


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
    (SamMissile) > planned target point (Oniks) > target_x/z (enemy strike).
    Returns None when the round exposes no aim point (e.g. a HARM riding a
    radar bearing) so callers degrade instead of crashing."""
    ship = getattr(m, "locked_ship", None)
    if ship is not None:
        return ship.pos
    tgt = getattr(m, "target", None)
    if tgt is not None:
        return tgt.pos
    tp = getattr(m, "target_point", None)
    if tp is not None:
        return tp
    tx = getattr(m, "target_x", None)
    if tx is not None:
        return np.array([tx, getattr(m, "target_y", 0.0),
                         getattr(m, "target_z", 0.0)], dtype=np.float64)
    return None


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
        # The camera subject may be a TEL StaticSubject or a ship/aircraft
        # entity (Task CAM [ / ] cycling): only a live missile (the only
        # subject kind with a phase_label) gets the flight block.
        if m is not None and not (getattr(m, "alive", False)
                                  and hasattr(m, "phase_label")):
            m = None
        if m is not None:
            self._flight_block(sandbox, m)
            tgt = _bracket_target(m)
            if tgt is not None:
                self._target_bracket(sandbox, m, tgt, w, h)
        else:
            self._launcher_block(sandbox)
        if getattr(sandbox.world, "defeated", False):
            self._banner(w, h, DEFEAT_TEXT, DANGER_COL)
        elif getattr(sandbox.world, "victorious", False):
            self._banner(w, h, VICTORY_TEXT, ARMED_COL)
        self._hint_flash(sandbox, w, h)
        self._corner_labels(sandbox, w, h)
        if sandbox.controls_overlay:
            self._controls_overlay(sandbox, w, h)
        self.text.flush(w, h)

    def draw_flight_block(self, sandbox, m) -> None:
        """Queue (no flush) the flight telemetry block for ``m``: the
        tactical map calls this for the LMB-selected round (Task RTG) so its
        telemetry shows in the same HUD flight block while the map is open."""
        self._flight_block(sandbox, m)

    # ---------------------------------------------------------------- blocks

    def _block(self, header: str, rows) -> None:
        """Panel at the top-left: header + rule + (label, value, color)
        rows, in the menu language's chrome (border + amber corner ticks)."""
        head_h = self.text.line_height(HEADER_SIZE)
        height = (PANEL_PAD * 2 + head_h + 4 + HEADER_GAP
                  + len(rows) * LINE_H)
        draw_panel(self.text, MARGIN, MARGIN, PANEL_W, height,
                   alpha=PANEL_ALPHA)
        tx = MARGIN + PANEL_PAD
        ty = MARGIN + PANEL_PAD
        self.text.draw_text(tx, ty, header, HEADER_COL, HEADER_SIZE)
        ty += head_h + 4
        draw_header_rule(self.text, tx, ty, PANEL_W - 2 * PANEL_PAD)
        ty += HEADER_GAP
        for label, value, col in rows:
            self.text.draw_text(tx, ty + 2, label, LABEL_COL)
            self.text.draw_text(tx + VALUE_X, ty + 2, value, col)
            ty += LINE_H

    def _flight_block(self, sandbox, m) -> None:
        """In-flight telemetry for the followed missile (Oniks or SAM)."""
        speed = float(np.linalg.norm(m.vel))
        alt = float(m.pos[1])
        tgt = _missile_target_pos(m)
        rng_km = (float(np.hypot(tgt[0] - m.pos[0], tgt[2] - m.pos[2])) / 1e3
                  if tgt is not None else None)
        label = m.phase_label
        phase_col = TERMINAL_COL if label == "TERMINAL" else VALUE_COL
        rows = [
            ("PHASE", label, phase_col),
            ("MACH", f"{float(mach(speed, alt)):.2f}", VALUE_COL),
            ("ALT", f"{alt:,.0f} m", VALUE_COL),
            ("SPD", f"{speed:,.0f} m/s", VALUE_COL),
            ("RNG", f"{rng_km:,.1f} km" if rng_km is not None else "---",
             VALUE_COL),
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
        if sandbox.active_platform == "drone":
            self._drone_block(sandbox)
        elif sandbox.active_platform == "s300":
            self._s300_block(sandbox)
        else:
            self._bastion_block(sandbox)

    def _drone_block(self, sandbox) -> None:
        """Recon-drone platform panel (Phase 4): flight/sensor/RWR rows
        from the pure helper, plus the shared TIME/CLOCK footer."""
        world = sandbox.world
        rows = drone_panel_rows(world)
        rows += [
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        self._block("RECON DRONE", rows)

    def _bastion_block(self, sandbox) -> None:
        world = sandbox.world
        if getattr(world, "defeated", False):
            # COMBAT lose condition: the TEL structure is rubble — the
            # launcher can never arm again (world.launch returns None).
            status, col = "DESTROYED", DANGER_COL
        elif world.launcher_armed:
            status, col = "ARMED", ARMED_COL
        else:
            # Epsilon: fixed-step decrements leave reload_left ~1e-13 above
            # the exact second, which would ceil one second too high.
            status = f"RELOADING {int(np.ceil(world.reload_left - 1e-9))} s"
            col = RELOAD_COL
        rows = [
            ("STATUS", status, col),
            ("WEAPON", ONIKS.display_name.upper(), VALUE_COL),
        ]
        ammo = oniks_ammo_row(world)        # COMBAT magazine; None in sandbox
        if ammo is not None:
            rows.append(ammo)
        rows += [
            ("PROFILE", sandbox.profile.upper(), VALUE_COL),
            ("TARGET", self._target_summary(sandbox, BASE_POS), VALUE_COL),
        ]
        radar = radar_status_row(world)
        if radar is not None:
            rows.append(radar)
        pantsir = pantsir_status_row(
            world, engaging=getattr(sandbox, "pantsir_engaging", False))
        if pantsir is not None:
            rows.append(pantsir)
        rows += [
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        self._block(BASTION.display_name.upper(), rows)

    def _s300_block(self, sandbox) -> None:
        world = sandbox.world
        sam_round = getattr(sandbox, "sam_round", "48n6")
        status, col, name, ammo_text = s300_round_panel(world, sam_round)
        rows = [
            ("STATUS", status, col),
            ("WEAPON", name, VALUE_COL),
            ("AMMO", ammo_text, VALUE_COL),
            ("TARGET", self._target_summary(sandbox, SAM_SITE_POS),
             VALUE_COL),
        ]
        radar = radar_status_row(world)
        if radar is not None:
            rows.append(radar)
        pantsir = pantsir_status_row(
            world, engaging=getattr(sandbox, "pantsir_engaging", False))
        if pantsir is not None:
            rows.append(pantsir)
        rows += [
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
            txt += " (launch)"      # accel locked to 1x through the cinematic
        return txt

    def _banner(self, w: int, h: int, text: str, color) -> None:
        """COMBAT outcome banner (spec 2.2 — DEFEAT red / VICTORY green):
        a centered corner-ticked panel in the menu chrome over the
        still-running sim — the player watches the aftermath; full
        end-screens come in Phase 7."""
        lh = self.text.line_height(HEADER_SIZE)
        tw = self.text.text_width(text, HEADER_SIZE)
        x = (w - tw) * 0.5
        y = h * DEFEAT_Y_FRAC - lh * 0.5
        draw_panel(self.text, x - DEFEAT_PAD_X, y - DEFEAT_PAD_Y,
                   tw + 2 * DEFEAT_PAD_X, lh + 2 * DEFEAT_PAD_Y, alpha=0.92)
        self.text.draw_text(x, y, text, color, HEADER_SIZE)

    # ----------------------------------------------- hints + corner labels

    def _hint_flash(self, sandbox, w: int, h: int) -> None:
        """Transient state-driven one-liner (e.g. 'S-300: SELECT AIR
        TARGET'), bottom-center, while sandbox.hint_left > 0 — the only
        panel-filled text left at the screen bottom."""
        if sandbox.hint_left <= 0.0 or not sandbox.hint_text:
            return
        lh = self.text.line_height(BODY_SIZE)
        tw = self.text.text_width(sandbox.hint_text)
        x = (w - tw) * 0.5
        y = h - 2.0 * (lh + HINT_MARGIN) - 12.0
        self.text.draw_rect(x - 10, y - 4, tw + 20, lh + 8, PANEL_RGBA)
        self.text.draw_text(x, y, sandbox.hint_text, RELOAD_COL)

    def _corner_labels(self, sandbox, w: int, h: int) -> None:
        """Bottom-right, no panel fill (spec §4.1): the 'F1 CONTROLS'
        micro-label with the bare camera-mode readout stacked above it."""
        lh = self.text.line_height(SMALL_SIZE)
        y = h - CORNER_MARGIN - lh
        tw = self.text.text_width(F1_LABEL, SMALL_SIZE)
        self.text.draw_text(w - CORNER_MARGIN - tw, y, F1_LABEL, ACCENT_DIM,
                            SMALL_SIZE)
        cam = f"CAM {sandbox.rig.mode.upper()}"
        cw = self.text.text_width(cam, SMALL_SIZE)
        self.text.draw_text(w - CORNER_MARGIN - cw, y - CAM_LABEL_GAP, cam,
                            MUTED, SMALL_SIZE)

    def _controls_overlay(self, sandbox, w: int, h: int) -> None:
        """F1: centered corner-ticked panel listing every binding straight
        from the live table (sim keeps running — overlay, not menu)."""
        text = self.text
        rows = overlay_rows(sandbox.app.keybinds)
        head_h = text.line_height(HEADER_SIZE)
        small_h = text.line_height(SMALL_SIZE)
        body_h = text.line_height(BODY_SIZE)
        content_h = len(rows) * OVERLAY_ROW_H
        panel_h = (PANEL_PAD * 2 + head_h + 4 + HEADER_GAP + content_h
                   + 8 + small_h)
        x = (w - OVERLAY_W) // 2
        y = (h - panel_h) // 2
        text.draw_rect(x - OVERLAY_DIM, y - OVERLAY_DIM,
                       OVERLAY_W + 2 * OVERLAY_DIM,
                       panel_h + 2 * OVERLAY_DIM, (*BG0, 0.35))
        draw_panel(text, x, y, OVERLAY_W, panel_h, alpha=0.92, strip=True)
        tx = x + PANEL_PAD
        ty = y + PANEL_PAD
        text.draw_text(tx, ty, "CONTROLS", HEADER_COL, HEADER_SIZE)
        ty += head_h + 4
        draw_header_rule(text, tx, ty, OVERLAY_W - 2 * PANEL_PAD)
        ty += HEADER_GAP
        for row in rows:
            if row[0] == "header":
                text.draw_text(tx, ty + (OVERLAY_ROW_H - small_h) // 2,
                               row[1], ACCENT_DIM, SMALL_SIZE)
            else:
                _, label, key = row
                oy = ty + (OVERLAY_ROW_H - body_h) // 2
                text.draw_text(tx, oy, label, MUTED)
                kw = text.text_width(key)
                text.draw_text(x + OVERLAY_W - PANEL_PAD - kw, oy, key,
                               TEXT_COL)
            ty += OVERLAY_ROW_H
        fw = text.text_width(OVERLAY_FOOTER, SMALL_SIZE)
        text.draw_text(x + (OVERLAY_W - fw) // 2, ty + 8, OVERLAY_FOOTER,
                       ACCENT_DIM, SMALL_SIZE)

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
        extent = max(getattr(target, "length", 0.0),
                     getattr(target, "wingspan", 0.0))
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
