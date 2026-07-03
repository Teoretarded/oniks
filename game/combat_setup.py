"""CombatSetupState: the four-page setup screen before a COMBAT session (Phase 7).

Visual language matches SettingsState/MenuState (game/states.py): corner-tick
panel, amber header rule, 40 px rows with label-left/value-right, selected-row
highlight with 3 px left focus bar, 80 ms press-flash on START, footer hints.

Four pages cycled with TAB (every built CombatConfig feature is reachable here
-- a feature the setup screen hides is dead content):
    World   -- SEED/MAP + the player's force mix (radars, drones, EW pod,
               TELs, CBR, decoys).
    Enemy   -- the opposing force mix (fleet classes, transports, submarines,
               AWACS, escort jammers, coastal radars).
    Armory  -- offensive ammo: Oniks/Zircon/ASBM/Kh-31P pools + swarm pods.
    Defense -- defensive ammo: S-300 / Pantsir / Buk pools + sonobuoys + ASW.

Navigation:
    UP/DN   move selection
    LEFT/RT adjust stepper value (+/- 1 for counts, +/- 5 s for reloads)
    TAB     switch page
    ENTER   START (bottom row of each page, or press on the START sentinel)
    ESC     back to main menu (no confirm -- no session data exists yet)

Seed editing:
    Typing digits 0-9 while the seed row is focused appends to a digit
    buffer; ENTER commits, BACKSPACE erases, ESC cancels.  A dedicated R key
    advances a deterministic LCG counter -- no host RNG, no wall-clock.

All input logic runs headless; GL/text is deferred to enter()/render().
"""

from __future__ import annotations

from typing import Callable

import pygame

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    ACCENT, BELIEF, BG0, BG2, DANGER, DISABLED, FAINT, FOCUS_BAR_W,
    LINE_COL, MUTED, OK_COL, PAD, PRESS_FLASH_S, ROW_DIVIDER, ROW_H,
    TEXT_COL, GameState, draw_brass_key, draw_hint_bar, draw_panel,
    draw_plate_header, move_selection,
)
from world.combat_config import (
    CombatConfig,
    CLAMP_AAW, CLAMP_AMMO, CLAMP_ARM_AMMO, CLAMP_ASBM_AMMO, CLAMP_ASW_AMMO,
    CLAMP_AWACS, CLAMP_BUK, CLAMP_CBR, CLAMP_CORNER_REFLECTORS,
    CLAMP_DECOYS, CLAMP_DESTROYERS, CLAMP_DRONES, CLAMP_ENEMY_RADARS,
    CLAMP_FLAGSHIP, CLAMP_GROUND_ATTACK, CLAMP_GUN_AMMO, CLAMP_JAMMERS,
    CLAMP_MAP_PRESET, CLAMP_ONIKS, CLAMP_PANTSIR, CLAMP_PLAYER_JAMMER,
    CLAMP_PLAYER_RADARS, CLAMP_RELOAD_S, CLAMP_S300, CLAMP_SONOBUOYS,
    CLAMP_SUB_KALIBR, CLAMP_SUBS, CLAMP_SWARM_CELLS, CLAMP_SWARM_PODS,
    CLAMP_TRANSPORTS, MAP_PRESET_NAMES, clamp_config,
)

# --- Layout (Wardroom Dusk, mock 03: 2-column grouped plates) -------------------

SETUP_CONTENT_W = 1160   # centered content column (tab rail + plate grid)
GRID_GAP = 20            # px between plate columns / stacked plates
START_KEY_W = 420        # centered brass START key
START_KEY_H = 46
TAB_RAIL_BG = (0.063, 0.090, 0.102)      # #10171A rail field behind the tabs
CHIP_DECEPTION = (0.788, 0.651, 0.910)   # #C9A6E8 (mock 03 group-identity chip)
SETUP_FOOTER = ("UP/DN SELECT   LT/RT ADJUST   TAB PAGE   "
                "ENTER START   R RANDOMIZE SEED   ESC BACK")
START_KEY_LABEL = "ENTER > START BATTLE"

# Deterministic LCG for seed randomisation (Numerical Recipes constants).
# No host RNG, no wall-clock: same sequence from the same starting counter.
_LCG_A   = 1664525
_LCG_C   = 1013904223
_LCG_MOD = 2 ** 32
_SEED_MAX = 2 ** 31 - 1

# Page indices (TAB cycles 0 -> 1 -> 2 -> 3 -> 0)
_PAGE_WORLD   = 0
_PAGE_ENEMY   = 1
_PAGE_ARMORY  = 2
_PAGE_DEFENSE = 3
_PAGE_NAMES   = ("WORLD", "ENEMY", "ARMORY", "DEFENSE")

# Sentinel string: selecting this row fires START.
_START = "START"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# Row descriptors --------------------------------------------------------------
# Each dict:
#   kind:   "stepper" | "fixed" | "seed" | "action"
#   label:  display string (left side)
#   field:  CombatConfig field name (steppers / seed)
#   step:   increment per LEFT/RIGHT press
#   lo/hi:  per-row clamp bounds

_WORLD_ROWS = [
    {"kind": "seed",    "label": "SEED",          "field": "seed"},
    # M3-F4 map preset: a cyclic stepper (clamped to CLAMP_MAP_PRESET, no wrap
    # past the bounds like every other stepper) whose VALUE is the preset
    # index but whose DISPLAY is MAP_PRESET_NAMES[value] (the ``names`` key
    # routes the stepper draw to the name). Default 0 (OPEN SEA) keeps the
    # out-of-the-box battle map byte-identical.
    {"kind": "stepper", "label": "MAP",           "field": "map_preset",
     "step": 1, "lo": CLAMP_MAP_PRESET[0], "hi": CLAMP_MAP_PRESET[1],
     "names": MAP_PRESET_NAMES},
    {"kind": "stepper", "label": "PLAYER RADARS", "field": "n_player_radars",
     "step": 1, "lo": CLAMP_PLAYER_RADARS[0], "hi": CLAMP_PLAYER_RADARS[1]},
    {"kind": "stepper", "label": "RECON DRONES",  "field": "n_drones",
     "step": 1, "lo": CLAMP_DRONES[0],        "hi": CLAMP_DRONES[1]},
    # M3-F4 drone EW pod: 0 = no pod (byte-identical default), 1 = the drone
    # carries the self-protect/escort jammer the JAM key toggles.
    {"kind": "stepper", "label": "DRONE EW POD",  "field": "player_jammer",
     "step": 1, "lo": CLAMP_PLAYER_JAMMER[0], "hi": CLAMP_PLAYER_JAMMER[1],
     "names": ("NONE", "FITTED")},
    # LAUNCHERS plate order per mock 03: strike first, then the SAM ladder.
    {"kind": "stepper", "label": "ONIKS TELs",    "field": "n_oniks",
     "step": 1, "lo": CLAMP_ONIKS[0],         "hi": CLAMP_ONIKS[1]},
    {"kind": "stepper", "label": "S-300 TELs",    "field": "n_s300",
     "step": 1, "lo": CLAMP_S300[0],          "hi": CLAMP_S300[1]},
    {"kind": "stepper", "label": "PANTSIR TELs",  "field": "n_pantsir",
     "step": 1, "lo": CLAMP_PANTSIR[0],       "hi": CLAMP_PANTSIR[1]},
    # M5 Buk mid-SAM: floor 0 (CLAMP_BUK) so leaving it at 0 keeps the Buk OFF
    # and the default battle byte-identical; a non-zero count builds the
    # gap-filler battery + its 9S36 radar and unlocks the buk TAB platform.
    {"kind": "stepper", "label": "BUK TELs",      "field": "n_buk",
     "step": 1, "lo": CLAMP_BUK[0],           "hi": CLAMP_BUK[1]},
    # M5 counter-battery radar + ESM decoys + corner reflectors: the player's
    # survivability toys vs the enemy back-plot (all 0/OFF by default).
    {"kind": "stepper", "label": "CB RADARS",     "field": "n_cbr",
     "step": 1, "lo": CLAMP_CBR[0],           "hi": CLAMP_CBR[1]},
    {"kind": "stepper", "label": "ESM DECOYS",    "field": "n_decoys",
     "step": 1, "lo": CLAMP_DECOYS[0],        "hi": CLAMP_DECOYS[1]},
    {"kind": "stepper", "label": "CORNER REFLECTORS", "field": "n_corner_reflectors",
     "step": 1, "lo": CLAMP_CORNER_REFLECTORS[0],
     "hi": CLAMP_CORNER_REFLECTORS[1]},
    {"kind": "action",  "label": _START},
]

_ENEMY_ROWS = [
    {"kind": "fixed",   "label": "CARRIER",       "value": "1  (FIXED)"},
    {"kind": "stepper", "label": "DESTROYERS",    "field": "n_destroyers",
     "step": 1, "lo": CLAMP_DESTROYERS[0],    "hi": CLAMP_DESTROYERS[1]},
    # M5 ship classes (0/OFF default): the CEC flagship datalink hub, the
    # dedicated AAW screen and the ground-attack (land-strike magazine) hulls.
    {"kind": "stepper", "label": "FLAGSHIP (CEC)", "field": "n_flagship",
     "step": 1, "lo": CLAMP_FLAGSHIP[0],      "hi": CLAMP_FLAGSHIP[1]},
    {"kind": "stepper", "label": "AAW DESTROYERS", "field": "n_aaw",
     "step": 1, "lo": CLAMP_AAW[0],           "hi": CLAMP_AAW[1]},
    {"kind": "stepper", "label": "GROUND-ATTACK",  "field": "n_ground_attack",
     "step": 1, "lo": CLAMP_GROUND_ATTACK[0], "hi": CLAMP_GROUND_ATTACK[1]},
    # M5 amphibious group: transports + LCACs; a landed beachhead starts the
    # TIMED second lose-path (beachhead grace clock).
    {"kind": "stepper", "label": "TRANSPORTS",    "field": "n_transports",
     "step": 1, "lo": CLAMP_TRANSPORTS[0],    "hi": CLAMP_TRANSPORTS[1]},
    # M5 submarines: the acoustic-only threat (find with sonobuoys on the
    # DEFENSE page, kill with ASW rounds).
    {"kind": "stepper", "label": "SUBMARINES",    "field": "n_subs",
     "step": 1, "lo": CLAMP_SUBS[0],          "hi": CLAMP_SUBS[1]},
    {"kind": "stepper", "label": "SUB KALIBR AMMO", "field": "sub_kalibr_ammo",
     "step": 1, "lo": CLAMP_SUB_KALIBR[0],    "hi": CLAMP_SUB_KALIBR[1]},
    {"kind": "stepper", "label": "AWACS",         "field": "n_awacs",
     "step": 1, "lo": CLAMP_AWACS[0],         "hi": CLAMP_AWACS[1]},
    # M3-F2 escort jammers (Growlers): stand-off emitters that collapse the
    # player radar rings (counter: ELINT still hears them; burn-through).
    {"kind": "stepper", "label": "ESCORT JAMMERS", "field": "n_jammers",
     "step": 1, "lo": CLAMP_JAMMERS[0],       "hi": CLAMP_JAMMERS[1]},
    {"kind": "stepper", "label": "ENEMY RADARS",  "field": "n_enemy_radars",
     "step": 1, "lo": CLAMP_ENEMY_RADARS[0],  "hi": CLAMP_ENEMY_RADARS[1]},
    {"kind": "action",  "label": _START},
]

_ARMORY_ROWS = [
    {"kind": "stepper", "label": "ONIKS  AMMO",
     "field": "oniks_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "ONIKS  RELOAD (s)",
     "field": "oniks_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    # Zircon: the scarce hypersonic pool the B key cycles to (floor 1 via the
    # shared missile clamp -- it has always shipped >= 1).
    {"kind": "stepper", "label": "ZIRCON AMMO",
     "field": "zircon_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    # M4 Bastion-K ASBM (0/OFF default): lofted top-attack rounds that beat
    # the SAM ceiling instead of the horizon.
    {"kind": "stepper", "label": "ASBM AMMO",
     "field": "asbm_ammo",
     "step": 1,  "lo": CLAMP_ASBM_AMMO[0], "hi": CLAMP_ASBM_AMMO[1]},
    # M2-T4: the player Kh-31P anti-radiation pool. Floor is 0 (CLAMP_ARM_AMMO,
    # NOT CLAMP_AMMO) so leaving it at 0 keeps the ARM OFF and the default
    # battle byte-identical; a non-zero stock unlocks launch_arm() + the 3-way
    # B weapon cycle. Ships with the coastal strike battery (Bastion-launched).
    {"kind": "stepper", "label": "KH-31P AMMO",
     "field": "kh31p_ammo",
     "step": 1,  "lo": CLAMP_ARM_AMMO[0], "hi": CLAMP_ARM_AMMO[1]},
    # M4 loitering swarm (0/OFF default): pods of slow loiterers with a
    # simultaneous time-on-target arrival solver (H cycles arrival mode).
    {"kind": "stepper", "label": "SWARM PODS",
     "field": "n_swarm_pods",
     "step": 1,  "lo": CLAMP_SWARM_PODS[0], "hi": CLAMP_SWARM_PODS[1]},
    {"kind": "stepper", "label": "SWARM CELLS/POD",
     "field": "swarm_cells_per_pod",
     "step": 1,  "lo": CLAMP_SWARM_CELLS[0], "hi": CLAMP_SWARM_CELLS[1]},
    {"kind": "action",  "label": _START},
]

_DEFENSE_ROWS = [
    {"kind": "stepper", "label": "S-300  48N6 AMMO",
     "field": "s300_48n6_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "S-300  40N6 AMMO",
     "field": "s300_40n6_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "S-300  RELOAD (s)",
     "field": "s300_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    {"kind": "stepper", "label": "PANTSIR  57E6 AMMO",
     "field": "pantsir_57e6_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "PANTSIR  GUN AMMO",
     "field": "pantsir_gun_ammo",
     "step": 10, "lo": CLAMP_GUN_AMMO[0], "hi": CLAMP_GUN_AMMO[1]},
    {"kind": "stepper", "label": "PANTSIR  RELOAD (s)",
     "field": "pantsir_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    # M5 Buk pools + reload (only effective when n_buk > 0; the pools use the
    # shared missile CLAMP_AMMO, the reload the shared CLAMP_RELOAD_S).
    {"kind": "stepper", "label": "BUK  9M317 AMMO",
     "field": "buk_9m317_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "BUK  9M338 AMMO",
     "field": "buk_9m338_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "BUK  RELOAD (s)",
     "field": "buk_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    # M5 ASW: passive sonobuoys (LMB-drop once the UI pass lands; the world
    # verb place_sonobuoy already consumes this stock) + ASROC-class rounds.
    {"kind": "stepper", "label": "SONOBUOYS",
     "field": "n_sonobuoys",
     "step": 1,  "lo": CLAMP_SONOBUOYS[0], "hi": CLAMP_SONOBUOYS[1]},
    {"kind": "stepper", "label": "ASW ROUNDS",
     "field": "asw_ammo",
     "step": 1,  "lo": CLAMP_ASW_AMMO[0], "hi": CLAMP_ASW_AMMO[1]},
    {"kind": "action",  "label": _START},
]

_PAGES = (_WORLD_ROWS, _ENEMY_ROWS, _ARMORY_ROWS, _DEFENSE_ROWS)

# Grouped plates (Wardroom Dusk, mock 03): per page, (title, chip color,
# row count) — consecutive slices of the page's row list, START excluded.
# Chip families follow the mock + color law: brass = the session plate,
# teal = sensors/belief hardware, green = own-force trucks, dusk-red = the
# threat axis (every ENEMY group), lavender = the deception identity chip.
# Groups fill the 2-column grid in order (left, right, left, ...).
_PAGE_GROUPS = (
    (("WORLD", ACCENT, 2), ("RECON", BELIEF, 3),
     ("LAUNCHERS", OK_COL, 4), ("DECEPTION", CHIP_DECEPTION, 3)),
    (("FLEET", DANGER, 5), ("AMPHIB + UNDERSEA", DANGER, 3),
     ("AIR + EW", DANGER, 2), ("GROUND SENSORS", DANGER, 1)),
    (("CRUISE MISSILES", ACCENT, 3), ("STANDOFF + SEAD", ACCENT, 2),
     ("LOITERING SWARM", ACCENT, 2)),
    (("S-300 BATTERY", ACCENT, 3), ("PANTSIR PD", ACCENT, 3),
     ("BUK BATTERY", ACCENT, 3), ("ASW", BELIEF, 2)),
)

# Parity guard (import-time): every non-START row belongs to exactly one
# group — a page edit that forgets the group table fails fast, not silently.
for _pg, _prows in zip(_PAGE_GROUPS, _PAGES):
    assert sum(n for _, _, n in _pg) == len(_prows) - 1, \
        "group row counts must cover every row except START"


class CombatSetupState(GameState):
    """Two-page setup screen for configuring a COMBAT session.

    ``start_cb`` is called with a fully-built, clamped CombatConfig when the
    player confirms START (after the 80 ms press-flash).  The integrator
    wires this to app.start_combat(config).

    All input / state runs headless; GL is deferred to enter()/render().
    """

    def __init__(self, app, start_cb: Callable[[CombatConfig], None]):
        super().__init__(app)
        self._gl = None
        self.text = None
        self.start_cb = start_cb

        # Mutable mirror of CombatConfig fields; floats stay float.  Derived
        # from the row tables so a page row can never reference a field this
        # dict (or build_config) forgot -- one source of truth, no drift.
        defaults = CombatConfig()
        self._fields: dict[str, int | float] = {
            row["field"]: getattr(defaults, row["field"])
            for page in _PAGES for row in page
            if row.get("kind") in ("stepper", "seed")
        }

        self._page: int = _PAGE_WORLD
        self._sel:  int = 0

        # Press-flash before firing START
        self._pending:      bool  = False
        self._pending_left: float = 0.0

        # Deterministic seed LCG: counter only, no host RNG / wall-clock.
        self._lcg_state: int = 0

        # Digit buffer for seed row entry
        self._seed_editing: bool = False
        self._seed_digits:  str  = ""

        # Per-render hit rectangles: [(row_index, (x0, y0, x1, y1))]
        self._hit_rects: list = []

    # ------------------------------------------------------------------ enter

    def enter(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl
            self._gl = gl
            self.text = self.app.ui_text()
        self._sel = 0
        self._pending = False
        self._pending_left = 0.0
        self._hit_rects = []

    def effective_time_scale(self) -> float:
        return 0.0   # setup screen freezes the sim

    # ------------------------------------------------------------------ helpers

    def _rows(self) -> list:
        return _PAGES[self._page]

    def _row_count(self) -> int:
        return len(self._rows())

    def _current_row(self) -> dict:
        return self._rows()[self._sel]

    # ------------------------------------------------------------------ LCG

    def _advance_lcg(self) -> int:
        """One deterministic LCG step; returns a seed value in [0, 2^31-1]."""
        self._lcg_state = (self._lcg_state * _LCG_A + _LCG_C) % _LCG_MOD
        return self._lcg_state & _SEED_MAX

    # ------------------------------------------------------------------ input

    def handle_event(self, ev) -> None:
        if self._pending:
            return   # press-flash in progress; all input off
        if ev.type == pygame.KEYDOWN:
            self._handle_key(ev.key, ev.unicode)
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None and hit != self._sel:
                self._sel = hit
                self._cancel_seed_edit()
                self.app.audio.ui_click()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self._sel = hit
                self._activate_current()

    def _handle_key(self, key: int, unicode: str) -> None:
        row = self._current_row()

        # --- Digit mode: seed row is accepting typed digits ---
        if self._seed_editing and row.get("kind") == "seed":
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._commit_seed_digits()
                return
            if key == pygame.K_ESCAPE:
                self._cancel_seed_edit()
                return
            if key == pygame.K_BACKSPACE:
                self._seed_digits = self._seed_digits[:-1]
                return
            if unicode and unicode.isdigit() and len(self._seed_digits) < 10:
                self._seed_digits += unicode
                return
            # Any other key while editing: ignore
            return

        # --- Normal navigation ---
        if key == pygame.K_UP:
            self._sel = move_selection(self._sel, -1, self._row_count())
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        elif key == pygame.K_DOWN:
            self._sel = move_selection(self._sel, 1, self._row_count())
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        elif key == pygame.K_TAB:
            self._page = (self._page + 1) % len(_PAGES)
            self._sel = 0
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        elif key == pygame.K_ESCAPE:
            self._back()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._activate_current()
        elif key == pygame.K_LEFT:
            self._adjust(-1)
        elif key == pygame.K_RIGHT:
            self._adjust(1)
        elif key == pygame.K_r:
            # Randomize seed (on any page -- user may trigger from armory too)
            self._fields["seed"] = self._advance_lcg()
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        else:
            # Start digit capture when a digit is typed on the seed row
            if row.get("kind") == "seed" and unicode and unicode.isdigit():
                self._seed_editing = True
                self._seed_digits = unicode
                self.app.audio.ui_click()

    def _adjust(self, direction: int) -> None:
        """LEFT/RIGHT: step the focused row's value."""
        row = self._current_row()
        kind = row.get("kind")
        if kind == "stepper":
            field = row["field"]
            v = self._fields[field] + row["step"] * direction
            self._fields[field] = _clamp(v, row["lo"], row["hi"])
            self.app.audio.ui_click()
        elif kind == "seed":
            v = int(self._fields["seed"]) + direction
            self._fields["seed"] = _clamp(v, 0, _SEED_MAX)
            self.app.audio.ui_click()

    def _activate_current(self) -> None:
        row = self._current_row()
        kind = row.get("kind")
        if kind == "action" and row["label"] == _START:
            self.app.audio.ui_click()
            self._pending = True
            self._pending_left = PRESS_FLASH_S
        elif kind == "seed":
            # Toggle digit-entry mode on ENTER
            if self._seed_editing:
                self._commit_seed_digits()
            else:
                self._seed_editing = True
                self._seed_digits = ""
            self.app.audio.ui_click()

    def _commit_seed_digits(self) -> None:
        if self._seed_digits:
            v = int(self._seed_digits)
            self._fields["seed"] = _clamp(v, 0, _SEED_MAX)
        self._seed_editing = False
        self._seed_digits = ""

    def _cancel_seed_edit(self) -> None:
        self._seed_editing = False
        self._seed_digits = ""

    def _back(self) -> None:
        self._cancel_seed_edit()
        self.app.states.switch(self.app.menu)

    def _hit(self, pos) -> int | None:
        for i, (x0, y0, x1, y1) in self._hit_rects:
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return i
        return None

    # ------------------------------------------------------------------ tick

    def _tick_pending(self, dt: float) -> None:
        if not self._pending:
            return
        self._pending_left -= dt
        if self._pending_left <= 0.0:
            self._pending = False
            self.start_cb(self.build_config())

    # ------------------------------------------------------------------ config

    def build_config(self) -> CombatConfig:
        """Return a clamped CombatConfig from the current field state.

        Every screen-managed field is forwarded (float fields stay float --
        the CombatConfig default declares each field's type); unmanaged
        fields keep their CombatConfig defaults via clamp_config."""
        defaults = CombatConfig()
        kwargs = {}
        for field, v in self._fields.items():
            kwargs[field] = (float(v)
                             if isinstance(getattr(defaults, field), float)
                             else int(v))
        return clamp_config(**kwargs)

    # ------------------------------------------------------------------ render

    def render(self, dt_real: float) -> None:
        self._tick_pending(dt_real)
        gl = self._gl
        gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        w, h = self.app.window.size()
        text = self.text
        x = (w - SETUP_CONTENT_W) // 2
        self._hit_rects = []

        head_lh  = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh  = text.line_height(BODY_SIZE)

        # --- Header (mock 03): cream 'COMBAT SETUP' + dim slash + brass page
        # name; 'PAGE n / 4' right-aligned in faint.
        page_name = _PAGE_NAMES[self._page]
        hx = x
        text.draw_text(hx, 40, "COMBAT SETUP", TEXT_COL, HEADER_SIZE)
        hx += text.text_width("COMBAT SETUP", HEADER_SIZE) + 12
        text.draw_text(hx, 40, "/", DISABLED, HEADER_SIZE)
        hx += text.text_width("/", HEADER_SIZE) + 12
        text.draw_text(hx, 40, page_name, ACCENT, HEADER_SIZE)
        page_no = f"PAGE {self._page + 1} / {len(_PAGES)}"
        text.draw_text(x + SETUP_CONTENT_W - text.text_width(page_no, SMALL_SIZE),
                       40 + head_lh - small_lh, page_no, FAINT, SMALL_SIZE)

        # --- Tab rail: contiguous boxed tabs on a darker rail; the active tab
        # carries the plate-selected fill + a 3px brass bar along its bottom.
        rail_y = 40 + head_lh + 12
        rail_h = small_lh + 18
        tab_w = SETUP_CONTENT_W / len(_PAGE_NAMES)
        text.draw_rect(x, rail_y, SETUP_CONTENT_W, rail_h, (*TAB_RAIL_BG, 1.0))
        for i, name in enumerate(_PAGE_NAMES):
            tx0 = round(x + i * tab_w)
            if i:
                text.draw_lines([(tx0, rail_y), (tx0, rail_y + rail_h)],
                                (*LINE_COL, 1.0), 1.0)
            active = (i == self._page)
            if active:
                text.draw_rect(tx0, rail_y, round(tab_w), rail_h, (*BG2, 1.0))
                text.draw_rect(tx0, rail_y + rail_h - 3, round(tab_w), 3,
                               (*ACCENT, 1.0))
            tw = text.text_width(name, SMALL_SIZE)
            text.draw_text(round(tx0 + (tab_w - tw) / 2),
                           rail_y + (rail_h - small_lh) // 2, name,
                           ACCENT if active else MUTED, SMALL_SIZE)
        text.draw_lines([(x, rail_y), (x + SETUP_CONTENT_W, rail_y),
                         (x + SETUP_CONTENT_W, rail_y + rail_h),
                         (x, rail_y + rail_h), (x, rail_y)],
                        (*LINE_COL, 1.0), 1.0)

        # --- Grouped plates: the 2-column grid; groups land left/right in
        # order and each column stacks independently (mock 03).
        rows = self._rows()
        grid_y = rail_y + rail_h + GRID_GAP
        col_w = (SETUP_CONTENT_W - GRID_GAP) // 2
        col_y = [grid_y, grid_y]
        idx = 0
        for gi, (title, chip, n) in enumerate(_PAGE_GROUPS[self._page]):
            gcol = gi % 2
            gx = x + gcol * (col_w + GRID_GAP)
            gy = col_y[gcol]
            head_band = 12 + small_lh + 7      # top pad + chip label + rule
            plate_h = head_band + n * ROW_H + 8
            draw_panel(text, gx, gy, col_w, plate_h, ticks=False)
            draw_plate_header(text, gx + PAD, gy + 12, col_w - 2 * PAD,
                              title, chip)
            ry = gy + head_band
            for k in range(n):
                if k:
                    text.draw_lines([(gx + PAD, ry), (gx + col_w - PAD, ry)],
                                    (*ROW_DIVIDER, 1.0), 1.0)
                self._draw_row(rows[idx], idx, gx + 1, ry, col_w - 2, body_lh)
                ry += ROW_H
                idx += 1
            col_y[gcol] = gy + plate_h + GRID_GAP

        # --- START: the centered brass key below the grid (mock 03); PRESS
        # inverts the key for the 80 ms flash.
        start_idx = len(rows) - 1
        key_y = max(col_y) + 4
        kx = x + (SETUP_CONTENT_W - START_KEY_W) // 2
        draw_brass_key(text, kx, key_y, START_KEY_W, START_KEY_H,
                       START_KEY_LABEL, focused=(self._sel == start_idx),
                       pressed=self._pending)
        self._hit_rects.append((start_idx, (kx, key_y, kx + START_KEY_W,
                                            key_y + START_KEY_H)))

        # --- Hint bar ---------------------------------------------------------
        draw_hint_bar(text, w, h, SETUP_FOOTER)
        text.flush(w, h)

    def _draw_row(self, row: dict, idx: int, x: int, y: int, w: int,
                  body_lh: int) -> None:
        """One plate row: full-plate-width focus fill + 3px brass bar, label
        at x+PAD, value right-aligned.  A zero/OFF stepper reads DISABLED at
        rest (mock 03) so an unfitted feature is visibly off."""
        text  = self.text
        kind  = row.get("kind")
        selected = (idx == self._sel)
        label = row["label"]

        if selected:
            text.draw_rect(x, y, w, ROW_H, (*BG2, 1.0))
            text.draw_rect(x, y, FOCUS_BAR_W, ROW_H, (*ACCENT, 1.0))

        label_col = ACCENT if selected else MUTED
        ty = y + (ROW_H - body_lh) // 2

        if kind == "fixed":
            text.draw_text(x + PAD, ty, label, MUTED)
            val = row.get("value", "")
            vw  = text.text_width(val)
            text.draw_text(x + w - PAD - vw, ty, val, DISABLED)

        elif kind == "seed":
            text.draw_text(x + PAD, ty, label, label_col)
            if self._seed_editing and selected:
                display  = (self._seed_digits + "_") if self._seed_digits else "_"
                val_col  = ACCENT
            elif selected:
                display  = f"< {int(self._fields['seed'])} >"
                val_col  = ACCENT
            else:
                display  = str(int(self._fields["seed"]))
                val_col  = TEXT_COL
            vw = text.text_width(display)
            text.draw_text(x + w - PAD - vw, ty, display, val_col)

        elif kind == "stepper":
            text.draw_text(x + PAD, ty, label, label_col)
            field = row["field"]
            v     = self._fields[field]
            names = row.get("names")
            if names is not None:
                # Enum stepper (e.g. MAP): the value indexes a names table.
                vi = int(v)
                val_str = names[vi] if 0 <= vi < len(names) else str(vi)
            # Whole-number floats (reload multiples of 5 s): show as int
            elif isinstance(v, float) and v == int(v):
                val_str = str(int(v))
            elif isinstance(v, float):
                val_str = f"{v:.1f}"
            else:
                val_str = str(v)
            if selected:
                display, val_col = f"< {val_str} >", ACCENT
            else:
                display = val_str
                # OFF/zero features read greyed so the ON set pops (mock 03).
                val_col = DISABLED if val_str in ("0", "NONE") else TEXT_COL
            vw = text.text_width(display)
            text.draw_text(x + w - PAD - vw, ty, display, val_col)

        self._hit_rects.append((idx, (x, y, x + w, y + ROW_H)))
