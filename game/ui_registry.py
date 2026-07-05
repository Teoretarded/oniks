"""Per-frame UI hit/tag registry (AI-testability build, 2026-07-05).

The single source of truth for WHAT is on screen WHERE.  Draw code
registers every major panel each frame:

  * ``name`` — a stable dotted id ("hud.platform_plate", "map.threat_strip")
  * rect    — the drawn pixel rectangle
  * ``action`` — optionally, the game/keybinds.py action id a click on the
    rect dispatches (the SAME id the key binding fires, so mouse and
    keyboard share one dispatcher and can never diverge)
  * ``code`` — a "file.py:site" pointer so a bug-report tag tells the
    reader (human or AI) exactly where the pixels come from
  * ``parent`` — a container's name, for rows drawn INSIDE a plate (the
    overlap oracle skips parent/child pairs — nesting is not a defect)

Three consumers:
  1. SandboxControls routes LMB clicks through :meth:`hit` (topmost wins).
  2. The F3 bug-report overlay tags clicked items into the report.
  3. :meth:`overlaps` is the LAYOUT ORACLE: after rendering a frame, any
     intersecting sibling pair is a UI defect an AI test can assert on
     without eyes (tools/probe_ui_overlaps.py).

GL-free, pure — unit-tested headless.
"""

from __future__ import annotations


class UiRegistry:
    """Per-frame registry; ``begin_frame`` at the top of render, ``add``
    from draw sites, queries afterwards."""

    def __init__(self):
        self.items: list[dict] = []

    def begin_frame(self) -> None:
        self.items = []

    def add(self, name: str, x: float, y: float, w: float, h: float, *,
            action: str | None = None, code: str = "",
            parent: str | None = None) -> None:
        self.items.append({
            "name": name,
            "rect": (float(x), float(y), float(x) + float(w),
                     float(y) + float(h)),
            "action": action,
            "code": code,
            "parent": parent,
        })

    def hit(self, px: float, py: float) -> dict | None:
        """The topmost item under (px, py) — later registration wins, the
        same convention as draw order (later draws on top)."""
        for item in reversed(self.items):
            x0, y0, x1, y1 = item["rect"]
            if x0 <= px <= x1 and y0 <= py <= y1:
                return item
        return None

    def overlaps(self) -> list[tuple[str, str]]:
        """Intersecting SIBLING pairs (name_a, name_b), registration order.
        Parent/child pairs are skipped — a row inside its plate is nesting,
        not a defect.  An empty list is the layout contract."""
        bad: list[tuple[str, str]] = []
        n = len(self.items)
        for i in range(n):
            a = self.items[i]
            for j in range(i + 1, n):
                b = self.items[j]
                if a["parent"] == b["name"] or b["parent"] == a["name"]:
                    continue
                ax0, ay0, ax1, ay1 = a["rect"]
                bx0, by0, bx1, by1 = b["rect"]
                if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                    bad.append((a["name"], b["name"]))
        return bad
