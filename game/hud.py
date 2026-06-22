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

from collections import namedtuple

import numpy as np

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.hud_widgets import badge as _badge
from game.hud_widgets import gauge_bar as _hud_gauge_bar
from game.keybinds import ACTIONS
from game.timewarp import drop_cause
from game.states import (ACCENT, ACCENT_DIM, BG0, DANGER, MUTED, OK_COL,
                         SEMANTIC_COLORS, TEXT_COL, WARN, draw_header_rule,
                         draw_panel)
from game.states import gauge_bar as _gauge_bar
from game.states import mini_compass as _mini_compass
from sim.arsenal import (BASTION, BUK_AGILE, BUK_LONG, BUK_TEL, N40N6,
                         N40N6_AMMO, ONIKS, S300, S300_TEL)
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
EMISSIONS_GAUGE_GAP_Y = 8   # px gap below the (data-driven) panel bottom where
#                             the EMCON gauge sits — anchored off the panel's
#                             real height, never a fixed offset from the top
EMISSIONS_GAUGE_H = 6       # px gauge bar height (compact own-emissions strip)
EMISSIONS_GAUGE_GAP = 8     # px between the EMCON caption and the bar
EMISSIONS_PCT_W = 34        # px reserved for the right-aligned percent readout

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

# --- Threat-warning strip + contact-intel panel (M1) ---------------------------
#
# FOG OF WAR / NO CHEAT (load-bearing): both pure helpers below read ONLY the
# sensor-gated contact picture (world.contacts.tracks + estimated_pos). They
# NEVER touch world.missiles, a real entity .pos/.alive, or any truth — an
# undetected hostile (in flight but not yet on the board) does not appear, and
# CLASS/kind come from the track's is_air + size + kind stamps (M1-F2), never
# the real entity. They are deterministic (no RNG) and GL-free; the DRAW
# methods that consume them compose the M1-F1 widget primitives.

TTI_CRIT_S = 20.0           # time-to-impact below this reads DANGER (red)
TTI_WARN_S = 60.0           # ... below this reads WARN (amber); else MUTED
CLOSING_EPS = 1.0           # m/s: a track closing slower than this has no TTI
STRIP_W = 180               # px, threat-strip column width

# Sensor-confidence ladder for the intel panel (track age in seconds):
AGE_IDENTIFIED_S = 5.0      # fresher than this -> IDENTIFIED (a live fix)
AGE_CLASSIFIED_S = 20.0     # fresher than this -> CLASSIFIED; else UNKNOWN
CONFIDENCE_FADE_S = 25.0    # linear confidence fade: 1.0 fresh -> 0.0 here on
#                             (so a brand-new fix reads >= 0.8, the panel's
#                             "high confidence" band, well before AGE_CLASSIFIED)

# Player weapons NEVER appear on the threat strip — this allowlist holds only
# the enemy-launched rounds the player must react to (Tomahawk/JASSM land-attack,
# HARM anti-radiation, SM-2/SM-6 area SAMs, AIM-9X fighter A2A, plus Kalibr for
# forward-compatibility). The player's own kinds (oniks/zircon/s300/40n6/
# pantsir_57e6) are deliberately absent, so a friendly round can never light up
# the strip even if a future code path stamps one onto the contact board.
HOSTILE_KINDS = frozenset({"sm2", "sm6", "tomahawk", "jassm", "harm",
                           "aim9x", "kalibr"})

# Severity token -> palette color (no hard-coded RGB at the strip call site;
# these are the states.py palette tokens, the same ones SEMANTIC_COLORS routes
# INBOUND/DESTROYED -> DANGER and TRANSIENT -> WARN through).
SEVERITY_COLORS = {"DANGER": DANGER, "WARN": WARN, "MUTED": MUTED}

# A single fog-pierced inbound row: sid (track id), kind (weapon_id stamp),
# brg (compass deg from the friendly asset to the estimate), rng (ground-plane
# metres), tti (seconds, or None when not closing) and severity (a SEMANTIC
# state token: DANGER / WARN / MUTED).
ThreatRow = namedtuple("ThreatRow", "sid kind brg rng tti severity")

STRIP_MARGIN = 16           # px, strip inset from the right/top screen edges
STRIP_ROW_H = 22            # px, threat-strip row pitch
STRIP_PULSE_HZ = 2.0        # critical-row pulse frequency (sin breathing)
STRIP_PULSE_LO = 0.55       # min alpha of the critical-row pulse
STRIP_PULSE_HI = 1.0        # max alpha of the critical-row pulse

# Docked contact-intel panel layout (composes draw_panel + gauge_bar + compass).
INTEL_W = 240               # px, intel-panel width
INTEL_PAD = 12              # px, inner padding
INTEL_LINE_H = 20           # px, label/value row pitch
INTEL_VALUE_X = 92          # px, label -> value column offset
INTEL_COMPASS_R = 22.0      # px, bearing-rose radius
INTEL_GAUGE_H = 8           # px, confidence gauge height

# --- Per-tube battery status row (M1-F4) ----------------------------------------
#
# OWN-FORCE TELEMETRY (load-bearing): ``tube_cells`` reads ONLY the world's own
# launcher/magazine attributes (_oniks_tubes / _s300_tubes + the reload totals +
# the ammo pools). It NEVER touches contacts / enemy / truth, and renders in the
# green/amber/disabled OWN idiom (READY/RELOADING/EMPTY via SEMANTIC_COLORS),
# never the CONTACT estimate idiom. Deterministic, GL-free, no RNG.
TUBE_CELL_W = 44            # px, width of one tube badge+gauge cell
TUBE_GAP = 6                # px, horizontal gap between adjacent tube cells
TUBE_ROW_GAP = 6            # px, gap between the panel body and the tube row
TUBE_GAUGE_H = 6            # px, height of a RELOADING cell's progress gauge
TUBE_LABEL_GAP = 2          # px, gap between a tube's index label and its badge

# --- Expanded per-battery STATUS PANEL board (M6) -------------------------------
#
# The full-screen-ish board (O) drawn like the F1 overlay: one ROW per player
# battery (name + pooled magazine on the left, the tube badges on the right),
# from the pure ``battery_status_rows`` helper.  Player-only own-force telemetry,
# EXEMPT from the radar gate; no enemy / contact / truth read.
BPANEL_W = 460              # px, board panel width (matches the F1 overlay feel)
BPANEL_DIM = 24             # px, dim-rect margin around the board
BPANEL_ROW_H = 40           # px, per-battery row pitch (name + tube badges)
BPANEL_NAME_W = 132         # px, battery-name + pool column width
BPANEL_TITLE = "BATTERY STATUS"
BPANEL_FOOTER = "O CLOSE"
BPANEL_EMPTY = "NO PLAYER BATTERIES"     # SANDBOX / no finite-battery world


def _clamp01(v: float) -> float:
    """Clamp ``v`` into [0, 1] (local copy so the helper stays GL-free)."""
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else float(v)


def tube_cells(world, platform):
    """Per-tube READY / RELOADING / EMPTY readout for the active launcher
    (M1-F4) — pure, GL-free, deterministic, OWN-FORCE ONLY.

    ``platform`` in {'bastion', 'oniks'} selects the Oniks ``_oniks_tubes``
    battery; 's300' selects the ``_s300_tubes`` battery. Any other platform, or
    a SANDBOX world missing the tube attribute, returns ``[]`` (mirroring the
    None-guard idiom of ``oniks_ammo_row`` / ``s300_round_panel``).

    Each cell is ``(label, state, frac)``: ``label`` is the 1-based tube index
    as a string ("1", "2", ...); ``state`` is a SEMANTIC token (READY /
    RELOADING / EMPTY); ``frac`` is the reload-progress fraction in [0, 1]
    (1.0 ready, 0.0 empty, strictly between while reloading).

      Oniks tube: reload_left > 0 -> RELOADING (frac = 1 - reload_left/total);
        elif loaded -> READY (1.0); else -> EMPTY (0.0).
      S-300 tube (no 'loaded' key): reload_left > 0 -> RELOADING; elif EITHER
        round pool (48N6 + 40N6) has stock -> READY (1.0); else -> EMPTY (0.0).
    """
    if platform in ("bastion", "oniks"):
        tubes = getattr(world, "_oniks_tubes", None)
        if tubes is None:
            return []
        total = float(getattr(world, "_oniks_tube_reload_s", 0.0))
        cells = []
        for i, t in enumerate(tubes):
            left = float(t.get("reload_left", 0.0))
            if left > 0.0:
                frac = _clamp01(1.0 - left / total) if total > 0.0 else 0.0
                cells.append((str(i + 1), "RELOADING", frac))
            elif t.get("loaded"):
                cells.append((str(i + 1), "READY", 1.0))
            else:
                cells.append((str(i + 1), "EMPTY", 0.0))
        return cells
    if platform == "s300":
        tubes = getattr(world, "_s300_tubes", None)
        if tubes is None:
            return []
        total = float(getattr(world, "_s300_tube_reload_s", 0.0))
        # READY when EITHER round pool can chamber a round: both 48N6 and 40N6
        # cycle through the same 5P85 tube (s300_round_panel doc), so a tube
        # with stock in either magazine is loadable.
        have_round = (getattr(world, "sam_ammo", 0)
                      + getattr(world, "sam_ammo_40n6", 0)) > 0
        cells = []
        for i, t in enumerate(tubes):
            left = float(t.get("reload_left", 0.0))
            if left > 0.0:
                frac = _clamp01(1.0 - left / total) if total > 0.0 else 0.0
                cells.append((str(i + 1), "RELOADING", frac))
            elif have_round:
                cells.append((str(i + 1), "READY", 1.0))
            else:
                cells.append((str(i + 1), "EMPTY", 0.0))
        return cells
    if platform == "buk":
        tubes = getattr(world, "_buk_tubes", None)
        if not tubes:
            return []                       # n_buk=0 / SANDBOX -> unchanged
        total = float(getattr(world, "_buk_tube_reload_s", 0.0))
        # READY when EITHER Buk round pool can chamber (9M317 + 9M338 share the
        # 9A317 tubes, like the S-300's 48N6/40N6).
        have_round = (getattr(world, "buk_9m317_ammo", 0)
                      + getattr(world, "buk_9m338_ammo", 0)) > 0
        cells = []
        for i, t in enumerate(tubes):
            left = float(t.get("reload_left", 0.0))
            if left > 0.0:
                frac = _clamp01(1.0 - left / total) if total > 0.0 else 0.0
                cells.append((str(i + 1), "RELOADING", frac))
            elif have_round:
                cells.append((str(i + 1), "READY", 1.0))
            else:
                cells.append((str(i + 1), "EMPTY", 0.0))
        return cells
    return []


def tube_state(t, pool_has_round: bool = True) -> str:
    """Classify ONE physical launch tube as LOADED / RELOADING / EMPTY (M6) —
    pure, GL-free, deterministic, OWN-FORCE ONLY.

    ``t`` is a live tube dict (``_oniks_tubes`` / ``_s300_tubes`` entry).

      * An Oniks tube carries a ``loaded`` flag and its own ``reload_left``
        re-cock timer:
          reload_left > 0           -> RELOADING (the tube is re-cocking);
          loaded (and re-cocked)    -> LOADED;
          else                      -> EMPTY (re-cocked but the magazine had
                                       no round to feed it).
      * An S-300 tube has NO ``loaded`` key (its rounds come from the shared
        48N6/40N6 pool), so readiness depends on the POOL: the caller passes
        ``pool_has_round`` (does EITHER pool still hold a round):
          reload_left > 0           -> RELOADING;
          pool_has_round            -> LOADED;
          else                      -> EMPTY.

    The reload timer always outranks the loaded flag so a tube mid-cycle reads
    RELOADING even if a stale ``loaded`` flag lingers."""
    if float(t.get("reload_left", 0.0)) > 0.0:
        return "RELOADING"
    if "loaded" in t:                       # Oniks tube
        return "LOADED" if t.get("loaded") else "EMPTY"
    return "LOADED" if pool_has_round else "EMPTY"   # S-300 tube (pool-fed)


def battery_status_rows(world):
    """Per-battery STATUS PANEL data (M6) — pure, GL-free, deterministic,
    OWN-FORCE ONLY.  One dict per PLAYER firing battery (each Oniks TEL, each
    S-300 TEL), so the panel shows every physical tube of every battery the
    player commands at a glance.

    Returns ``[{name, tubes, pool_text, pool_col, refill_left}]`` where:
      * ``name``       battery label ("BASTION TEL 1", "S-300 TEL 1", ...);
      * ``tubes``      list of ``(state, reload_left)`` — state is a
                       :func:`tube_state` token, reload_left the per-tube
                       re-cock countdown (s, 0.0 when not reloading);
      * ``pool_text``  shared magazine readout ("<n>/<cap>" for Oniks; both
                       48N6/40N6 stocks for the S-300), or ``None`` when the
                       magazine is INFINITE (the SANDBOX world has no finite
                       pool — mirrors ``oniks_ammo_row`` returning None);
      * ``pool_col``   ARMED_COL while rounds remain, RELOAD_COL when dry;
      * ``refill_left`` magazine-refill countdown (s) while the pool is dry and
                       the armory is reloading it; 0.0 otherwise.

    FOG / NO-CHEAT: reads ONLY the world's own launcher/magazine attributes
    (_oniks_tubes / _s300_tubes grouped by the launcher-position count, the
    ammo pools, the reload timers).  It NEVER touches contacts / enemy /
    world.missiles truth.  A world without the tube structures (the SANDBOX
    WorldState) yields ``[]`` (no per-battery panel), exactly like ``tube_cells``
    / ``oniks_ammo_row`` degrade in the sandbox."""
    rows: list = []
    rows += _oniks_battery_rows(world)
    rows += _s300_battery_rows(world)
    return rows


def _group_tubes(tubes, n_launchers):
    """Split a FLAT tube list into per-launcher slices (Oniks: 2/TEL, S-300:
    4/TEL).  ``n_launchers`` is ``len(_*_launcher_positions)``; an unknown count
    (0/None) falls back to one slice so a malformed world never crashes."""
    n = max(1, int(n_launchers or 1))
    per = max(1, len(tubes) // n)
    return [tubes[i * per:(i + 1) * per] for i in range(n)]


def _oniks_battery_rows(world):
    """Per-Oniks-TEL battery dicts (FLAT _oniks_tubes grouped 2-per-TEL by the
    launcher-position count), or [] when the world has no Oniks battery (the
    SANDBOX WorldState)."""
    tubes = getattr(world, "_oniks_tubes", None)
    if not tubes:
        return []
    positions = getattr(world, "_oniks_launcher_positions", [])
    ammo = getattr(world, "_oniks_ammo", None)
    cap = getattr(world, "_oniks_mag_cap", ammo)
    if ammo is None:                        # infinite (SANDBOX): no pool readout
        pool_text, pool_col, refill_left = None, ARMED_COL, 0.0
    elif ammo > 0:
        pool_text, pool_col, refill_left = f"{ammo}/{cap}", ARMED_COL, 0.0
    else:
        refill_left = float(getattr(world, "_oniks_mag_reload_left", 0.0))
        pool_text, pool_col = f"0/{cap}", RELOAD_COL
    rows = []
    for i, slice_ in enumerate(_group_tubes(tubes, len(positions))):
        cells = [(tube_state(t), float(t.get("reload_left", 0.0)))
                 for t in slice_]
        rows.append({"name": f"BASTION TEL {i + 1}", "tubes": cells,
                     "pool_text": pool_text, "pool_col": pool_col,
                     "refill_left": refill_left})
    return rows


def _s300_battery_rows(world):
    """Per-S-300-TEL battery dicts (FLAT _s300_tubes grouped 4-per-TEL).  The
    48N6 + 40N6 pools are SHARED across every tube, so the pool readout and the
    LOADED/EMPTY tube decision use the combined stock.  [] when the world has no
    S-300 battery (the SANDBOX WorldState)."""
    tubes = getattr(world, "_s300_tubes", None)
    if not tubes:
        return []
    positions = getattr(world, "_s300_launcher_positions", [])
    ammo48 = int(getattr(world, "sam_ammo", 0))
    ammo40 = int(getattr(world, "sam_ammo_40n6", 0))
    pool_has_round = (ammo48 + ammo40) > 0
    pool_text = f"48N6 {ammo48}  40N6 {ammo40}"
    pool_col = ARMED_COL if pool_has_round else RELOAD_COL
    # When BOTH pools are dry the shared refill timer is the longer of the two
    # (each pool re-stocks on its own counter; the player reads the soonest the
    # battery is loadable again, i.e. the max remaining wait until any round
    # returns — surface the larger so the readout never under-promises).
    refill_left = 0.0
    if not pool_has_round:
        refill_left = max(
            float(getattr(world, "_s300_48n6_mag_reload_left", 0.0)),
            float(getattr(world, "_s300_40n6_mag_reload_left", 0.0)))
    rows = []
    for i, slice_ in enumerate(_group_tubes(tubes, len(positions))):
        cells = [(tube_state(t, pool_has_round=pool_has_round),
                  float(t.get("reload_left", 0.0))) for t in slice_]
        rows.append({"name": f"S-300 TEL {i + 1}", "tubes": cells,
                     "pool_text": pool_text, "pool_col": pool_col,
                     "refill_left": refill_left})
    return rows


def salvo_readout(sandbox):
    """SALVO HUD row (M6) — pure, GL-free, OWN-FORCE.  Shows the selected salvo
    mode (RIPPLE / FAN / TOT) and, while a ripple is queued, the progress
    'SALVO k/n' (rounds remaining).  Reads only the player's own salvo state on
    the sandbox; returns None when the sandbox carries no salvo queue (the
    legacy/smoke path) so the block is unchanged.

    Returns ``(label, value, col)``: amber while a salvo is in progress (a
    transient action cue), muted-green at rest (the resting mode selector)."""
    queue = getattr(sandbox, "_salvo", None)
    mode = getattr(sandbox, "salvo_mode", None)
    if queue is None or mode is None:
        return None
    mode_txt = mode.upper()
    if getattr(queue, "active", False):
        # count_left is the rounds STILL to fire; the first round already flew
        # through the single-fire path, so it is not counted in the queue total.
        left = int(getattr(queue, "count_left", 0))
        return ("SALVO", f"{mode_txt}  {left} QUEUED", RELOAD_COL)
    return ("SALVO", mode_txt, LABEL_COL)


def _ground_range(origin_xz, est) -> float:
    """Ground-plane (xz) distance from a friendly (x, z) asset to a 3D
    estimate ``est`` (x, y, z) — altitude is ignored (a TTI/threat is judged
    on the map plane)."""
    return float(np.hypot(est[0] - origin_xz[0], est[2] - origin_xz[1]))


def _compass_bearing(dx: float, dz: float) -> int:
    """Compass heading (deg, 0 = +z = North, clockwise) of the (dx, dz)
    ground vector, as an int in [0, 360)."""
    return int(round(np.degrees(np.arctan2(dx, dz)))) % 360


def _threat_severity(tti) -> str:
    """SEMANTIC state token for a time-to-impact: DANGER under TTI_CRIT_S,
    WARN under TTI_WARN_S, else MUTED (a None tti — not closing — is MUTED)."""
    if tti is None:
        return "MUTED"
    if tti < TTI_CRIT_S:
        return "DANGER"
    if tti < TTI_WARN_S:
        return "WARN"
    return "MUTED"


def threat_rows(world, friendly_xz, now) -> list:
    """The fog-pierced inbound board for the threat-warning strip (M1) — pure,
    GL-free, deterministic. Reads ONLY the gated contact picture
    (world.contacts.tracks + estimated_pos); NEVER world.missiles or truth.

    Keeps only air tracks whose weapon ``kind`` is in HOSTILE_KINDS (enemy
    rounds — friendly kinds and ship/fighter PLATFORM tracks are excluded), and
    for each computes ground-plane range + compass bearing from ``friendly_xz``
    to the dead-reckoned estimate, the closing speed (the component of the
    track velocity toward the asset) and the time-to-impact (rng / closing, or
    None when not closing). Sorted by (tti is None, tti, sid): soonest impact
    first, non-closing tracks last, ``sid`` as the deterministic tiebreak.
    """
    rows = []
    board = world.contacts
    for sid, track in board.tracks.items():
        if not (track.get("is_air") and track.get("kind") in HOSTILE_KINDS):
            continue
        est = board.estimated_pos(sid, now)
        ox, oz = float(friendly_xz[0]), float(friendly_xz[1])
        dx, dz = est[0] - ox, est[2] - oz          # asset -> track (for bearing)
        rng = float(np.hypot(dx, dz))
        brg = _compass_bearing(float(dx), float(dz))
        vel = track["vel"]
        # Closing speed = velocity projected onto the unit vector FROM the
        # track TOWARD the asset (positive => inbound). Degenerate range (track
        # on top of the asset) counts as closing 0 -> no TTI.
        if rng > CLOSING_EPS:
            ux, uz = -dx / rng, -dz / rng          # track -> asset, normalized
            closing = float(vel[0]) * ux + float(vel[2]) * uz
        else:
            closing = 0.0
        tti = rng / closing if closing > CLOSING_EPS else None
        rows.append(ThreatRow(sid=sid, kind=track.get("kind"), brg=brg,
                              rng=rng, tti=tti,
                              severity=_threat_severity(tti)))
    rows.sort(key=lambda r: (r.tti is None, r.tti if r.tti is not None else 0.0,
                             r.sid))
    return rows


def contact_intel(world, sid, origin_xz, now):
    """The fog-of-war track inspector for the click-contact intel panel (M1) —
    pure, GL-free, deterministic. None when ``sid`` is None or not on the board;
    else a dict of sensor-DERIVED fields (never truth):

      cls           'MISSILE' / 'AIR' / 'SURFACE', from size + is_air
      id            'IDENTIFIED' / 'CLASSIFIED' / 'UNKNOWN', by track age
      confidence    [0, 1] fading linearly with age (fresh >= 0.8)
      dead_reckoned True once age >= AGE_CLASSIFIED_S (the fix is coasting)
      brg, rng      compass bearing + ground-plane range from origin -> estimate
      course        compass heading of the track velocity
      speed         ground-plane speed (m/s)
      alt           estimated altitude (m, the estimate's y)
      kind, age     the raw track stamps (kind may be None for a platform)
      source        coarse sensor provenance ('RADAR' for a fresh fix that is
                    still being refreshed, 'COAST' once dead-reckoned) — derived
                    from the track, not truth
    """
    if sid is None:
        return None
    board = world.contacts
    track = board.tracks.get(sid)
    if track is None:
        return None
    est = board.estimated_pos(sid, now)
    age = float(track.get("age", 0.0))
    size = track.get("size")
    is_air = bool(track.get("is_air"))
    if size == "missile":
        cls = "MISSILE"
    elif is_air:
        cls = "AIR"
    else:
        cls = "SURFACE"
    if age < AGE_IDENTIFIED_S:
        ident = "IDENTIFIED"
    elif age < AGE_CLASSIFIED_S:
        ident = "CLASSIFIED"
    else:
        ident = "UNKNOWN"
    confidence = max(0.0, 1.0 - age / CONFIDENCE_FADE_S)
    dead_reckoned = age >= AGE_CLASSIFIED_S
    ox, oz = float(origin_xz[0]), float(origin_xz[1])
    dx, dz = est[0] - ox, est[2] - oz
    rng = float(np.hypot(dx, dz))
    brg = _compass_bearing(float(dx), float(dz))
    vel = track["vel"]
    speed = float(np.hypot(vel[0], vel[2]))
    course = _compass_bearing(float(vel[0]), float(vel[2]))
    return {
        "cls": cls,
        "id": ident,
        "confidence": confidence,
        "dead_reckoned": dead_reckoned,
        "brg": brg,
        "rng": rng,
        "course": course,
        "speed": speed,
        "alt": float(est[1]),
        "kind": track.get("kind"),
        "age": age,
        # A dead-reckoned track is no longer being painted by radar; before
        # that it is a live fix. Coarse, sensor-derived — never reads truth.
        "source": "COAST" if dead_reckoned else "RADAR",
    }


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


# M3-F5 EW legibility readouts. The burn-through km comes from the world's
# published ew_state (sim/ew.effective_range — the single source of truth); the
# row never recomputes physics. Below the close-in detection floor the net has
# effectively collapsed, so we read the red "NET DEGRADED" status rather than a
# misleadingly tiny range. The emissions-exposure meter weights the player's OWN
# loud emitters: an active search radar plus a HOT EW pod (own-truth, allowed)
# normalised to a 0..1 "how loud am I" gauge so the player can manage the
# back-plot risk of going active.
RADAR_BURN_THRU_FLOOR_M = 12_000.0   # below this the ring has collapsed (just
                                     # above sim/ew EW_CLOSE_FLOOR_M 8 km, so a
                                     # ring pinned to the floor reads DEGRADED)
EW_NET_DEGRADED = "NET DEGRADED"
# Exposure weights (dimensionless, sum to the 1.0 cap). A live search radar is
# the dominant back-plot emitter; the EW pod adds the rest. Tuned for legibility
# (radar-alone reads ~2/3 of the gauge), not an RF datum.
EXPOSURE_RADAR_W = 0.65
EXPOSURE_POD_W = 0.35
EXPOSURE_LABEL = "EMCON"             # the gauge caption (own emissions level)


def radar_jam_row(world):
    """The COMBAT radar burn-through row for the launcher blocks under enemy
    jamming, or None when no jammer is active (SANDBOX / the byte-identical
    default battle — world.ew_state inactive or absent) — pure, unit-testable.

    Reads ONLY world.ew_state (the sim's published EW summary; the burn-through
    km is sim/ew.effective_range, the single source of truth — never recomputed
    here). Returns:
      * ("RADAR", "BURN-THRU <km>km", amber) while the net still burns through
        at usable range (degraded but functional);
      * ("RADAR", "NET DEGRADED", red) once the ring has collapsed to the
        close-in floor (the jammer owns the picture)."""
    state = getattr(world, "ew_state", None)
    if not state or not state.get("active"):
        return None
    bt = state.get("burn_through_m")
    if bt is None or bt <= RADAR_BURN_THRU_FLOOR_M:
        return ("RADAR", EW_NET_DEGRADED, DANGER_COL)
    return ("RADAR", f"BURN-THRU {int(round(bt / 1e3))}km", RELOAD_COL)


def emissions_exposure(world):
    """The player's OWN emissions-loudness gauge (how loud the player currently
    is on the back-plot), or None when nothing the player owns is radiating
    (SANDBOX / silent radar + cold/unconfigured pod) — pure, unit-testable.

    OWN-TRUTH ONLY (allowed): reads the player's own radar_station.emitting and,
    when the EW pod is CONFIGURED (world._player_jammer) and the drone's pod is
    HOT (drone.jam_active on a live drone), the pod's contribution.  Returns
    ``(label, frac01, color)`` for gauge_bar; frac is the weighted 0..1 loudness
    (radar dominant, pod additive, capped at 1.0).  An unarmed pod (player_jammer
    off) is never counted even if a stale jam_active flag is set."""
    radar = getattr(world, "radar_station", None)
    if radar is None:
        return None
    frac = 0.0
    if getattr(radar, "alive", False) and getattr(radar, "emitting", False):
        frac += EXPOSURE_RADAR_W
    if getattr(world, "_player_jammer", False):
        drone = getattr(world, "drone", None)
        if (drone is not None and getattr(drone, "alive", False)
                and getattr(drone, "jam_active", False)):
            frac += EXPOSURE_POD_W
    if frac <= 0.0:
        return None                          # silent: no gauge to show
    frac = min(1.0, frac)
    # Amber while moderately lit, red once loud (the back-plot is wide open).
    col = DANGER_COL if frac >= 0.85 else RELOAD_COL
    return (EXPOSURE_LABEL, frac, col)


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


def swarm_status_row(world):
    """The COMBAT loitering-swarm pod row, or None when no pod is armed
    (SANDBOX, or a COMBAT setup with n_swarm_pods 0 -> _swarm_mag_cap 0) —
    pure, GL-free, unit-testable.

    Returns ``("SWARM", text, color)`` where text is:
      * ``"<cells>/<cap>  <inflight> UP"`` (green) — cells ready in the pod
        magazine + the count of swarm rounds currently in flight, or
      * ``"0/<cap> RLDG <s>s"`` (amber) — magazine empty and the refill timer
        running (the renewable-but-rate-limited pod mechanic)."""
    cap = getattr(world, "_swarm_mag_cap", 0)
    if not cap:
        return None
    cells = getattr(world, "_swarm_cells", 0)
    inflight = sum(1 for m in getattr(world, "missiles", [])
                   if getattr(getattr(m, "weapon", None), "weapon_id", None)
                   == "swarm" and getattr(m, "alive", False))
    if cells > 0:
        return ("SWARM", f"{cells}/{cap}  {inflight} UP", ARMED_COL)
    left = getattr(world, "_swarm_mag_reload_left", 0.0)
    return ("SWARM", f"0/{cap} RLDG {int(np.ceil(left - 1e-9))}s", RELOAD_COL)


def bastion_weapon_strip(sandbox, world) -> list:
    """The Bastion weapon-select strip (M2-T4) — pure, GL-free, unit-testable.

    Returns ``[(label, selected_bool, ammo_text)]`` for the rounds the Bastion
    TEL can chamber: ONIKS, ZIRCON, and (each only when its scarce pool is
    CONFIGURED) BASTION-K ASBM and KH-31P.  ``selected`` flags the active
    ``sandbox.oniks_weapon``.  Ammo text:
      * ONIKS  -> magazine ``"<n>/<cap>"`` (renewable, rate-limited);
      * ZIRCON / ASBM / KH-31P -> the scarce pool count ``"<n>"``.
    The ASBM row is OMITTED when ``_asbm_ammo`` is 0/None and the KH-31P row
    when ``_kh31p_ammo`` is 0/None, so the out-of-the-box Bastion strip is
    exactly the two-round ONIKS|ZIRCON list — matching the gated B cycle.
    Order mirrors the B cycle: ONIKS, ZIRCON, ASBM, KH-31P."""
    active = getattr(sandbox, "oniks_weapon", "oniks")
    oniks_ammo = getattr(world, "_oniks_ammo", None)
    oniks_cap = getattr(world, "_oniks_mag_cap", oniks_ammo)
    oniks_text = (f"{oniks_ammo}/{oniks_cap}" if oniks_ammo is not None
                  else "--")
    zircon = getattr(world, "_zircon_ammo", None)
    rows = [
        ("ONIKS",  active == "oniks",  oniks_text),
        ("ZIRCON", active == "zircon",
         str(int(zircon)) if zircon is not None else "--"),
    ]
    asbm = getattr(world, "_asbm_ammo", None)
    if asbm:                                 # configured pool (non-None, > 0)
        rows.append(("ASBM", active == "asbm", str(int(asbm))))
    arm = getattr(world, "_kh31p_ammo", None)
    if arm:                                  # configured pool (non-None, > 0)
        rows.append(("KH-31P", active == "kh31p", str(int(arm))))
    return rows


def arm_seeker_row(missile):
    """Seeker-state readout for a FOLLOWED player ARM (M2-T4) — pure, GL-free.

    Returns ``(label, color)`` for a live ``PlayerArmMissile`` mapping its OWN
    seeker state (reading the followed round's own attributes is allowed — no
    enemy truth):
      * LOCK       — target radar alive AND emitting, no miss offset (homing on
                     the live emission); SEMANTIC 'READY' green.
      * SILENT-CEP — a miss offset has been drawn (the radar went silent; the
                     round flies a seeded CEP basket); SEMANTIC 'RELOADING'
                     amber (degraded but still in flight).
      * MEMORY     — no miss offset and the target is NOT emitting: the round
                     coasts to the last-known position; SEMANTIC 'ESTIMATE'
                     (sensor-belief idiom, dimmer than friendly truth).
    Returns None for any non-ARM missile (no ``target_radar`` / not a
    PlayerArmMissile), so the flight block shows it only for the player ARM."""
    radar = getattr(missile, "target_radar", None)
    if radar is None or not hasattr(missile, "_miss_offset"):
        return None
    if getattr(missile, "_miss_offset", None) is not None:
        return ("SILENT-CEP", SEMANTIC_COLORS["RELOADING"])
    if getattr(radar, "alive", False) and getattr(radar, "emitting", False):
        return ("LOCK", SEMANTIC_COLORS["READY"])
    return ("MEMORY", SEMANTIC_COLORS["ESTIMATE"])


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
    # M3-F4 EW pod row — only when the pod is FITTED (world._player_jammer);
    # amber + a "POD HOT — DRONE LOUD" note while jamming (going loud deafens the
    # drone's own ELINT), green "OFF" when cold.  Absent entirely on an unfitted
    # drone so the default battle's panel is unchanged.
    if getattr(world, "_player_jammer", False):
        if getattr(drone, "jam_active", False):
            rows.append(("JAM", "ON  POD HOT - DRONE LOUD", RELOAD_COL))
        else:
            rows.append(("JAM", "OFF", ARMED_COL))
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


def buk_round_panel(world, buk_round: str):
    """M5 Buk readout with the round select (mirror of s300_round_panel) —
    pure, unit-testable (shared by the HUD panel and the tactical-map strip).

    Returns ``(status, color, weapon_name, ammo_text)``: status reflects the
    SELECTED round's readiness (its own pool + the shared tube reload), and
    ammo_text always shows BOTH pools so the player sees the whole magazine at
    a glance.  Reads the CombatWorld Buk state (buk_9m317_ammo / buk_9m338_ammo
    + the per-round launcher-armed gates)."""
    if buk_round == "9m338":
        ammo = world.buk_9m338_ammo
        armed = world.buk_9m338_launcher_armed
        name = BUK_AGILE.display_name.upper()
    else:
        ammo = world.buk_9m317_ammo
        armed = world.buk_9m317_launcher_armed
        name = BUK_LONG.display_name.upper()
    if ammo <= 0:
        status, col = "EMPTY", RELOAD_COL
    elif armed:
        status, col = "ARMED", ARMED_COL
    else:
        status, col = "RELOADING", RELOAD_COL
    ammo_text = (f"9M317 {world.buk_9m317_ammo}/{BUK_TEL.ammo} "
                 f"9M338 {world.buk_9m338_ammo}/{BUK_TEL.ammo}")
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
        self._threat_strip(sandbox, (BASE_POS[0], BASE_POS[2]), w, h)
        self._hint_flash(sandbox, w, h)
        self._corner_labels(sandbox, w, h)
        if getattr(sandbox, "battery_panel_open", False):
            self._battery_panel(sandbox, w, h)
        if sandbox.controls_overlay:
            self._controls_overlay(sandbox, w, h)
        self.text.flush(w, h)

    def draw_flight_block(self, sandbox, m) -> None:
        """Queue (no flush) the flight telemetry block for ``m``: the
        tactical map calls this for the LMB-selected round (Task RTG) so its
        telemetry shows in the same HUD flight block while the map is open."""
        self._flight_block(sandbox, m)

    # ---------------------------------------------------------------- blocks

    def _emissions_gauge(self, world, panel_bottom) -> None:
        """M3-F5 own-emissions meter: a small captioned gauge_bar showing how
        loud the player is on the back-plot (own radar + hot EW pod, own-truth).
        Drawn as a free overlay just below the telemetry panel; nothing renders
        when emissions_exposure returns None (silent / SANDBOX).

        ``panel_bottom`` is the platform block's actual bottom edge in px
        (MARGIN + the height _block returned for THIS frame's rows/tubes). The
        gauge anchors a fixed gap below it so it always clears the panel — even
        when the jam row makes the bastion block tall — instead of a magic
        offset from the panel top decoupled from the data-driven height."""
        out = emissions_exposure(world)
        if out is None:
            return
        label, frac, col = out
        # Anchor a fixed gap below the panel's real bottom — a compact, always-
        # legible strip; layout is screen-space only (no GL).
        gx = MARGIN + PANEL_PAD
        gy = panel_bottom + EMISSIONS_GAUGE_GAP_Y
        self.text.draw_text(gx, gy, label, LABEL_COL, SMALL_SIZE)
        cap_w = self.text.text_width(label, SMALL_SIZE)
        bar_x = gx + cap_w + EMISSIONS_GAUGE_GAP
        bar_w = PANEL_W - 2 * PANEL_PAD - cap_w - EMISSIONS_GAUGE_GAP \
            - EMISSIONS_PCT_W
        _hud_gauge_bar(self.text, bar_x, gy, max(bar_w, 1.0),
                       EMISSIONS_GAUGE_H, frac, col)
        self.text.draw_text(bar_x + max(bar_w, 1.0) + 4, gy,
                            f"{int(round(frac * 100))}%", col, SMALL_SIZE)

    def _block(self, header: str, rows, cells=None) -> None:
        """Panel at the top-left: header + rule + (label, value, color)
        rows, in the menu language's chrome (border + amber corner ticks).

        ``cells`` (M1-F4, optional) is a ``tube_cells`` list — per-tube
        (label, state, frac) own-force telemetry drawn as a badge row INSIDE
        the panel beneath the value rows, so it inherits the same chrome. An
        empty/None list adds nothing (SANDBOX: the block is unchanged)."""
        head_h = self.text.line_height(HEADER_SIZE)
        small_h = self.text.line_height(SMALL_SIZE)
        cell_h = small_h + 2 * 3.0      # badge body height (states.BADGE_PAD_Y)
        # The tube row reserves its own height inside the panel, mirroring the
        # stack drawn by _tube_cells_row: TUBE_ROW_GAP, the "TUBES" caption,
        # the per-tube index label, the state badge, the RELOADING gauge band,
        # plus a bottom margin so the badges sit fully inside the chrome.
        tube_band = 0
        if cells:
            tube_band = int(TUBE_ROW_GAP
                            + small_h + TUBE_LABEL_GAP     # "TUBES" caption
                            + small_h + TUBE_LABEL_GAP     # per-tube index
                            + cell_h                       # the state badge
                            + TUBE_GAUGE_H + 4             # RELOADING gauge band
                            + PANEL_PAD)                   # bottom margin
        height = (PANEL_PAD * 2 + head_h + 4 + HEADER_GAP
                  + len(rows) * LINE_H + tube_band)
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
        if cells:
            self._tube_cells_row(tx, ty + TUBE_ROW_GAP, cells)
        # The caller anchors the free-floating emissions gauge off the panel's
        # actual bottom (the height is fully data-driven by row/tube count), so
        # the gauge can never overlap a tall block (e.g. the jam-row-extended
        # bastion panel). MARGIN + height == the panel's bottom edge in px.
        return height

    def _tube_cells_row(self, x, y, cells) -> None:
        """Per-tube battery row (M1-F4): for each ``(label, state, frac)`` cell
        a small CAPS state badge (READY/RELOADING/EMPTY via SEMANTIC_COLORS, the
        own-force green/amber/disabled idiom) under its 1-based tube index, with
        a thin progress gauge beneath a RELOADING cell. OWN-FORCE only — no
        contact/enemy reads, no CONTACT_COL."""
        small_h = self.text.line_height(SMALL_SIZE)
        self.text.draw_text(x, y, "TUBES", LABEL_COL, SMALL_SIZE)
        y += small_h + TUBE_LABEL_GAP
        for i, (label, state, frac) in enumerate(cells):
            cx = x + i * (TUBE_CELL_W + TUBE_GAP)
            # Index label above the badge, then the state badge.
            self.text.draw_text(cx, y, label, MUTED, SMALL_SIZE)
            ly = y + small_h + TUBE_LABEL_GAP
            # badge(renderer, label, x, y, state): label is the CAPS text, state
            # routes the SEMANTIC color (both the state token here).
            _badge(self.text, state, cx, ly, state, size=SMALL_SIZE)
            # A RELOADING cell gets a progress gauge in its own (amber) color.
            if state == "RELOADING":
                gy = ly + self.text.line_height(SMALL_SIZE) + 2 * 3.0 + 2
                _hud_gauge_bar(self.text, cx, gy, TUBE_CELL_W, TUBE_GAUGE_H,
                               frac, SEMANTIC_COLORS["RELOADING"])

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
        ]
        # M2-T4: a followed player ARM gets a seeker-state row (LOCK /
        # SILENT-CEP / MEMORY) read off its OWN homing state; None (skipped)
        # for every non-ARM round, so the Oniks/SAM flight block is unchanged.
        seeker = arm_seeker_row(m)
        if seeker is not None:
            rows.append(("SEEKER", seeker[0], seeker[1]))
        rows += [
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
        elif sandbox.active_platform == "buk":
            self._buk_block(sandbox)
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
        height = self._block("RECON DRONE", rows)
        # M3-F5: the own-emissions gauge ALSO shows while flying the drone — the
        # platform where the EW pod is hot and the back-plot exposure is highest
        # (the pod is a primary EXPOSURE_POD_W contributor). Anchored below the
        # data-driven block bottom; None when silent -> nothing drawn.
        self._emissions_gauge(world, MARGIN + height)

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
        rows = [("STATUS", status, col)]
        # M2-T4: the Bastion weapon-select strip — one row per chamberable
        # round (ONIKS|ZIRCON, plus KH-31P only when the ARM pool is stocked),
        # the active one flagged with a '>' marker and accent colour, ammo
        # right-aligned in the value.  In the DEFAULT battle (ARM off, ONIKS
        # active) this renders the two-round strip; the ONIKS magazine row
        # still follows so the per-tube AMMO readout is unchanged.
        strip = bastion_weapon_strip(sandbox, world)
        for label, selected, ammo_text in strip:
            marker = "> " if selected else "  "
            wcol = ACCENT if selected else VALUE_COL
            rows.append(("WEAPON" if label == strip[0][0] else "",
                         f"{marker}{label}  {ammo_text}", wcol))
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
        # M3-F5: degraded-radar burn-through row under enemy jamming (None in
        # the default battle -> the block is unchanged).
        jam = radar_jam_row(world)
        if jam is not None:
            rows.append(jam)
        pantsir = pantsir_status_row(
            world, engaging=getattr(sandbox, "pantsir_engaging", False))
        if pantsir is not None:
            rows.append(pantsir)
        # M6 salvo: mode selector + queued-rounds readout (own-force; None on
        # the legacy/smoke path -> the block is unchanged).
        salvo = salvo_readout(sandbox)
        if salvo is not None:
            rows.append(salvo)
        rows += [
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        # M1-F4: per-tube battery row (own-force; [] in SANDBOX -> unchanged).
        height = self._block(BASTION.display_name.upper(), rows,
                             cells=tube_cells(world, "bastion"))
        # M3-F5: the own-emissions gauge (how loud the player is on the
        # back-plot) anchored below the data-driven block bottom; None when
        # silent -> nothing drawn.
        self._emissions_gauge(world, MARGIN + height)

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
        # M3-F5: degraded-radar burn-through row under enemy jamming (None in
        # the default battle -> the block is unchanged).
        jam = radar_jam_row(world)
        if jam is not None:
            rows.append(jam)
        pantsir = pantsir_status_row(
            world, engaging=getattr(sandbox, "pantsir_engaging", False))
        if pantsir is not None:
            rows.append(pantsir)
        # M6 salvo: mode selector + queued-rounds readout (own-force; None on
        # the legacy/smoke path -> the block is unchanged).
        salvo = salvo_readout(sandbox)
        if salvo is not None:
            rows.append(salvo)
        rows += [
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        # M1-F4: per-tube battery row (own-force; [] in SANDBOX -> unchanged).
        height = self._block(S300_TEL.display_name.upper(), rows,
                             cells=tube_cells(world, "s300"))
        # M3-F5: the own-emissions gauge (how loud the player is on the
        # back-plot) anchored below the data-driven block bottom; None when
        # silent -> nothing drawn.
        self._emissions_gauge(world, MARGIN + height)

    def _buk_block(self, sandbox) -> None:
        """M5 Buk mid-SAM platform panel (mirror of _s300_block): the selected
        round's readiness + both pools from buk_round_panel, the target summary
        around the Buk site, and the per-tube battery row."""
        world = sandbox.world
        from world.combat import BUK_SITE_XZ
        origin = (BUK_SITE_XZ[0], 0.0, BUK_SITE_XZ[1])
        buk_round = getattr(sandbox, "buk_round", "9m317")
        status, col, name, ammo_text = buk_round_panel(world, buk_round)
        rows = [
            ("STATUS", status, col),
            ("WEAPON", name, VALUE_COL),
            ("AMMO", ammo_text, VALUE_COL),
            ("TARGET", self._target_summary(sandbox, origin), VALUE_COL),
        ]
        radar = radar_status_row(world)
        if radar is not None:
            rows.append(radar)
        jam = radar_jam_row(world)
        if jam is not None:
            rows.append(jam)
        pantsir = pantsir_status_row(
            world, engaging=getattr(sandbox, "pantsir_engaging", False))
        if pantsir is not None:
            rows.append(pantsir)
        rows += [
            ("TIME", self._scale_text(sandbox), VALUE_COL),
            ("CLOCK", "T+" + _fmt_clock(world.sim_time), VALUE_COL),
        ]
        height = self._block(BUK_TEL.display_name.upper(), rows,
                             cells=tube_cells(world, "buk"))
        self._emissions_gauge(world, MARGIN + height)

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
        requested = sandbox.controls.requested_scale
        # M6 AUTO-TIME-WARP: when auto pacing is ON show the EFFECTIVE scale and
        # a TARGET / cause tag; the auto-drop tag (INBOUND/TERMINAL/INTERCEPT)
        # tells the player WHY time slowed, and '^ramping' marks the ease back.
        if getattr(sandbox.controls, "auto_warp", False):
            txt = f"x{eff:g}"
            cause = drop_cause(sandbox.world)
            if cause is not None or sandbox.warp_drop_active():
                txt += f" (auto: {cause or 'LAUNCH'})"
            elif eff < requested - 1e-3:
                txt += f" (auto ^ramping -> x{requested:g})"
            elif eff > requested + 1e-3:
                txt += f" (auto v-> x{requested:g})"
            else:
                txt += f" (auto x{requested:g})"
            return txt
        txt = f"x{eff:g}"
        if eff != requested:
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

    # ------------------------------------------ threat strip + intel panel

    def _threat_strip(self, sandbox, friendly_xz, w: int, h: int) -> None:
        """Right-edge inbound column from ``threat_rows`` (M1): one badge +
        bearing/range line per hostile, soonest impact at the top, colored by
        severity. Reads ONLY the gated picture (the pure helper enforces this);
        an empty board draws nothing. The single most-critical row (top, DANGER)
        breathes via a sim-clock sine so the eye snaps to it.

        Queues into the shared TextRenderer (NO flush): the HUD's draw() and the
        map's _chrome() both call it, then flush ONCE — calling flush here would
        double-flush the map batch."""
        rows = threat_rows(sandbox.world, friendly_xz,
                           sandbox.world.sim_time)
        if not rows:
            return                          # empty board: no strip
        x = w - STRIP_MARGIN - STRIP_W
        y = STRIP_MARGIN
        head = "INBOUND"
        self.text.draw_text(x, y, head, ACCENT, SMALL_SIZE)
        y += self.text.line_height(SMALL_SIZE) + 4
        # Pulse the top critical row: a deterministic sim-clock sine (no RNG,
        # no per-frame state) ramping STRIP_PULSE_LO..HI at STRIP_PULSE_HZ.
        pulse = (STRIP_PULSE_LO + (STRIP_PULSE_HI - STRIP_PULSE_LO)
                 * 0.5 * (1.0 + np.sin(sandbox.world.sim_time
                                       * 2.0 * np.pi * STRIP_PULSE_HZ)))
        for i, r in enumerate(rows):
            col = SEVERITY_COLORS.get(r.severity, MUTED)
            a = pulse if (i == 0 and r.severity == "DANGER") else 1.0
            kind = (r.kind or "UNK").upper()
            tti = f"{r.tti:.0f}s" if r.tti is not None else "--"
            line = f"{kind}  {r.brg:03d}  {r.rng / 1e3:.0f}km  {tti}"
            self.text.draw_text(x, y, line, (*col[:3], a))
            y += STRIP_ROW_H

    def _intel_panel(self, world, selected_contact, origin_xz, x, y) -> None:
        """Docked contact-intel panel from ``contact_intel`` (M1): the
        sensor-derived track inspector (CLASS / ID / course / a confidence
        gauge / a bearing rose). Nothing when no contact is selected or the
        track has dropped. Queues into the shared TextRenderer (NO flush)."""
        intel = contact_intel(world, selected_contact, origin_xz,
                              world.sim_time)
        if intel is None:
            return
        # Fixed-height panel: header rule + the value rows + the confidence
        # gauge, with a bearing rose docked on the right.
        rows = [
            ("CLASS", intel["cls"]),
            ("ID", intel["id"]),
            ("BRG", f"{intel['brg']:03d}"),
            ("RNG", f"{intel['rng'] / 1e3:.1f} km"),
            ("CRS", f"{intel['course']:03d}  {intel['speed']:.0f} m/s"),
            ("ALT", f"{intel['alt']:,.0f} m"),
            ("SRC", intel["source"]
             + ("  DR" if intel["dead_reckoned"] else "")),
        ]
        head_h = self.text.line_height(HEADER_SIZE)
        height = (INTEL_PAD * 2 + head_h + 4 + HEADER_GAP
                  + len(rows) * INTEL_LINE_H + INTEL_GAUGE_H + 18)
        draw_panel(self.text, x, y, INTEL_W, height, alpha=PANEL_ALPHA)
        tx = x + INTEL_PAD
        ty = y + INTEL_PAD
        self.text.draw_text(tx, ty, "CONTACT", HEADER_COL, HEADER_SIZE)
        # Bearing rose, top-right of the panel.
        cx = x + INTEL_W - INTEL_PAD - INTEL_COMPASS_R
        cy = ty + head_h * 0.5 + INTEL_COMPASS_R * 0.2
        _mini_compass(self.text, cx, cy, INTEL_COMPASS_R, [intel["brg"]])
        ty += head_h + 4
        draw_header_rule(self.text, tx, ty, INTEL_W - 2 * INTEL_PAD)
        ty += HEADER_GAP
        # The estimate-class fields render in the faded contact idiom (a sensor
        # GUESS reads dimmer than friendly truth — fog-of-war color contract);
        # the ID/CLASS labels stay MUTED.
        for label, value in rows:
            self.text.draw_text(tx, ty, label, LABEL_COL)
            self.text.draw_text(tx + INTEL_VALUE_X, ty, value, ACCENT_DIM)
            ty += INTEL_LINE_H
        # Confidence gauge: amber while a live fix, dimmer as it fades.
        ty += 4
        self.text.draw_text(tx, ty - 2, "CONF", LABEL_COL)
        gauge_col = OK_COL if intel["confidence"] >= 0.8 else WARN
        _gauge_bar(self.text, tx + INTEL_VALUE_X, ty,
                   INTEL_W - 2 * INTEL_PAD - INTEL_VALUE_X, INTEL_GAUGE_H,
                   intel["confidence"], gauge_col)

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

    def _battery_panel(self, sandbox, w: int, h: int) -> None:
        """O: the EXPANDED per-battery status board (M6) — a centered corner-
        ticked panel (the F1-overlay chrome) listing every player battery as a
        row of tube badges with the pooled magazine + refill timer.  Built from
        the pure ``battery_status_rows`` helper, so it can never show stale or
        enemy state (own-force only; the sim keeps running — overlay, not menu).
        """
        text = self.text
        bats = battery_status_rows(sandbox.world)
        head_h = text.line_height(HEADER_SIZE)
        small_h = text.line_height(SMALL_SIZE)
        n_rows = max(1, len(bats))           # an empty world still draws a note
        content_h = n_rows * BPANEL_ROW_H
        panel_h = (PANEL_PAD * 2 + head_h + 4 + HEADER_GAP + content_h
                   + 8 + small_h)
        x = (w - BPANEL_W) // 2
        y = (h - panel_h) // 2
        text.draw_rect(x - BPANEL_DIM, y - BPANEL_DIM,
                       BPANEL_W + 2 * BPANEL_DIM, panel_h + 2 * BPANEL_DIM,
                       (*BG0, 0.35))
        draw_panel(text, x, y, BPANEL_W, panel_h, alpha=0.92, strip=True)
        tx = x + PANEL_PAD
        ty = y + PANEL_PAD
        text.draw_text(tx, ty, BPANEL_TITLE, HEADER_COL, HEADER_SIZE)
        ty += head_h + 4
        draw_header_rule(text, tx, ty, BPANEL_W - 2 * PANEL_PAD)
        ty += HEADER_GAP
        if not bats:
            # SANDBOX / infinite-magazine world: nothing per-battery to show.
            text.draw_text(tx, ty + (BPANEL_ROW_H - small_h) // 2,
                           BPANEL_EMPTY, MUTED, SMALL_SIZE)
        for bat in bats:
            self._battery_row(tx, ty, bat, BPANEL_W - 2 * PANEL_PAD)
            ty += BPANEL_ROW_H
        ty = y + panel_h - PANEL_PAD - small_h
        fw = text.text_width(BPANEL_FOOTER, SMALL_SIZE)
        text.draw_text(x + (BPANEL_W - fw) // 2, ty, BPANEL_FOOTER,
                       ACCENT_DIM, SMALL_SIZE)

    def _battery_row(self, x, y, bat, row_w) -> None:
        """One battery row of the expanded board: the name + pooled magazine on
        the left, the per-tube state badges (LOADED/RELOADING/EMPTY via
        SEMANTIC_COLORS — the own-force idiom) on the right, with a thin reload
        gauge under a RELOADING tube.  OWN-FORCE only; no contact reads."""
        text = self.text
        small_h = text.line_height(SMALL_SIZE)
        text.draw_text(x, y, bat["name"], LABEL_COL, SMALL_SIZE)
        pool = bat["pool_text"]
        if pool is not None:
            ptxt = pool
            if bat["refill_left"] > 0.0:
                ptxt += f"  RLDG {int(np.ceil(bat['refill_left'] - 1e-9))}s"
            text.draw_text(x, y + small_h + TUBE_LABEL_GAP, ptxt,
                           bat["pool_col"], SMALL_SIZE)
        # Tube badges, right of the name column.
        bx = x + BPANEL_NAME_W
        for i, (state, _left) in enumerate(bat["tubes"]):
            cx = bx + i * (TUBE_CELL_W + TUBE_GAP)
            text.draw_text(cx, y, str(i + 1), MUTED, SMALL_SIZE)
            ly = y + small_h + TUBE_LABEL_GAP
            # READY is the own-force LOADED token in SEMANTIC_COLORS; map the
            # LOADED state onto it so the badge reads green.
            badge_state = "READY" if state == "LOADED" else state
            _badge(text, badge_state, cx, ly, badge_state, size=SMALL_SIZE)

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
