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
from game.keybinds import ACTIONS
from sim.contacts import classify as _classify
from sim.contacts import track_quality as _track_quality
import game.states as _S
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
PANEL_W = 308               # px, platform plate width (mock 04)
PANEL_PAD = 14              # px, inner padding of the platform plate
LINE_H = 30                 # px, row pitch of the platform plate (18pt rows)
VALUE_X = 104               # px, label -> value column offset (legacy blocks)
HEADER_GAP = 10             # px, gap under the header rule
HINT_MARGIN = 10            # px, hint line offset from the bottom edge
CORNER_MARGIN = 16          # px, bottom-right micro-label inset (spec §4.1)
# Panel ink calibration (mock 07): the HUD plates read as rgba-ink over the
# WORST-CASE bright 3D scene at .93, not the old translucent .55.
PANEL_ALPHA = 0.93

# Wardroom Dusk: the HUD speaks the shared states.py palette (no forked hues).
PANEL_RGBA = (*_S.PLATE_INK, PANEL_ALPHA)    # over-3D plate ink (mock 07)
LABEL_COL = (*MUTED, 1.0)                    # muted sage labels
VALUE_COL = (*TEXT_COL, 1.0)                 # warm-cream values
HEADER_COL = (*ACCENT, 1.0)                  # brass headline
ARMED_COL = (*OK_COL, 1.0)                   # own-force truth green
RELOAD_COL = (*WARN, 1.0)                    # status amber
TERMINAL_COL = (*_S.HOSTILE_AGED, 1.0)       # TERMINAL phase pops dusk-red
DANGER_COL = (*DANGER, 1.0)                  # destroyed / defeat (states.py DANGER)

# COMBAT Phase 3: radar-silence readout + the lose-condition banner.
# Phase 5b adds the mirrored win banner (spec 2.2: all enemy ships + the
# airfield destroyed — world/combat.py ``victorious``).  Defeat outranks
# victory if both somehow latch in one frame (losing the Bastion is final).
RADAR_EMITTING = "EMITTING"
RADAR_SILENT = "SILENT"
RADAR_DESTROYED = "DESTROYED"
DEFEAT_TEXT = "BASTION DESTROYED - DEFEAT"
DEFEAT_TEXT_BEACHHEAD = "BEACHHEAD ESTABLISHED - DEFEAT"
VICTORY_TEXT = "ENEMY FORCE DESTROYED - VICTORY"
DEFEAT_Y_FRAC = 0.24        # banner center height as a fraction of the screen
DEFEAT_PAD_X = 28           # px panel padding around the banner text
DEFEAT_PAD_Y = 18

F1_LABEL = "F1 CONTROLS"    # the HUD's entire permanent hint footprint
OVERLAY_W = 1040            # px, F1 overlay panel width (mock 10: two-column)
OVERLAY_COL_GAP = 40        # px, gap between the two binding columns
OVERLAY_ROW_H = 24          # px, overlay binding-row pitch
OVERLAY_DIM = 24            # px, dim-rect margin around the overlay panel
OVERLAY_FOOTER = "F1 CLOSE   REBIND IN SETTINGS"

# Target bracket: 4 corner L's sized with the locked ship's on-screen extent.
# Spec §7: the selected/locked target's bracket is BRASS (selection family).
BRACKET_COL = (*ACCENT, 0.95)
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

# Sensor staleness thresholds for the intel panel.  (The old age-keyed
# IDENTIFIED/CLASSIFIED ladder is gone — classification is now EARNED by
# dwell, sim/contacts.classify; staleness only degrades position quality.)
AGE_CLASSIFIED_S = 20.0     # older than this -> the fix is dead-reckoned
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

# Severity token -> palette color (no hard-coded RGB at the strip call site).
# A non-urgent vampire is still a HOSTILE contact, so the quiet band wears the
# aged dusk-red — never the neutral muted (fog-of-war color LAW: hostile
# contacts live in the dusk-red family, age/urgency expressed by tone).
SEVERITY_COLORS = {"DANGER": DANGER, "WARN": WARN, "MUTED": _S.HOSTILE_AGED}

# INBOUND ranked cards (mock 04): card chrome + the TTI countdown bar.
CARD_W = 286                # px, inbound-card column width
CARD_INK = (0.090, 0.078, 0.071)     # rgba(23,20,18) card fill (@0.9)
CARD_PAD = 12               # px, card inner padding
CARD_BAR_W = 4              # px, severity bar on the card's left edge
CARD_GAP = 10               # px, vertical gap between cards
TTI_BAR_WINDOW_S = 240.0    # bar = time-to-impact as a fraction of this
#                             window (a typical long SAM/vampire flight); the
#                             bar DRAINS as the round closes — presentation
#                             scale only, the number next to it is the truth
CARD_MAX = 5                # cards shown; the rest collapse to '+N MORE'
INBOUND_BLINK_S = 1.2       # header blink period (mock: steps(1) 1.2s)

# A single fog-pierced inbound row: sid (track id), kind (weapon_id stamp),
# brg (compass deg from the friendly asset to the estimate), rng (ground-plane
# metres), tti (seconds, or None when not closing) and severity (a SEMANTIC
# state token: DANGER / WARN / MUTED).
ThreatRow = namedtuple("ThreatRow", "sid kind brg rng tti severity")

STRIP_MARGIN = 16           # px, strip inset from the right/top screen edges
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
TUBE_GAP = 6                # px, horizontal gap between adjacent tube cells
TUBE_ROW_GAP = 6            # px, gap between the panel body and the tube row
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
    # When BOTH pools are dry, the tubes go LOADED again the moment EITHER
    # pool refills (tube_state keys on the combined stock) — so the honest
    # countdown is the SOONEST running timer, not the max (which overstated
    # the wait by up to a full refill cycle and had players holding fire).
    # A timer at 0 while dry means that pool has no refill armed: ignore it.
    refill_left = 0.0
    if not pool_has_round:
        timers = [t for t in (
            float(getattr(world, "_s300_48n6_mag_reload_left", 0.0)),
            float(getattr(world, "_s300_40n6_mag_reload_left", 0.0)))
            if t > 0.0]
        refill_left = min(timers) if timers else 0.0
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
    """The fog-of-war track inspector for the click-contact intel panel (M1,
    re-keyed by the classification spec) — pure, GL-free, deterministic.
    None when ``sid`` is None or not on the board; else a dict of
    sensor-DERIVED fields (never truth):

      cls           'UNKNOWN' until the dwell ladder earns the class, then
                    'MISSILE' / 'AIR' / 'SURFACE' (size + is_air)
      id            the ladder stage 'UNKNOWN' / 'CLASSIFIED' / 'IDENTIFIED'
                    — earned by TRACK DWELL (sim/contacts.classify), MONOTONIC
                    (a coasting track keeps what it earned; the old age-keyed
                    version called a first-frame track IDENTIFIED — the exact
                    free-knowledge bug the spec removes)
      label         the display name the ladder has earned (UNK / MSL / SM6)
      quality       Q5 (fresh paint) .. Q1 (about to drop) — position quality
                    from staleness (sim/contacts.track_quality)
      confidence    [0, 1] fading linearly with age (fresh >= 0.8)
      dead_reckoned True once age >= AGE_CLASSIFIED_S (the fix is coasting)
      brg, rng      compass bearing + ground-plane range from origin -> estimate
      course        compass heading of the track velocity
      speed         ground-plane speed (m/s) — always shown: honestly measured
      alt           estimated altitude (m, the estimate's y)
      kind          the TYPE stamp, or None while the ladder hasn't earned it
      age           the raw staleness stamp
      source        'RADAR' for a live fix, 'COAST' once dead-reckoned
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
    stage, label = _classify(track, now)
    if stage == "UNKNOWN":
        cls = "UNKNOWN"
    elif size == "missile":
        cls = "MISSILE"
    elif is_air:
        cls = "AIR"
    else:
        cls = "SURFACE"
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
        "id": stage,
        "label": label,
        "quality": _track_quality(track),
        "confidence": confidence,
        "dead_reckoned": dead_reckoned,
        "brg": brg,
        "rng": rng,
        "course": course,
        "speed": speed,
        "alt": float(est[1]),
        # The TYPE is only surfaced once the ladder earned it (fog LAW:
        # never display what the sensors have not produced yet).
        "kind": track.get("kind") if stage == "IDENTIFIED" else None,
        "age": age,
        "source": "COAST" if dead_reckoned else "RADAR",
    }


def interceptor_pairings(world):
    """{hostile air-track id: count of OWN interceptors in flight at it} —
    the honest core of the NTDS 'FCS assigned' modifier (proto 03).

    OWN-FORCE TRUTH ONLY (allowed): reads each of OUR live rounds' .target
    entity reference (our own fire-control assignment) and keys it by the
    target's ``aircraft_id`` — the same id the ContactBoard tracks under.
    Enemy rounds (is_hostile) and surface-target rounds (Oniks locked ships,
    ARM radar shots) are excluded; this counts interceptors at AIR threats.
    Never reads enemy intent — unlike the rejected 'S-300 ASSIGNED' mock
    copy, PAIRED/UNCOVERED states a fact about MY rounds."""
    out: dict = {}
    for m in getattr(world, "missiles", ()):
        if not getattr(m, "alive", False):
            continue
        if getattr(m, "is_hostile", False):
            continue                        # not ours
        tgt = getattr(m, "target", None)
        if tgt is None or not getattr(tgt, "is_air", False):
            continue                        # interceptors only
        tid = getattr(tgt, "aircraft_id", None)
        if tid:
            out[tid] = out.get(tid, 0) + 1
    return out


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
    route = getattr(drone, "route", ())
    rows = [
        ("STATUS", "AIRBORNE", ARMED_COL),
        # Tasking state (playtest 2026-07-05): an untasked drone loiters
        # over the base and finds NOTHING — the fleet sits beyond the
        # radar horizon, so a silent loiter must never read as 'working'.
        # Amber call-to-action while the route is empty; WPT count once
        # tasked (own-force telemetry, no fog).
        ("TASKING", (f"{len(route)} WPT" if route
                     else "NONE - RMB ON MAP TO TASK"),
         VALUE_COL if route else RELOAD_COL),
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
        # FOG: a SAM guides on the dead-reckoned contact estimate until its
        # TERMINAL seeker tracks truth — read the round's OWN guidance
        # picture (_target_state) rather than tgt.pos, which handed the HUD
        # free truth telemetry (a wandering stale track on the map while the
        # RNG row counted down against the target's real position).
        state_fn = getattr(m, "_target_state", None)
        if state_fn is not None:
            tx, ty, tz = state_fn()[:3]
            return np.array([tx, ty, tz], dtype=np.float64)
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
        # Track ids already announced on the INBOUND stack (render-side
        # state: drives the one-shot NEW-CONTACT hint, never the sim).
        self._threat_seen: set = set()

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
            # Honest cause: a beachhead loss reads its own banner, not the
            # bastion string (mirrors the end-screen defeat_cause map).
            cause = getattr(sandbox.world, "defeat_cause", None)
            self._banner(w, h,
                         DEFEAT_TEXT_BEACHHEAD if cause == "beachhead"
                         else DEFEAT_TEXT, DANGER_COL)
        elif getattr(sandbox.world, "victorious", False):
            self._banner(w, h, VICTORY_TEXT, ARMED_COL)
        self._clock_chip(sandbox, w)
        self._threat_strip(sandbox, (BASE_POS[0], BASE_POS[2]), w, h)
        self._hint_flash(sandbox, w, h)
        self._corner_labels(sandbox, w, h)
        if getattr(sandbox, "battery_panel_open", False):
            self._battery_panel(sandbox, w, h)
        if sandbox.controls_overlay:
            self._controls_overlay(sandbox, w, h)
        self.text.flush(w, h)

    def draw_flight_block(self, sandbox, m) -> float:
        """Queue (no flush) the flight telemetry block for ``m``: the
        tactical map calls this for the LMB-selected round (Task RTG) so its
        telemetry shows in the same HUD flight block while the map is open.
        Returns the plate height so the caller can dock panels BELOW it
        (the contact card used to draw straight through this plate —
        playtest overlap, 2026-07-05)."""
        return self._flight_block(sandbox, m)

    # ---------------------------------------------------------------- blocks

    def _clock_chip(self, sandbox, w: int) -> None:
        """Top-center clock chip (mock 04): the sim clock cream + the time-
        scale readout faint.  The auto-warp cause text rides in the scale
        span so WHY time slowed stays visible (M6 auto-warp legibility)."""
        text = self.text
        clock = "T+" + _fmt_clock(sandbox.world.sim_time)
        scale = self._scale_text(sandbox)
        body_h = text.line_height(BODY_SIZE)
        small_h = text.line_height(SMALL_SIZE)
        cw = text.text_width(clock)
        sw = text.text_width(scale, SMALL_SIZE)
        pad_x, gap = 18, 12
        bw = round(cw + gap + sw + 2 * pad_x)
        bh = body_h + 14
        x = round((w - bw) / 2)
        y = MARGIN
        text.draw_rect(x, y, bw, bh, (*_S.PLATE_INK, 0.88))
        text.draw_lines([(x, y), (x + bw, y), (x + bw, y + bh), (x, y + bh),
                         (x, y)], (*_S.LINE_COL, 1.0), 1.0)
        text.draw_text(x + pad_x, y + 7, clock, VALUE_COL)
        text.draw_text(x + pad_x + cw + gap,
                       y + 7 + (body_h - small_h) // 2, scale,
                       _S.FAINT, SMALL_SIZE)
        ui = getattr(sandbox, "ui", None)
        if ui is not None:
            ui.add("hud.clock_chip", x, y, bw, bh,
                   code="game/hud.py:_clock_chip")

    def _block(self, header: str, rows, cells=None, status=None,
               emcon=None, reg=None) -> float:
        """The PLATFORM PLATE (mock 04): header row (brass platform name +
        family-tinted status badge) over a brass-capped rule, label/value
        rows right-aligned (a truthy 4th row element marks the selected-
        WEAPON row: plate-selected fill + 3px brass bar), TUBE boxes, and
        the in-plate EMCON meter.  Returns the plate height (px).

        ``cells`` is a ``tube_cells`` list (own-force only, [] in SANDBOX);
        ``status`` is an optional (text, color) badge; ``emcon`` an optional
        (label, frac01, color) meter from emissions_exposure."""
        text = self.text
        small_h = text.line_height(SMALL_SIZE)
        body_h = text.line_height(BODY_SIZE)
        tube_box_h = small_h + 12
        head_band = 10 + small_h + 9            # header row + rule gap
        tube_band = (TUBE_ROW_GAP + tube_box_h + 4) if cells else 0
        emcon_band = (small_h + 10) if emcon else 0
        height = (head_band + HEADER_GAP + len(rows) * LINE_H + tube_band
                  + emcon_band + PANEL_PAD)
        draw_panel(text, MARGIN, MARGIN, PANEL_W, height, alpha=PANEL_ALPHA,
                   fill=_S.PLATE_INK, ticks=False)
        # UI registry (mouse parity + F3 tagging, 2026-07-05): ``reg`` is
        # (sandbox, name, header_action, body_action).  The plate registers
        # whole (click-consuming), then a header zone and a body zone that
        # dispatch the SAME action ids the key bindings fire — e.g. the
        # bastion plate header TABs platforms, its body cycles the weapon.
        if reg is not None:
            sandbox, name, header_action, body_action = reg
            ui = getattr(sandbox, "ui", None)
            if ui is not None:
                code = "game/hud.py:_block"
                ui.add(name, MARGIN, MARGIN, PANEL_W, height, code=code)
                if header_action:
                    ui.add(name + ".header", MARGIN, MARGIN, PANEL_W,
                           head_band, action=header_action, parent=name,
                           code=code)
                if body_action:
                    ui.add(name + ".body", MARGIN, MARGIN + head_band,
                           PANEL_W, height - head_band, action=body_action,
                           parent=name, code=code)
        tx = MARGIN + PANEL_PAD
        inner_w = PANEL_W - 2 * PANEL_PAD
        ty = MARGIN + 10
        text.draw_text(tx, ty, header, HEADER_COL, SMALL_SIZE)
        if status is not None:
            s_text, s_col = status
            bw = round(text.text_width(s_text, SMALL_SIZE) + 14)
            bh = small_h + 4
            bx = MARGIN + PANEL_W - PANEL_PAD - bw
            by = ty - 2
            text.draw_rect(bx, by, bw, bh, (*s_col[:3], 0.14))
            text.draw_lines([(bx, by), (bx + bw, by), (bx + bw, by + bh),
                             (bx, by + bh), (bx, by)], (*s_col[:3], 0.9), 1.0)
            text.draw_text(bx + 7, ty, s_text, s_col, SMALL_SIZE)
        ty += small_h + 8
        draw_header_rule(text, MARGIN + 1, ty, PANEL_W - 2)
        ty += 1 + HEADER_GAP
        for row in rows:
            label, value, col = row[0], row[1], row[2]
            selected = len(row) > 3 and row[3]
            vy = ty + (LINE_H - body_h) // 2
            if selected:
                text.draw_rect(MARGIN + 1, ty, PANEL_W - 2, LINE_H,
                               (*_S.BG2, 1.0))
                text.draw_rect(MARGIN + 1, ty, 3, LINE_H, (*ACCENT, 1.0))
            if label:
                text.draw_text(tx, vy, label,
                               ACCENT if selected else LABEL_COL)
            vw = text.text_width(value)
            text.draw_text(MARGIN + PANEL_W - PANEL_PAD - vw, vy, value, col)
            ty += LINE_H
        if cells:
            ty += TUBE_ROW_GAP
            self._tube_boxes(tx, ty, inner_w, cells, tube_box_h)
            ty += tube_box_h + 4
        if emcon:
            label, frac, col = emcon
            gy = ty + 4
            text.draw_text(tx, gy, label, LABEL_COL, SMALL_SIZE)
            cap_w = text.text_width(label, SMALL_SIZE)
            pct = f"{int(round(frac * 100))}%"
            pw = text.text_width(pct, SMALL_SIZE)
            bar_x = tx + cap_w + 8
            bar_w = max(1.0, inner_w - cap_w - 8 - pw - 8)
            _gauge_bar(text, bar_x, gy + (small_h - 5) // 2, bar_w, 5,
                       frac, col)
            text.draw_text(tx + inner_w - pw, gy, pct, col, SMALL_SIZE)
        return height

    def _tube_boxes(self, x, y, w, cells, box_h) -> None:
        """TUBE CELL boxes (spec §5): family-color border + tinted fill —
        green 'TUBE n - RDY', amber reloading with a thin progress strip,
        hairline+disabled empty.  Boxes split the plate's inner width; the
        labels shorten when >2 tubes so an S-300 row of 4 still reads.
        OWN-FORCE only — no contact/enemy reads."""
        text = self.text
        small_h = text.line_height(SMALL_SIZE)
        n = len(cells)
        box_w = (w - TUBE_GAP * (n - 1)) / n
        short = n > 2
        for i, (label, state, frac) in enumerate(cells):
            bx = round(x + i * (box_w + TUBE_GAP))
            col = SEMANTIC_COLORS.get(state, MUTED)
            st = {"READY": "RDY", "RELOADING": "RLD", "EMPTY": "EMP"}.get(
                state, state)
            txt = f"{label} {st}" if short else f"TUBE {label} - {st}"
            if state == "EMPTY":
                border, fill_a, tcol = _S.LINE_COL, 0.0, (*_S.DISABLED, 1.0)
            else:
                border, fill_a, tcol = col, 0.14, (*col[:3], 1.0)
            if fill_a > 0.0:
                text.draw_rect(bx, y, round(box_w), box_h,
                               (*col[:3], fill_a))
            text.draw_lines([(bx, y), (bx + box_w, y),
                             (bx + box_w, y + box_h), (bx, y + box_h),
                             (bx, y)], (*border[:3], 0.9), 1.0)
            tw = text.text_width(txt, SMALL_SIZE)
            text.draw_text(round(bx + (box_w - tw) / 2),
                           y + (box_h - small_h) // 2, txt, tcol, SMALL_SIZE)
            if state == "RELOADING":
                # Thin progress strip along the box bottom.
                fw = round((box_w - 4) * _clamp01(frac))
                if fw > 0:
                    text.draw_rect(bx + 2, y + box_h - 4, fw, 2,
                                   (*col[:3], 0.9))

    def _flight_block(self, sandbox, m) -> None:
        """In-flight telemetry for the followed missile (Oniks or SAM).
        The flight phase is the plate's status badge (TERMINAL pops
        dusk-red); TIME/CLOCK live in the top-center clock chip."""
        speed = float(np.linalg.norm(m.vel))
        alt = float(m.pos[1])
        tgt = _missile_target_pos(m)
        rng_km = (float(np.hypot(tgt[0] - m.pos[0], tgt[2] - m.pos[2])) / 1e3
                  if tgt is not None else None)
        label = m.phase_label
        phase_col = TERMINAL_COL if label == "TERMINAL" else ARMED_COL
        rows = []
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
        return self._block(m.weapon.display_name.upper(), rows,
                           status=(label, phase_col),
                           reg=(sandbox, "hud.flight_block", None, None))

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
        """Recon-drone platform panel (Phase 4): flight/sensor/RWR rows from
        the pure helper; the STATUS row is the plate's badge.  The EMCON
        meter rides inside the plate — the drone is where the EW pod goes
        hot and back-plot exposure peaks."""
        world = sandbox.world
        rows = drone_panel_rows(world)
        status = None
        if rows and rows[0][0] == "STATUS":
            status = (rows[0][1], rows[0][2])
            rows = rows[1:]
        self._block("RECON DRONE", rows, status=status,
                    emcon=emissions_exposure(world),
                    reg=(sandbox, "hud.plate.drone", "cycle_platform",
                         "jam"))

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
        rows = []
        # M2-T4: the Bastion weapon-select strip — one row per chamberable
        # round (ONIKS|ZIRCON, plus KH-31P only when the ARM pool is stocked).
        # The ACTIVE round renders as the plate's selected-WEAPON row (mock
        # 04: plate-selected fill + 3px brass bar + brass '>' value); the
        # rest are quiet right-aligned rows below it.
        strip = bastion_weapon_strip(sandbox, world)
        for label, selected, ammo_text in strip:
            if selected:
                rows.append(("WEAPON", f"> {label} {ammo_text}", ACCENT,
                             True))
            else:
                rows.append(("", f"{label} {ammo_text}", VALUE_COL))
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
        # M1-F4 tube boxes + M3-F5 in-plate EMCON meter (own-force).
        self._block(BASTION.display_name.upper(), rows,
                    cells=tube_cells(world, "bastion"),
                    status=(status, col),
                    emcon=emissions_exposure(world),
                    reg=(sandbox, "hud.plate.bastion", "cycle_platform",
                         "oniks_weapon"))

    def _s300_block(self, sandbox) -> None:
        world = sandbox.world
        sam_round = getattr(sandbox, "sam_round", "48n6")
        status, col, name, ammo_text = s300_round_panel(world, sam_round)
        rows = [
            ("WEAPON", f"> {name}", ACCENT, True),   # the B-cycled round
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
        self._block(S300_TEL.display_name.upper(), rows,
                    cells=tube_cells(world, "s300"),
                    status=(status, col),
                    emcon=emissions_exposure(world),
                    reg=(sandbox, "hud.plate.s300", "cycle_platform",
                         "sam_round"))

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
            ("WEAPON", f"> {name}", ACCENT, True),   # the B-cycled round
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
        self._block(BUK_TEL.display_name.upper(), rows,
                    cells=tube_cells(world, "buk"),
                    status=(status, col),
                    emcon=emissions_exposure(world),
                    reg=(sandbox, "hud.plate.buk", "cycle_platform",
                         "sam_round"))

    @staticmethod
    def _target_summary(sandbox, origin) -> str:
        tp = sandbox.target_point
        if tp is None:
            return "NONE"
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
            # LATCHED cause from the warp director (not a fresh drop_cause
            # recompute): the tag holds steady through the DWELL debounce
            # instead of flickering off while the warp still sits at 1x.
            director = getattr(sandbox.controls, "warp_director", None)
            cause = director.cause if director is not None else None
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
        """Right-edge INBOUND ranked cards from ``threat_rows`` (mock 04):
        soonest impact on top, each a severity-tinted card — 4px left bar,
        kind + bearing line, the TTI seconds, a range line, and a 3px
        countdown bar that drains over TTI_BAR_WINDOW_S (the number beside
        it is the truth; the bar is the glance).  Beyond CARD_MAX cards the
        tail collapses to an honest '+N MORE'.  Reads ONLY the gated picture
        (the pure helper enforces this); an empty board draws nothing.  The
        top DANGER card's bar breathes via a deterministic sim-clock sine.

        Queues into the shared TextRenderer (NO flush): the HUD's draw() and
        the map's _chrome() both call it, then flush ONCE."""
        world = sandbox.world
        rows = threat_rows(world, friendly_xz, world.sim_time)
        if not rows:
            return                          # empty board: no strip
        text = self.text
        # One-shot launch warning: a track id newly ON the stack flashes the
        # contextual hint — the player hears 'something is inbound' before
        # the ladder has earned WHAT it is (classification spec).
        new_sids = [r.sid for r in rows if r.sid not in self._threat_seen]
        if new_sids:
            self._threat_seen.update(new_sids)
            hint = getattr(sandbox, "show_hint", None)
            if hint is not None:
                hint("WARNING - NEW INBOUND CONTACT")
        tracks = world.contacts.tracks
        pairings = interceptor_pairings(world)
        small_h = text.line_height(SMALL_SIZE)
        body_h = text.line_height(BODY_SIZE)
        x = w - STRIP_MARGIN - CARD_W
        y = STRIP_MARGIN
        # Header: tracked dusk-red label (mock blink, steps(1)) + the count
        # with the honest coverage tally (proto 03: 'N - M UNCOVERED').
        blink_on = (world.sim_time % INBOUND_BLINK_S) < 0.66
        text.draw_text(x + 2, y, "INBOUND",
                       (*_S.HOSTILE_AGED, 1.0 if blink_on else 0.35),
                       SMALL_SIZE)
        uncovered = sum(1 for r in rows if not pairings.get(r.sid))
        cnt = (f"{len(rows)} - {uncovered} UNCOVERED" if uncovered
               else f"{len(rows)} - ALL PAIRED")
        ccol = DANGER if uncovered else OK_COL
        text.draw_text(x + CARD_W - 2 - text.text_width(cnt, SMALL_SIZE), y,
                       cnt, (*ccol[:3], 1.0), SMALL_SIZE)
        y += small_h + 8
        card_h = 6 + body_h + 2 + small_h + 6 + 3 + 8
        pulse = (STRIP_PULSE_LO + (STRIP_PULSE_HI - STRIP_PULSE_LO)
                 * 0.5 * (1.0 + np.sin(world.sim_time
                                       * 2.0 * np.pi * STRIP_PULSE_HZ)))
        for i, r in enumerate(rows[:CARD_MAX]):
            col = SEVERITY_COLORS.get(r.severity, MUTED)[:3]
            bar_a = pulse if (i == 0 and r.severity == "DANGER") else 1.0
            text.draw_rect(x, y, CARD_W, card_h, (*CARD_INK, 0.9))
            text.draw_lines([(x, y), (x + CARD_W, y),
                             (x + CARD_W, y + card_h), (x, y + card_h),
                             (x, y)], (*col, 0.35), 1.0)
            text.draw_rect(x, y, CARD_BAR_W, card_h, (*col, bar_a))
            cx = x + CARD_BAR_W + CARD_PAD
            # Classification ladder (fog LAW): the card names the round only
            # once the dwell earned it — UNK -> MSL -> SM6.  Speed is always
            # shown (honestly measured from the track vector).
            trk = tracks.get(r.sid)
            label = _classify(trk, world.sim_time)[1] if trk is not None \
                else (r.kind or "UNK").upper()
            tti_txt = f"{r.tti:.0f} S" if r.tti is not None else "--"
            tw = text.text_width(tti_txt)
            text.draw_text(x + CARD_W - CARD_PAD - tw, y + 6, tti_txt,
                           VALUE_COL)
            text.draw_text(cx, y + 6 + (body_h - small_h) // 2,
                           f"{label} - BRG {r.brg:03d}", (*col, 1.0),
                           SMALL_SIZE)
            spd = (float(np.hypot(trk["vel"][0], trk["vel"][2]))
                   if trk is not None else 0.0)
            text.draw_text(cx, y + 6 + body_h + 2,
                           f"{r.rng / 1e3:.0f} KM - {spd:.0f} M/S",
                           MUTED, SMALL_SIZE)
            # Coverage state (own-force truth: my interceptors in flight).
            n_up = pairings.get(r.sid, 0)
            cov = f"PAIRED x{n_up}" if n_up else "UNCOVERED"
            cov_col = OK_COL if n_up else DANGER
            cw2 = text.text_width(cov, SMALL_SIZE)
            text.draw_text(x + CARD_W - CARD_PAD - cw2, y + 6 + body_h + 2,
                           cov, (*cov_col[:3], 0.9), SMALL_SIZE)
            # Countdown bar: track in the dim family tone, fill drains with
            # the time remaining (frac of the fixed window).
            by = y + card_h - 8 - 3
            bw = CARD_W - CARD_BAR_W - 2 * CARD_PAD
            text.draw_rect(cx, by, bw, 3, (*col, 0.18))
            frac = _clamp01((r.tti or 0.0) / TTI_BAR_WINDOW_S)
            fw = round(bw * frac)
            if fw > 0:
                text.draw_rect(cx, by, fw, 3, (*col, 0.9))
            y += card_h + CARD_GAP
        extra = len(rows) - CARD_MAX
        if extra > 0:
            more = f"+{extra} MORE"
            text.draw_text(x + 2, y, more, (*_S.HOSTILE_AGED, 0.8),
                           SMALL_SIZE)

    def _intel_panel(self, world, selected_contact, origin_xz, x, y):
        """Docked contact-intel panel from ``contact_intel`` (M1): the
        sensor-derived track inspector (CLASS / ID / course / a confidence
        gauge / a bearing rose). Nothing when no contact is selected or the
        track has dropped. Queues into the shared TextRenderer (NO flush).
        Returns the drawn panel height (px), or None when nothing drew —
        the map registers the rect and stacks panels from it."""
        intel = contact_intel(world, selected_contact, origin_xz,
                              world.sim_time)
        if intel is None:
            return None
        # Fixed-height panel: header rule + the value rows + the confidence
        # gauge, with a bearing rose docked on the right.  TYPE shows the
        # ladder-earned label (UNK -> MSL -> SM6, classification spec) and
        # ID the ladder stage; the Q chip below grades position quality.
        rows = [
            ("CLASS", intel["cls"]),
            ("TYPE", intel["label"]),
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
                  + len(rows) * INTEL_LINE_H + INTEL_GAUGE_H + 42)
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
        # The estimate-class fields render in the BELIEF teal idiom (a sensor
        # GUESS never wears the own-truth green — fog-of-war color LAW);
        # the ID/CLASS labels stay MUTED.
        for label, value in rows:
            self.text.draw_text(tx, ty, label, LABEL_COL)
            self.text.draw_text(tx + INTEL_VALUE_X, ty, value, _S.BELIEF)
            ty += INTEL_LINE_H
        # Fix-freshness gauge (relabeled from the bare 'CONF' bar — playtest
        # 2026-07-05: 'it keeps counting down, it makes no sense').  The bar
        # IS the age of the last radar fix: full on a fresh sweep, draining
        # between sweeps, snapping back on the next fix.  The seconds ride
        # next to it so the drain explains itself.
        ty += 4
        self.text.draw_text(tx, ty - 2, "FIX", LABEL_COL)
        gauge_col = OK_COL if intel["confidence"] >= 0.8 else WARN
        age_txt = f"{intel['age']:.0f}S"
        age_w = self.text.text_width(age_txt, SMALL_SIZE) + 8
        _gauge_bar(self.text, tx + INTEL_VALUE_X, ty,
                   INTEL_W - 2 * INTEL_PAD - INTEL_VALUE_X - age_w,
                   INTEL_GAUGE_H, intel["confidence"], gauge_col)
        self.text.draw_text(x + INTEL_W - INTEL_PAD - age_w + 8, ty - 2,
                            age_txt, LABEL_COL, SMALL_SIZE)
        # Track-quality ladder chip (proto 04): five ascending bars, filled
        # to Q, in the BELIEF teal family (a sensor grade, never truth).
        # 'POS' names what is graded: position quality from staleness.
        ty += INTEL_GAUGE_H + 8
        self.text.draw_text(tx, ty - 2, f"POS Q{intel['quality']}",
                            LABEL_COL, SMALL_SIZE)
        q = int(intel["quality"])
        bx = tx + INTEL_VALUE_X
        for i in range(5):
            bar_h = 4 + 3 * i
            if i < q:
                self.text.draw_rect(bx + i * 9, ty + 12 - bar_h, 6, bar_h,
                                    (*_S.BELIEF, 0.9))
            else:
                self.text.draw_rect(bx + i * 9, ty + 12 - bar_h, 6, bar_h,
                                    (*_S.LINE_COL, 0.9))
        return height

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
        """Bottom-right (mock 04): the boxed CAM chip stacked over the
        combined micro-hint line.  F1_LABEL keeps the exact spec §4.1 copy
        (test-pinned); the map/battery hints ride behind it."""
        text = self.text
        lh = text.line_height(SMALL_SIZE)
        hint = f"{F1_LABEL} - M MAP - O BATTERY"
        hw = text.text_width(hint, SMALL_SIZE)
        hy = h - CORNER_MARGIN - lh
        text.draw_text(w - CORNER_MARGIN - hw, hy, hint, _S.HINT_COL,
                       SMALL_SIZE)
        cam = f"CAM - {sandbox.rig.mode.upper()}"
        cw = text.text_width(cam, SMALL_SIZE)
        bw = round(cw + 20)
        bh = lh + 8
        bx = w - CORNER_MARGIN - bw
        by = hy - 8 - bh
        text.draw_rect(bx, by, bw, bh, (*_S.PLATE_INK, 0.8))
        text.draw_lines([(bx, by), (bx + bw, by), (bx + bw, by + bh),
                         (bx, by + bh), (bx, by)], (*_S.LINE_COL, 1.0), 1.0)
        text.draw_text(bx + 10, by + 4, cam, VALUE_COL, SMALL_SIZE)

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
        """One battery row of the expanded board (mock 07): the name +
        pooled magazine on the left, TUBE boxes (the spec §5 tube-cell
        recipe via _tube_boxes) on the right.  OWN-FORCE only; no contact
        reads."""
        text = self.text
        small_h = text.line_height(SMALL_SIZE)
        text.draw_text(x, y, bat["name"], VALUE_COL, SMALL_SIZE)
        pool = bat["pool_text"]
        if pool is not None:
            ptxt = pool
            if bat["refill_left"] > 0.0:
                ptxt += f"  RLDG {int(np.ceil(bat['refill_left'] - 1e-9))}s"
            text.draw_text(x, y + small_h + TUBE_LABEL_GAP, ptxt,
                           bat["pool_col"], SMALL_SIZE)
        # Tube boxes, right of the name column (READY is the own-force
        # LOADED token in SEMANTIC_COLORS; per-tube reload frac is unknown
        # here so the box shows RLD without a progress strip).
        cells = [(str(i + 1), "READY" if s == "LOADED" else s, 0.0)
                 for i, (s, _left) in enumerate(bat["tubes"])]
        self._tube_boxes(x + BPANEL_NAME_W, y, row_w - BPANEL_NAME_W, cells,
                         small_h + 10)

    def _controls_overlay(self, sandbox, w: int, h: int) -> None:
        """F1 (mock 10): centered corner-ticked panel listing every binding
        straight from the live table, in TWO columns split at a group
        boundary — the one-column list outgrew 1080p as milestones added
        bindings.  Sim keeps running (overlay, not menu)."""
        text = self.text
        rows = overlay_rows(sandbox.app.keybinds)
        head_h = text.line_height(HEADER_SIZE)
        small_h = text.line_height(SMALL_SIZE)
        body_h = text.line_height(BODY_SIZE)
        # Split ONLY at a group header, minimizing column imbalance.
        header_idx = [i for i, r in enumerate(rows) if r[0] == "header"]
        split = min(header_idx[1:] or [len(rows)],
                    key=lambda i: abs(i - len(rows) / 2))
        cols = (rows[:split], rows[split:])
        content_h = max(len(c) for c in cols) * OVERLAY_ROW_H
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
        close_w = text.text_width("F1 CLOSE", SMALL_SIZE)
        text.draw_text(x + OVERLAY_W - PANEL_PAD - close_w,
                       ty + (head_h - small_h), "F1 CLOSE", _S.FAINT,
                       SMALL_SIZE)
        ty += head_h + 4
        draw_header_rule(text, tx, ty, OVERLAY_W - 2 * PANEL_PAD)
        top = ty + HEADER_GAP
        col_w = (OVERLAY_W - 2 * PANEL_PAD - OVERLAY_COL_GAP) // 2
        for ci, col in enumerate(cols):
            cx = tx + ci * (col_w + OVERLAY_COL_GAP)
            cy = top
            for row in col:
                if row[0] == "header":
                    text.draw_text(cx, cy + (OVERLAY_ROW_H - small_h) // 2,
                                   row[1], ACCENT_DIM, SMALL_SIZE)
                else:
                    _, label, key = row
                    oy = cy + (OVERLAY_ROW_H - body_h) // 2
                    text.draw_text(cx, oy, label, MUTED)
                    kw = text.text_width(key)
                    text.draw_text(cx + col_w - kw, oy, key, TEXT_COL)
                cy += OVERLAY_ROW_H
        fy = top + content_h
        fw = text.text_width(OVERLAY_FOOTER, SMALL_SIZE)
        text.draw_text(x + (OVERLAY_W - fw) // 2, fy + 8, OVERLAY_FOOTER,
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
