"""In-game HUD variants of the widget primitive library (game/states.py).

The menu chrome paints its panels/fills at PANEL_ALPHA = 0.92; the in-game HUD
paints translucent over the live battle at HUD_ALPHA = 0.55 (matching
game/hud.py). Rather than fork the geometry, these are thin wrappers that reuse
the exact same draw helpers and just pass the lower fill alpha through the
helpers' ``alpha=`` parameter — DRY, one source of truth for layout/color.

Pure + GL-free + headless, like their states.py counterparts.
"""

from __future__ import annotations

from engine.text import SMALL_SIZE
from game import states

# In-game HUD fill alpha (game/hud.py uses 0.55; menus use states.PANEL_ALPHA).
HUD_ALPHA = 0.55


def badge(text, label, x, y, state, size=SMALL_SIZE) -> float:
    """Translucent (0.55) HUD status pill. See game.states.badge — the body
    fill carries the 0.55 panel alpha instead of the faint menu tint."""
    return states.badge(text, label, x, y, state, size, alpha=HUD_ALPHA)


def gauge_bar(text, x, y, w, h, frac, col, *, ticks=0) -> None:
    """Translucent (0.55) HUD gauge bar. See game.states.gauge_bar."""
    states.gauge_bar(text, x, y, w, h, frac, col, ticks=ticks, alpha=HUD_ALPHA)
