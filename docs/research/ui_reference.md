# ONIKS — In-Game UI Design Direction & Reference Report

Date: 2026-06-11
Scope: main menu, pause menu, settings/keybinds, in-game HUD affordances.
Hard constraint: OpenGL overlay pass with a monospace glyph atlas (Consolas bold), `draw_text` / `draw_rect` / `draw_lines` only — no images, no gradients. Everything below is achievable with text, 1px lines, axis-aligned rects, and flat fills.

Reference games surveyed: Nuclear Option, DCS World, HighFleet, Carrier Command 2, Stormworks/Sprocket, plus general military-FUI references.

---

## 0. What the references actually do (research notes)

**Nuclear Option** (the primary north star — same low-poly + clean overlay philosophy). Its presentation is "realistic physics + low-poly stylised visuals" with deliberately thin, unornamented HUD overlays: light monochrome text, thin line-drawn ladders/reticles, small translucent dark boxes for MFD-style data, cyan/blue for friendly marks, red for hostiles. Players discuss the HUD almost purely in terms of information availability, not decoration — the UI disappears into function. Sources: https://www.realityremake.com/articles/nuclear-option-review-a-tactical-flight-sim-you-didnt-see-coming , https://www.skywardfm.com/post/first-impression-nuclear-option-early-access-release , https://steamcommunity.com/app/2168680/discussions/0/691996377956223504/ , https://tvtropes.org/pmwiki/pmwiki.php/VideoGame/NuclearOption

**HighFleet** — the opposite pole: a fully diegetic "small museum where you are allowed to touch and twist everything" (designer Konstantin Koshutin). Deep navy/charcoal backgrounds, amber/orange phosphor readouts, red warning stamps, stencil typography. The lesson for ONIKS is not the knobs (we can't afford diegetic art) but the *mood*: monochrome dark field + one warm phosphor accent + sparse red = instant military-hardware feel. Sources: https://www.gamedeveloper.com/design/designing-i-highfleet-i-a-strategy-game-with-heavy-machinery-and-twirling-knobs , https://www.fanbyte.com/legacy/in-highfleet-the-imposing-interface-is-the-point , https://www.gameuidatabase.com/gameData.php?id=2373

**Carrier Command 2** — every screen in the game is a low-res monochrome terminal: single phosphor hue per screen (green, amber, cyan), monospace text, 1px boxes, no anti-aliased ornament. Proof that a whole game UI can be carried by "one accent color + monospace + thin rects". Community mods (UI Enhancer) add exactly the kind of color coding we should bake in from the start: yellow = busy/rearming, green = active, cyan = selected. Sources: https://www.microprose.com/games/carrier-command-2/ , https://steamcommunity.com/sharedfiles/filedetails/?id=2761300794 , https://github.com/NexusQuile/CC2-Higher-Resolution

**DCS World** — menu chrome is a dark slate field with flat panels, thin separators, ALL-CAPS section headers, and a column of plain text buttons; it proves "flat dark + text list" reads as professional sim, not cheap. Theming is file-driven (every 2D element replaceable), reinforcing config-file-first UI. Sources: https://www.digitalcombatsimulator.com/en/files/3311938/ , https://steamcommunity.com/sharedfiles/filedetails/?id=665860274

**Stormworks / Sprocket settings screens** — utilitarian list-rows: label left, value/binding right, click-to-rebind, generic back button; nothing decorative. Their weakness (cramped, unstyled) is the gap ONIKS can clear with the corner-tick panel language below. Sources: https://stormworks.fandom.com/wiki/Wiki/Key_Assignment , https://stormworks.fandom.com/wiki/V1.4.11

**Rebinding UX literature** — key points adopted in §3: fully keyboard-accessible rebind flow, capture *scancode-level* keys, show conflicts immediately, never dead-end the user. Sources: https://blubberquark.tumblr.com/post/669815230084317184/i-got-my-key-binding-interface-up-and-running , https://www.ixiegaming.com/blog/the-art-of-keybinding/ , https://discussions.unity.com/t/input-systems-rebind-ui-sample-and-advice/853345

**Military FUI palettes** — tactical palettes converge on near-black green/blue fields with one phosphor accent; e.g. stealth set `#151816 #354030 #6e7b5b #a8b297 #e3e7dc`, sci-fi set with amber `#ff6e21` / cyan `#73fffe`. Sources: https://www.schemecolor.com/military.php , https://www.color-hex.com/color-palette/1015935 , https://www.behance.net/search/projects/military%20ui%20hud , https://interfaceingame.com/ , https://www.gameuidatabase.com/

**Existing ONIKS code anchors** (keep — they're already on-style): HUD amber header `(0.95,0.85,0.45)` = `#F2D973`; label grey-green `#99B8A3`; value white `#EBF7EB`; armed green `#73FF8C`; reload amber `#FFB840`; bracket red `#FF5C3D`; menu clear color `#030507`; Consolas bold 18/28pt atlas; 12px HUD margin; corner-L target bracket. The spec below is a strict superset of this so nothing visually breaks.

---

## 1. VISUAL LANGUAGE SPEC

### 1.1 Palette (hex, with float-tuple equivalents for the engine)

| Token | Hex | RGB floats | Use |
|---|---|---|---|
| `BG0` | `#060A10` | (0.024, 0.039, 0.063) | Menu clear color / full-screen field (slightly lifted from current `#030507` so panels separate) |
| `BG1` | `#0B1412` | (0.043, 0.078, 0.071) | Panel fill. Alpha 0.92 in menus, 0.55 in HUD (matches current `PANEL_RGBA` feel) |
| `BG2` | `#101D19` | (0.063, 0.114, 0.098) | Row hover fill / input field fill |
| `LINE` | `#23332E` | (0.137, 0.200, 0.180) | 1px panel borders, dividers, scrollbar track |
| `ACCENT` | `#F2D973` | (0.95, 0.85, 0.45) | Primary amber. Headers, selected text, focus brackets. **Identical to current `HEADER_COL` — zero migration.** |
| `ACCENT_DIM` | `#8C7E43` | (0.55, 0.494, 0.263) | Amber at rest (unselected hotkey hints, footer) |
| `DANGER` | `#FF5C3D` | (1.0, 0.36, 0.24) | Conflicts, destructive confirm, TERMINAL phase. Same as bracket color. |
| `OK` | `#73FF8C` | (0.45, 1.0, 0.55) | ARMED / success states. Existing. |
| `WARN` | `#FFB840` | (1.0, 0.72, 0.25) | RELOADING / transient hints. Existing. |
| `TEXT` | `#EBF7EB` | (0.92, 0.97, 0.92) | Primary values/body. Existing `VALUE_COL`. |
| `MUTED` | `#99B8A3` | (0.60, 0.72, 0.64) | Labels, secondary copy. Existing `LABEL_COL`. |
| `DISABLED` | `#4A5A54` | (0.29, 0.353, 0.329) | Greyed rows, version footer |

Rule: ONE accent (amber) carries the brand; green/red/orange are *status semantics only*, never decoration. This is the Carrier Command 2 / HighFleet discipline.

### 1.2 Panel treatment

- **Fill**: `BG1` rect, alpha 0.92 (menus) / 0.55 (HUD).
- **Border**: 1px `LINE` rectangle via `draw_lines` (4 segments), inset 0.5px-safe (draw at integer pixel coords).
- **Corner ticks** (signature element, echoes the in-game target bracket): 4 amber `ACCENT_DIM` L-shapes, 8px legs, 1.5px stroke, drawn ON TOP of the border at each corner. Selected/active panels swap ticks to full `ACCENT`. Implementation = exactly the existing `_target_bracket` corner loop with `half=panel_half`, `leg=8`.
- **Header rule**: under any panel header, a 1px `LINE` divider spanning the inner width, with a 24px `ACCENT` segment overlaid at the left end (two `draw_lines` calls).
- **Scanline accent — use sparingly**: do NOT tile scanlines (quad cost, visual noise). Instead, one optional "data strip": a 2px tall `ACCENT` rect at 0.12 alpha across the very top inner edge of the active panel. Cheap, reads as powered-on phosphor.
- **No drop shadows, no rounded corners.** Hard edges are the style.

### 1.3 Typography (Consolas bold atlas)

| Role | Size (pt, baked) | Case | Color | Notes |
|---|---|---|---|---|
| GAME TITLE | 56 (new bake) | CAPS, letter-spaced | `TEXT` | Render as `"O N I K S"` (space-injected tracking — monospace atlas has fixed advance, so fake tracking with literal spaces; 1 space ≈ +1ch) |
| Screen header | 28 (existing `HEADER_SIZE`) | CAPS | `ACCENT` | e.g. `SETTINGS / KEYBINDS` |
| Menu item / row | 18 (existing `BODY_SIZE`) | CAPS | state-dependent | All interactive text is CAPS |
| Body / help copy | 18 | CAPS preferred; sentence case allowed for long lines | `MUTED` | |
| Small / footer / hints | 14 (new bake) | CAPS | `DISABLED` or `ACCENT_DIM` | version string, `F1 CONTROLS` |

Add `TITLE_SIZE = 56` and `SMALL_SIZE = 14` to the `SIZES` tuple in `engine/text.py` — the atlas baker already loops over arbitrary sizes.
ALL-CAPS everywhere except multi-sentence help text. Numbers always with units, space-separated: `1,250 m`, `M 2.31`, `BRG 047`.

### 1.4 Interaction states (rects + color swaps only)

| State | Treatment |
|---|---|
| Rest | `MUTED` text, no fill |
| Hover (mouse) | `BG2` row fill + `TEXT` text |
| Selected (keyboard focus) | `ACCENT` text + 3px wide `ACCENT` bar at row left edge + `BG2` fill + `>` caret prefix optional (pick bar OR caret, not both — recommend bar) |
| Pressed / activated | row fill flashes `ACCENT` at 0.22 alpha for 80 ms, then action fires |
| Listening (rebind) | binding cell shows `PRESS KEY` in `ACCENT`, cell fill pulses `ACCENT` alpha 0.10↔0.20 at 2 Hz (sin on frame time — flat fills only, no gradient) |
| Disabled | `DISABLED` text, no hover response |
| Danger focus (e.g. RESET DEFAULTS armed) | text and left bar swap to `DANGER` |

### 1.5 Layout grid

- Base unit: **8px**. All paddings/gaps are multiples of 8 (the HUD's current 12px margin stays as the one legacy exception, or migrate to 16).
- Menu screens: content column **560px** wide, horizontally centered; top margin 96px to title baseline.
- Row height: **40px** (text 18pt ≈ 22px line + 9px top/bottom), hit target full row width.
- Panel inner padding: **16px**; gap between panels: **24px**.
- Settings screens: two-column rows inside the 560px panel — action label x=16, binding value right-aligned at panel_w−16.
- HUD keeps top-left telemetry block (268px wide) exactly as-is; new elements obey the same 8px rhythm.

---

## 2. MAIN MENU + PAUSE MENU

### 2.1 Main menu

Background: live sandbox scene idling under the menu (slow orbit camera over the coastline) at full color, with a full-screen `BG0` dim rect at alpha 0.45 — Nuclear Option does effectively this. Fallback: flat `BG0`.

```
+------------------------------------------------------------------+
|                                                                  |
|                                                                  |
|        +--[tick]-----------------------------------[tick]--+     |
|        |  O N I K S                                        |     |   title 56pt TEXT
|        |  ANTI-SHIP MISSILE SIMULATION                     |     |   14pt MUTED, caps
|        +--[tick]-----------------------------------[tick]--+     |
|                                                                  |
|             ____ thin LINE divider w/ 24px ACCENT cap ____       |
|                                                                  |
|        |  > SANDBOX                                        |     <- selected: ACCENT text,
|        |    SETTINGS                                       |        3px left bar, BG2 fill
|        |    QUIT                                           |     <- rest: MUTED
|                                                                  |
|                                                                  |
|                                                                  |
|  ONIKS PROTO v0.3.1 - 2026-06-11            UP/DOWN ENTER ESC    |   14pt DISABLED footer,
+------------------------------------------------------------------+   both corners, 24px margin
```

- Items: `SANDBOX`, `SETTINGS`, `QUIT` — exact strings, 18pt, 40px row pitch.
- Title panel: bordered box with corner ticks, 560px wide; subtitle line `ANTI-SHIP MISSILE SIMULATION` in `MUTED` 14pt directly under the title.
- Footer left: `ONIKS PROTO v0.3.1 — 2026-06-11` in `DISABLED` 14pt. Footer right: `↑/↓ SELECT   ENTER CONFIRM` in `ACCENT_DIM` 14pt (use `UP/DOWN` text if arrows aren't in the ASCII bake — they aren't, atlas is 32–126, so use `UP/DN SELECT  ENTER OK`).
- `QUIT` when focused uses `DANGER` accent (subtle "this one ends the program" cue).

### 2.2 Pause menu

Same component, fewer items, drawn over the *frozen* sim frame with `BG0` dim at alpha 0.65 (darker than main menu — communicates "suspended").

```
+------------------------------------------------------------------+
|   (frozen sandbox frame, dimmed 65%)                             |
|                                                                  |
|              +--[t]--------------------------[t]--+              |
|              |  PAUSED                            |              |  28pt ACCENT header
|              |  T+04:12  x8                       |              |  14pt MUTED sim clock+scale
|              |  __________________________________|              |  header rule
|              |                                    |              |
|              |  > RESUME                          |              |
|              |    SETTINGS                        |              |
|              |    MAIN MENU                       |              |
|              |                                    |              |
|              +--[t]--------------------------[t]--+              |
|                                                                  |
|                       ESC RESUME                                 |  14pt ACCENT_DIM
+------------------------------------------------------------------+
```

- Items: `RESUME`, `SETTINGS`, `MAIN MENU`. ESC closes (same as `RESUME`).
- Showing `T+clock` in the pause header is a free premium touch — the sim acknowledges its own state.
- `MAIN MENU` focused = `WARN` color (data loss possible), with a one-line confirm swap on first ENTER: row text becomes `MAIN MENU — ENTER AGAIN TO CONFIRM` in `DANGER`.

---

## 3. SETTINGS / KEYBINDS SCREEN

### 3.1 Wireframe

```
+------------------------------------------------------------------+
|   SETTINGS / KEYBINDS                                  28pt ACCENT|
|   ___________________________________________________ header rule|
|                                                                  |
|  +-[t]------------------------------------------------------[t]-+|
|  |  ACTION                                         BINDING      ||  14pt MUTED col headers
|  |  ............................................................||  1px LINE divider
|  |  LAUNCH WEAPON                                   SPACE       ||
|  |  CYCLE PLATFORM                                  TAB         ||
|  |> TACTICAL MAP                                    M           ||  <- focused row
|  |  CAMERA MODE                                     C           ||
|  |  PROFILE HI-LO                                   1           ||
|  |  PROFILE LO-LO                                   2           ||
|  |  PAUSE SIM                                       P           ||
|  |  FRAME STEP                                      N           ||
|  |  TIME SCALE -                                    MINUS       ||  | <- 2px scrollbar track
|  |  TIME SCALE +                                    EQUALS      ||  # <- 4px ACCENT_DIM thumb
|  |  FREE CAM FWD/BACK                               W / S       ||
|  |  FREE CAM LEFT/RIGHT                             A / D       ||
|  |  FREE CAM UP/DOWN                                E / Q       ||
|  |  SCREENSHOT                                      F2          ||
|  |  CONTROLS OVERLAY                                F1          ||
|  +-[t]------------------------------------------------------[t]-+|
|                                                                  |
|     [ RESET DEFAULTS ]                          [ BACK ]         |  buttons, 1px border boxes
|                                                                  |
|  ENTER REBIND   ESC BACK   R RESET ROW            v0.3.1         |  14pt footer
+------------------------------------------------------------------+
```

Row states during rebind:

```
normal:     |  TACTICAL MAP                                M           |
listening:  |  TACTICAL MAP                          [ PRESS KEY ]     |  ACCENT, cell pulses
conflict:   |  TACTICAL MAP                                C           |
            |  ! C IN USE: CAMERA MODE - ENTER SWAP / ESC CANCEL       |  DANGER 14pt sub-row
```

### 3.2 Rebind flow (exact behavior)

1. Click row or press ENTER on focused row → cell enters **listening**: shows `PRESS KEY` (`ACCENT`, pulsing fill), all other input suppressed.
2. Next `KEYDOWN` is captured **by scancode** (layout-independent — per https://blubberquark.tumblr.com/post/669815230084317184/i-got-my-key-binding-interface-up-and-running ); display name via `pygame.key.name(key).upper()`.
3. `ESC` while listening = cancel, restore previous binding. (Therefore ESC itself is not rebindable — reserve ESC and F1.)
4. **Conflict**: if the key is already bound, show the `DANGER` sub-row `! C IN USE: CAMERA MODE — ENTER SWAP / ESC CANCEL`. ENTER performs an atomic *swap* (the old action takes your old key) — never silently unbind, never hard-block. Conflicted rows that remain show a `DANGER`-tinted binding cell.
5. `R` on a focused row resets that row to default; `RESET DEFAULTS` button resets all (requires the double-ENTER confirm pattern from §2.2, `DANGER` text).
6. Every successful rebind writes the config file immediately (no Apply button — sim-prototype scale doesn't need staged settings).

### 3.3 Persistence format

JSON, human-editable, action-id → pygame key *name* string (names survive `pygame.key.key_code()` round-trip; store lists for multi-key actions):

```json
{
  "version": 1,
  "bindings": {
    "launch":         "space",
    "cycle_platform": "tab",
    "map":            "m",
    "camera_mode":    "c",
    "profile_hi_lo":  "1",
    "profile_lo_lo":  "2",
    "pause":          "p",
    "frame_step":     "n",
    "time_down":      "-",
    "time_up":        "=",
    "freecam_fwd":    "w",
    "freecam_back":   "s",
    "freecam_left":   "a",
    "freecam_right":  "d",
    "freecam_up":     "e",
    "freecam_down":   "q",
    "screenshot":     "f2",
    "controls_overlay": "f1"
  }
}
```

- Location: `%APPDATA%\ONIKS\settings.json` (`os.path.join(os.getenv("APPDATA"), "ONIKS", "settings.json")`); fall back to the game dir if APPDATA is unset. Keybinds live inside the same file as future audio/video settings (one file, one `version` field for migration).
- Load rule: unknown action ids ignored, missing ids filled from defaults, unparseable file → rename to `settings.json.bad` and regenerate (never crash on config). This mirrors how Minecraft (`options.txt` `key_key.*` lines), id-tech `.cfg` bind commands, and Unity's rebind-JSON all behave: flat text, action→key, defaults on absence.

### 3.4 Scroll behavior (~15–18 actions)

- Viewport = panel inner height; rows y-culled (skip `draw_*` outside panel bounds — no GL scissor needed if header/footer rows overdraw the clipped edge with panel-fill rects).
- Mouse wheel: 3 rows per notch. Keyboard: focus moves with UP/DOWN and the view auto-scrolls to keep focus visible with a 1-row lookahead margin.
- Scrollbar: 2px `LINE` track at panel right inner edge, 4px wide `ACCENT_DIM` thumb, thumb length proportional, min 24px. Pure rects.
- At 1080p with 40px rows, 18 actions ≈ 720px — it will *just* overflow; design for scroll from day one, and group with 14pt `MUTED` section sub-headers: `ENGAGEMENT`, `SIMULATION`, `CAMERA`, `SYSTEM` (sub-headers scroll with content).

---

## 4. IN-GAME HUD GUIDANCE

### 4.1 Remove the bottom hint bar — replace with three things

The current `CONTROLS_HINT` line (`TAB platform  C cam  M map ...`, `game/hud.py:52`) is permanent low-value noise — the exact thing the Nuclear Option community praises that game for not having. Replacement:

1. **A single micro-affordance, bottom-right corner**: `F1 CONTROLS` — 14pt, `ACCENT_DIM`, no panel fill, 16px from both edges. One string, exact copy: `F1 CONTROLS`. That's the entire permanent footprint.
2. **F1 toggle overlay**: centered panel (same §1.2 treatment, alpha 0.92, corner ticks) listing all bindings *generated from the live binding table* (so it can never lie after a rebind). Two-column: action `MUTED`, key `TEXT`. Header `CONTROLS` 28pt `ACCENT` + rule. Footer line: `F1 CLOSE   REBIND IN SETTINGS`. Sim keeps running (or pause it — recommend keep running; it's an overlay, not a menu). Dim rect alpha 0.35 behind the panel only, not full-screen.
3. **Keep contextual one-liners** (the existing `hint_flash` mechanism) for *state-driven* messages only, never tutorials: `S-300: SELECT AIR TARGET`, `LAUNCHER RELOADING`, `TIME x8`. 2.5 s, `WARN` color, bottom-center, with panel fill. These earn their pixels because they appear only when relevant — the principle the rebind-UX literature calls contextual disclosure (https://www.ixiegaming.com/blog/the-art-of-keybinding/).

The `CAM CHASE` mode readout (currently glued to the hint bar) moves to a bare 14pt `MUTED` string bottom-right, stacked 24px above `F1 CONTROLS`: copy `CAM CHASE` / `CAM FREE` / `CAM TRACK`. No panel fill — corner text, Nuclear Option style.

### 4.2 Telemetry block consistency

Keep the top-left block exactly as built (it already matches the spec: amber header, muted labels, white values, status colors). Upgrades to align it with the menu language, all cheap:

- Add the 1px `LINE` border + 8px corner ticks (`ACCENT_DIM`) around the existing panel rect.
- Add the header rule (1px `LINE` + 24px `ACCENT` cap) under the weapon name.
- Snap `LINE_H` 22 → 24 (8px rhythm) and `MARGIN` 12 → 16 when convenient.
- Status colors stay: `ARMED` `#73FF8C`, `RELOADING n s` `#FFB840`, `TERMINAL` `#FF5C3D` — they're already the spec's semantic set.

---

## 5. TOP 10 PREMIUM TOUCHES (ranked by payoff/effort)

1. **Corner ticks on every panel** — 4 amber L's, 8px legs, 1.5px stroke. Unifies menus with the in-game target bracket; the whole UI becomes "targeting hardware". (~10 lines, reuses bracket code.)
2. **Consistent 8px spacing rhythm** — every margin/pad/gap a multiple of 8. Invisible individually; collectively it's the difference between "programmer UI" and "designed UI".
3. **Selected-row left bar (3px amber) + fill instead of just color swap** — focus is findable in peripheral vision; standard in DCS-class sims.
4. **80 ms press-flash on activation** (fill `ACCENT` α0.22) + the existing `ui_click()` sound — input feels acknowledged. Pair every state change with the click.
5. **Header rule with amber cap** (1px line, 24px accent segment) under every header — one detail that reads as a deliberate design system.
6. **Live data in chrome**: `T+04:12  x8` in the pause header; version + date in the main-menu footer; `BRG/RNG` already in the HUD. Military UIs never show static decoration — every string is an instrument.
7. **Pulsing `PRESS KEY` rebind cell** (sin-alpha 2 Hz between 0.10–0.20) — flat-fill "breathing" that signals listening state without animation assets.
8. **Conflict sub-row with swap offer** (`! C IN USE: CAMERA MODE — ENTER SWAP / ESC CANCEL`) — handling the edge case gracefully is the most premium-feeling thing a settings screen can do.
9. **Space-tracked title** (`O N I K S`) over a corner-ticked box with a `MUTED` role line under it (`ANTI-SHIP MISSILE SIMULATION`) — instant title-screen identity from pure text.
10. **Powered-on strip**: 2px `ACCENT` α0.12 line across the top inner edge of the *active* panel only — the faintest phosphor glow cue, HighFleet's mood at 1/1000th the cost.

(Deliberately rejected: tiled scanlines, fake CRT curvature, typewriter text reveal — quad-count and taste hazards that fight the clean Nuclear Option look.)

---

## Appendix: exact copy strings

- Main menu: `SANDBOX` / `SETTINGS` / `QUIT`; footer `ONIKS PROTO v{ver} — {date}`; hints `UP/DN SELECT  ENTER OK`
- Pause: `PAUSED`, `RESUME` / `SETTINGS` / `MAIN MENU`; confirm `MAIN MENU — ENTER AGAIN TO CONFIRM`; footer `ESC RESUME`
- Keybinds: header `SETTINGS / KEYBINDS`; columns `ACTION` `BINDING`; `[ PRESS KEY ]`; `! {KEY} IN USE: {ACTION} — ENTER SWAP / ESC CANCEL`; `RESET DEFAULTS`; `BACK`; footer `ENTER REBIND   ESC BACK   R RESET ROW`
- HUD: `F1 CONTROLS`; `CAM CHASE|FREE|TRACK`; overlay header `CONTROLS`, footer `F1 CLOSE   REBIND IN SETTINGS`
