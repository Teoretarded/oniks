"""RED-FORCE DIRECTOR — the war sandbox's puppet-master panel (I, on the map).

Model/draw split (the forensics-pure convention): ``DirectorModel`` is
GL-free pure logic over a SandboxWorld (unit-tested headless in
tests/test_director.py); ``draw_director`` + ``draw_unit_markers`` are the
render half, called only by game/sandbox_war.py with a live GL context.

The panel is an overlay on the tactical map — THE SIM NEVER PAUSES under
it.  Flow: I opens the panel over the map, UP/DOWN walk the selectable
rows, ENTER activates (the AUTO-ENGAGE row toggles the world's
weapons-free flag; the SEAD row rolls a HARM package; a unit row ARMS
target mode), and while armed the next LMB on the map converts through
the map view's screen_to_world into a director_order at that point.
ESC backs out one level (disarm, then close).  Every action message is
flashed through the state's show_hint — which in the combat shell is
ALSO the black-box ledger's denial channel, so director orders leave a
paper trail for free.
"""

from __future__ import annotations

# Row kinds.
ROW_TOGGLE = "toggle"      # the global AUTO-ENGAGE switch
ROW_UNIT = "unit"          # an orderable unit (arms target mode)
ROW_SEAD = "sead"          # point-free HARM package at the player radar
ROW_INFO = "info"          # display-only (carrier / AWACS)

# Unit kinds the panel lets the player ORDER (matches the world API).
ORDERABLE_KINDS = ("destroyer", "sub", "fighters")


class DirectorModel:
    """Pure selection/order state over ``world`` (a SandboxWorld)."""

    def __init__(self, world):
        self.world = world
        self.open = False
        self.sel = 0                 # index into rows()
        self.armed_uid: str | None = None   # unit awaiting a map click
        self.last_msg = ""           # persistent panel status line

    # ------------------------------------------------------------------ rows

    def rows(self) -> list[dict]:
        """The panel rows, rebuilt live each call (ammo/alive move under
        us).  Order: the toggle, the orderable units, SEAD, the info rows."""
        out = [dict(kind=ROW_TOGGLE, label="AUTO-ENGAGE", selectable=True)]
        units = self.world.director_units()
        for u in units:
            if u["kind"] in ORDERABLE_KINDS:
                out.append(dict(kind=ROW_UNIT, unit=u,
                                selectable=bool(u["alive"])))
        out.append(dict(kind=ROW_SEAD,
                        label="SEAD: HARM THE PLAYER RADAR",
                        selectable=True))
        for u in units:
            if u["kind"] not in ORDERABLE_KINDS:
                out.append(dict(kind=ROW_INFO, unit=u, selectable=False))
        return out

    # ------------------------------------------------------------- open/close

    def toggle(self) -> None:
        self.open = not self.open
        self.armed_uid = None
        if self.open and not self._selectable(self.rows(), self.sel):
            self.move(+1)

    def cancel(self) -> bool:
        """ESC: back out one level.  True when the event was consumed."""
        if not self.open:
            return False
        if self.armed_uid is not None:
            self.armed_uid = None
            self.last_msg = "TARGET MODE CANCELLED"
            return True
        self.open = False
        return True

    # -------------------------------------------------------------- selection

    @staticmethod
    def _selectable(rows: list[dict], idx: int) -> bool:
        return 0 <= idx < len(rows) and bool(rows[idx]["selectable"])

    def move(self, delta: int) -> None:
        """Walk the selection past unselectable rows, wrapping."""
        rows = self.rows()
        if not any(r["selectable"] for r in rows):
            self.sel = 0
            return
        idx = self.sel
        for _ in range(len(rows)):
            idx = (idx + delta) % len(rows)
            if rows[idx]["selectable"]:
                self.sel = idx
                return

    # ---------------------------------------------------------------- actions

    def activate(self) -> str:
        """ENTER on the current row.  Returns the HUD/panel message."""
        rows = self.rows()
        if not self._selectable(rows, self.sel):
            self.move(+1)
            rows = self.rows()
            if not self._selectable(rows, self.sel):
                return ""
        row = rows[self.sel]
        world = self.world
        if row["kind"] == ROW_TOGGLE:
            world.set_weapons_free(not world.enemy_weapons_free)
            state = "ON" if world.enemy_weapons_free else "OFF"
            self.last_msg = f"AUTO-ENGAGE: {state}"
        elif row["kind"] == ROW_SEAD:
            _ok, msg = world.director_sead()
            self.last_msg = msg
        else:                                   # ROW_UNIT: arm target mode
            u = row["unit"]
            if not u["ready"]:
                self.last_msg = f"{u['label']}: NOT READY - {u['detail']}"
            else:
                self.armed_uid = u["uid"]
                self.last_msg = f"{u['label']}: CLICK MAP TO LAUNCH"
        return self.last_msg

    def click(self, world_xz):
        """LMB on the map while armed -> issue the order.  Returns the
        (ok, msg) tuple, or None when not armed (caller eats the click)."""
        if self.armed_uid is None:
            return None
        uid, self.armed_uid = self.armed_uid, None
        ok, msg = self.world.director_order(uid, world_xz)
        self.last_msg = msg
        return ok, msg


# --------------------------------------------------------------------- render
# GL-touching half — imported names resolved inside the functions so this
# module stays importable headless (the model tests).

PANEL_X = 332          # right of the BOARD contacts column (315 px)
PANEL_Y = 92           # below the map title plate
PANEL_W = 470
ROW_PAD = 6


def draw_director(state, model: DirectorModel, w: int, h: int) -> None:
    """The panel: header, rows (label/weapon/ammo/status), status line."""
    from engine.text import SMALL_SIZE
    from game.states import (ACCENT, BELIEF, DANGER, PAPER_MUTED, TEXT_COL,
                             draw_panel)
    text = state.text
    rows = model.rows()
    lh = text.line_height(SMALL_SIZE) + ROW_PAD
    ph = lh * (len(rows) + 3) + 18
    draw_panel(text, PANEL_X, PANEL_Y, PANEL_W, ph)
    x = PANEL_X + 14
    y = PANEL_Y + 10
    key = state.app.keybinds.name_for("director")
    text.draw_text(x, y, f"RED-FORCE DIRECTOR   [{key} CLOSE]",
                   ACCENT, SMALL_SIZE)
    y += lh
    free = state.world.enemy_weapons_free
    for i, row in enumerate(rows):
        sel = i == model.sel
        marker = ">" if sel else " "
        col = TEXT_COL if row["selectable"] else PAPER_MUTED
        if row["kind"] == ROW_TOGGLE:
            stat = "ON" if free else "OFF"
            stat_col = DANGER if free else PAPER_MUTED
            text.draw_text(x, y, f"{marker} {row['label']}", col, SMALL_SIZE)
            text.draw_text(x + PANEL_W - 92, y, stat, stat_col, SMALL_SIZE)
        elif row["kind"] == ROW_SEAD:
            text.draw_text(x, y, f"{marker} {row['label']}", col, SMALL_SIZE)
        else:
            u = row["unit"]
            armed = model.armed_uid == u["uid"]
            label_col = (ACCENT if armed else
                         col if u["alive"] else DANGER)
            text.draw_text(x, y, f"{marker} {u['label']}",
                           label_col, SMALL_SIZE)
            text.draw_text(x + 250, y, u["weapon"], col, SMALL_SIZE)
            stat = ("ARMED" if armed else
                    "RDY" if u["ready"] else
                    "DEAD" if not u["alive"] else "-")
            text.draw_text(x + PANEL_W - 92, y,
                           f"{u['ammo']:>3} {stat}", col, SMALL_SIZE)
        y += lh
    y += 4
    if model.armed_uid is not None:
        text.draw_text(x, y, "CLICK MAP TO LAUNCH - ESC CANCEL",
                       BELIEF, SMALL_SIZE)
    elif model.last_msg:
        text.draw_text(x, y, model.last_msg[:64], PAPER_MUTED, SMALL_SIZE)
    y += lh
    text.draw_text(x, y, "UP/DN SELECT   ENTER ORDER/TOGGLE",
                   PAPER_MUTED, SMALL_SIZE)
    state.ui.add("map.director_panel", PANEL_X, PANEL_Y, PANEL_W, ph,
                 code="game/director.py:draw_director")
    text.flush(w, h)


def draw_unit_markers(state, model: DirectorModel, w: int, h: int) -> None:
    """Truth markers for every director unit while the panel is open — the
    sandbox may show its own toys (subs included; they are invisible to the
    radar picture by construction).  Small diamond + uid, amber when armed."""
    from engine.text import SMALL_SIZE
    from game.states import ACCENT, DANGER, PAPER_MUTED
    text = state.text
    view = state.tactical_map.view
    for u in model.world.director_units():
        if not u["alive"]:
            continue
        sx, sy = view.world_to_screen((float(u["pos"][0]),
                                       float(u["pos"][2])))
        if not (0.0 <= sx <= w and 0.0 <= sy <= h):
            continue
        armed = model.armed_uid == u["uid"]
        col = ACCENT if armed else (DANGER if u["kind"] != "sub"
                                    else PAPER_MUTED)
        r = 7.0 if armed else 5.0
        pts = [(sx, sy - r), (sx + r, sy), (sx, sy + r), (sx - r, sy),
               (sx, sy - r)]
        text.draw_lines(pts, (*col, 0.95), 1.5)
        text.draw_text(sx + 8, sy - 6, u["uid"].upper(), col, SMALL_SIZE)
    text.flush(w, h)
