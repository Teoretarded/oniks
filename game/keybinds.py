"""Action registry + rebindable key table + JSON persistence (Task UI).

Every player action is routed through this single action -> key table
(defaults = the bindings the game shipped with, see README). The table is
persisted as human-editable versioned JSON at %APPDATA%\\ONIKS\\settings.json
(pygame key NAME strings — they survive the ``pygame.key.key_code`` round
trip), falling back to the game directory when APPDATA is unset.

Load rules (never crash on config): unknown action ids are ignored, missing
ids fill from the defaults, an unparseable file is renamed to
``settings.json.bad`` and regenerated. Duplicate keys keep the first claimer
(registry order); the loser falls back to its default or, when that is the
disputed key itself, loads unbound (shown as ``---`` in the settings UI).

ESC and F1 are RESERVED (the rebind flow itself needs them: ESC cancels a
capture, F1 must always reach the controls overlay) — their rows show in the
settings list but refuse rebinds, and no other action may take their keys.

The table is kept injective (one key -> one action): a conflicting rebind is
an atomic SWAP (the other action takes this action's old key) — never a
silent unbind, never a hard block. Numpad -/+/ENTER alias to the main-row
keys via ``normalize_key`` so the time-accel keys keep working from either
cluster.

GL-free (pygame key constants/name tables only) — unit-tested headless.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pygame

SETTINGS_VERSION = 1
SETTINGS_DIR = "ONIKS"
SETTINGS_FILE = "settings.json"

# ESC cancels rebind captures and F1 is the always-available controls
# overlay: neither may be rebound nor assigned to another action.
RESERVED_KEYS = frozenset({pygame.K_ESCAPE, pygame.K_F1})

# Numpad equivalents accepted wherever the main-row key is bound.
NUMPAD_ALIASES = {
    pygame.K_KP_MINUS: pygame.K_MINUS,
    pygame.K_KP_PLUS: pygame.K_EQUALS,
    pygame.K_KP_ENTER: pygame.K_RETURN,
}


@dataclass(frozen=True)
class ActionDef:
    """One bindable action: id (persistence key), settings-row label,
    section group, default pygame key code, reserved (ESC/F1) flag."""

    id: str
    label: str
    group: str
    default: int
    reserved: bool = False


# Registry order = settings-screen / F1-overlay display order.
ACTIONS: tuple[ActionDef, ...] = (
    ActionDef("launch", "LAUNCH WEAPON", "ENGAGEMENT", pygame.K_SPACE),
    ActionDef("cycle_platform", "CYCLE PLATFORM", "ENGAGEMENT", pygame.K_TAB),
    ActionDef("map", "TACTICAL MAP", "ENGAGEMENT", pygame.K_m),
    ActionDef("profile_hi_lo", "PROFILE HI-LO", "ENGAGEMENT", pygame.K_1),
    ActionDef("profile_lo_lo", "PROFILE LO-LO", "ENGAGEMENT", pygame.K_2),
    ActionDef("clear_waypoints", "CLEAR WAYPOINTS", "ENGAGEMENT", pygame.K_x),
    # COMBAT radar silence (Phase 3): flips the player radar station's
    # emissions. R is unclaimed by every other default; in SANDBOX (no
    # radar station) the action is a graceful no-op.
    ActionDef("radar_toggle", "RADAR EMISSIONS", "ENGAGEMENT", pygame.K_r),
    # S-300 round select (Phase 5b): toggles the 48N6 <-> 40N6 round the
    # next SAM launch uses. V is unclaimed by every other default.
    ActionDef("sam_round", "S-300 ROUND SELECT", "ENGAGEMENT", pygame.K_v),
    # Oniks/Zircon select (Phase 8): B toggles the Bastion round. B is unclaimed.
    ActionDef("oniks_weapon", "ONIKS/ZIRCON SELECT", "ENGAGEMENT", pygame.K_b),
    # M4-B loitering-swarm arrival mode: H toggles SYNC (coordinated time-on-
    # target) <-> MAX (plain max-speed bundle) while the SWARM platform is
    # active.  H is unclaimed by every other default; off the swarm platform
    # the action is a graceful no-op.
    ActionDef("swarm_arrival_mode", "SWARM ARRIVAL MODE", "ENGAGEMENT",
              pygame.K_h),
    # M3-F4 drone EW pod (self-protect jammer): G toggles drone.set_jam while
    # the DRONE platform is active. G is unclaimed by every other default; in
    # SANDBOX / off the drone platform the action is a graceful no-op.
    ActionDef("jam", "DRONE EW POD", "ENGAGEMENT", pygame.K_g),
    # M6 salvo / ripple-fire: F empties all currently-ready tubes of the active
    # platform in a controlled ripple (the SM-2 saturation king move); Y cycles
    # the salvo mode RIPPLE -> FAN -> TOT.  Both keys were unclaimed by every
    # prior default.  Off a launch platform / with no aim point the action is a
    # graceful no-op (it reuses the single-fire validation).
    ActionDef("salvo_fire", "SALVO / RIPPLE FIRE", "ENGAGEMENT", pygame.K_f),
    ActionDef("salvo_mode", "SALVO MODE", "ENGAGEMENT", pygame.K_y),
    # M5 ASW (UI-wiring pass): U arms BUOY-DROP mode — the next LMB on the
    # tactical map drops a passive sonobuoy at the clicked point (finite
    # n_sonobuoys stock); K fires an ASW round at the freshest LOCALIZED
    # subsurface fix (world.launch_asw refuses blind shots).  U/K were
    # unclaimed by every prior default; with no buoy stock / no ASW ammo /
    # no fix the actions are graceful no-op hints (SANDBOX worlds too).
    ActionDef("buoy_drop", "SONOBUOY DROP (MAP)", "ENGAGEMENT", pygame.K_u),
    ActionDef("asw_launch", "ASW LAUNCH", "ENGAGEMENT", pygame.K_k),
    # M6 per-battery STATUS PANEL: toggles the EXPANDED full battery board
    # (every Oniks/S-300 tube's LOADED/RELOADING/EMPTY + the magazine pool +
    # refill timers), drawn like the F1 overlay.  Player-only own-force
    # telemetry, EXEMPT from the radar gate.  The spec proposed G, but G is now
    # claimed by the M3-F4 drone EW pod (jam); O was unclaimed by every default
    # (and F/Y are the salvo keys), so the panel binds to O.
    ActionDef("battery_panel", "BATTERY PANEL", "SIMULATION", pygame.K_o),
    # FORENSICS / SHOT DEBRIEF ledger (handoff 2026-07-03): J opens the
    # recorded-flight-path sheet in battle.  An overlay, not a menu — the sim
    # NEVER pauses under it.  J is unclaimed by every other default; in
    # SANDBOX (no flight recorder) the action is a graceful no-op.
    ActionDef("forensics", "FORENSICS / DEBRIEF", "SIMULATION", pygame.K_j),
    # M6 AUTO-TIME-WARP: T toggles event-aware auto pacing — the - / = ladder
    # sets the TARGET warp and the sim auto-drops to 1x on important events
    # (inbound detected / own terminal / intercept), then eases back.  T was
    # unclaimed by every prior default.  OFF by default -> byte-identical.
    ActionDef("auto_warp_toggle", "AUTO TIME-WARP", "SIMULATION", pygame.K_t),
    ActionDef("pause", "PAUSE SIM", "SIMULATION", pygame.K_p),
    ActionDef("frame_step", "FRAME STEP", "SIMULATION", pygame.K_n),
    ActionDef("time_down", "TIME SCALE -", "SIMULATION", pygame.K_MINUS),
    ActionDef("time_up", "TIME SCALE +", "SIMULATION", pygame.K_EQUALS),
    ActionDef("camera_mode", "CAMERA MODE", "CAMERA", pygame.K_c),
    ActionDef("subject_prev", "SUBJECT PREV", "CAMERA", pygame.K_LEFTBRACKET),
    ActionDef("subject_next", "SUBJECT NEXT", "CAMERA",
              pygame.K_RIGHTBRACKET),
    ActionDef("freecam_fwd", "FREE CAM FWD", "CAMERA", pygame.K_w),
    ActionDef("freecam_back", "FREE CAM BACK", "CAMERA", pygame.K_s),
    ActionDef("freecam_left", "FREE CAM LEFT", "CAMERA", pygame.K_a),
    ActionDef("freecam_right", "FREE CAM RIGHT", "CAMERA", pygame.K_d),
    ActionDef("freecam_up", "FREE CAM UP", "CAMERA", pygame.K_e),
    ActionDef("freecam_down", "FREE CAM DOWN", "CAMERA", pygame.K_q),
    ActionDef("screenshot", "SCREENSHOT", "SYSTEM", pygame.K_F2),
    ActionDef("controls_overlay", "CONTROLS OVERLAY", "SYSTEM", pygame.K_F1,
              reserved=True),
    ActionDef("menu", "MENU / BACK", "SYSTEM", pygame.K_ESCAPE,
              reserved=True),
)

GROUPS = ("ENGAGEMENT", "SIMULATION", "CAMERA", "SYSTEM")

_DEFS = {a.id: a for a in ACTIONS}


def normalize_key(key: int) -> int:
    """Fold numpad -/+/ENTER onto their main-row equivalents."""
    return NUMPAD_ALIASES.get(key, key)


def settings_path() -> str:
    """%APPDATA%\\ONIKS\\settings.json, or the game dir when APPDATA is
    unset (the same file will later hold audio/video settings)."""
    base = os.getenv("APPDATA") or "."
    return os.path.join(base, SETTINGS_DIR, SETTINGS_FILE)


def key_display(key: int | None) -> str:
    """UI string for a key code: pygame's name upper-cased, '---' unbound."""
    return pygame.key.name(key).upper() if key is not None else "---"


def _key_from_value(value) -> int | None:
    """A file value -> key code: a key-name string, or a list of names
    (multi-key legacy form — first valid wins). None when nothing parses."""
    names = value if isinstance(value, list) else [value]
    for name in names:
        if isinstance(name, str):
            try:
                return pygame.key.key_code(name)
            except ValueError:
                continue
    return None


class Keybinds:
    """The mutable action -> key table. Construction loads ``path`` (the
    real settings file by default); every successful mutation saves back
    immediately (no Apply button at sim-prototype scale)."""

    def __init__(self, path: str | None = None):
        self.path = path if path is not None else settings_path()
        self.keys: dict[str, int | None] = {a.id: a.default for a in ACTIONS}
        self.load()

    # -------------------------------------------------------------- lookups

    def key_for(self, action_id: str) -> int | None:
        return self.keys[action_id]

    def name_for(self, action_id: str) -> str:
        return key_display(self.keys[action_id])

    def action_for(self, key: int) -> str | None:
        key = normalize_key(key)
        for aid, k in self.keys.items():
            if k == key:
                return aid
        return None

    def matches(self, action_id: str, key: int) -> bool:
        return self.keys[action_id] == normalize_key(key)

    def conflict(self, action_id: str, key: int) -> str | None:
        """The OTHER action currently holding ``key`` (None when free or
        when ``action_id`` itself already owns it)."""
        other = self.action_for(key)
        return other if other is not None and other != action_id else None

    def rows(self) -> list[tuple[ActionDef, int | None]]:
        """(ActionDef, key) in registry order — drives the settings list
        and the F1 overlay (generated live, so it can never lie)."""
        return [(a, self.keys[a.id]) for a in ACTIONS]

    # -------------------------------------------------------------- rebinds

    def rebind(self, action_id: str, key: int) -> bool:
        """Bind ``action_id`` to ``key``; a conflicting action atomically
        takes this action's old key (swap). False = refused (reserved
        action, or reserved key). Saves on success."""
        if _DEFS[action_id].reserved:
            return False
        key = normalize_key(key)
        if key in RESERVED_KEYS:
            return False
        other = self.action_for(key)
        if other == action_id:
            return True                       # no-op: already bound
        if other is not None:
            self.keys[other] = self._displaced_key(action_id, other)
        self.keys[action_id] = key
        self.save()
        return True

    def _displaced_key(self, action_id: str, other: str) -> int | None:
        """The key ``other`` receives when ``action_id`` takes its key.
        Normally the plain swap (this action's old key) — but when the old
        key is None (an UNBOUND row), a bare swap silently unbound ``other``
        in violation of the injective-swap contract; fall back to ``other``'s
        default when that key is free, else honestly None."""
        old = self.keys[action_id]
        if old is not None:
            return old
        default = _DEFS[other].default
        return default if self.action_for(default) is None else None

    def reset_row(self, action_id: str) -> None:
        """R on a settings row: back to the default, swapping with whoever
        holds that default now (the table stays injective)."""
        default = _DEFS[action_id].default
        if self.keys[action_id] == default:
            return
        other = self.action_for(default)
        if other is not None and other != action_id:
            self.keys[other] = self._displaced_key(action_id, other)
        self.keys[action_id] = default
        self.save()

    def reset_all(self) -> None:
        self.keys = {a.id: a.default for a in ACTIONS}
        self.save()

    # ---------------------------------------------------------- persistence

    def load(self) -> None:
        """Read ``self.path``; never crashes on config (see module doc)."""
        self.keys = {a.id: a.default for a in ACTIONS}
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            bindings = data["bindings"]
            if not isinstance(bindings, dict):
                raise ValueError("bindings is not a table")
        except (OSError, ValueError, KeyError, TypeError):
            try:                              # quarantine + regenerate
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            self.save()
            return
        wanted: dict[str, int | None] = {}
        for a in ACTIONS:                     # unknown ids simply ignored
            raw = bindings.get(a.id)
            if raw == "UNBOUND" and not a.reserved:
                wanted[a.id] = None           # an explicit unbind persists
                continue
            key = _key_from_value(raw)
            if a.reserved or key is None or key in RESERVED_KEYS:
                key = a.default               # reserved rows stay pinned
            wanted[a.id] = key
        taken: set[int] = set()
        for a in ACTIONS:                     # duplicate keys: first claimer
            key = wanted[a.id]
            if key in taken:
                key = a.default if a.default not in taken else None
            if key is not None:
                taken.add(key)
            self.keys[a.id] = key

    def save(self) -> None:
        # An unbound row is written as the explicit "UNBOUND" sentinel —
        # omitting it made the row silently revert to its default on the
        # next launch (older loaders read the sentinel as a bad value and
        # fall back to the default, so the file stays backward-compatible).
        bindings = {aid: (pygame.key.name(k) if k is not None else "UNBOUND")
                    for aid, k in self.keys.items()}
        payload = {"version": SETTINGS_VERSION, "bindings": bindings}
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except OSError:
            pass                              # read-only disk: play on
