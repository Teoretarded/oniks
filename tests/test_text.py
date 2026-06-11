"""engine.text atlas bake — GL-free (TextRenderer itself is never built)."""

import numpy as np

from engine.text import (ASCII_FIRST, ASCII_LAST, ATLAS_WIDTH, BODY_SIZE,
                         HEADER_SIZE, SIZES, SMALL_SIZE, TITLE_SIZE,
                         WHITE_BLOCK, bake_atlas)

GLYPH_COUNT = ASCII_LAST - ASCII_FIRST + 1


def test_bake_atlas_layout_and_metrics():
    pixels, glyphs = bake_atlas()
    assert pixels.dtype == np.uint8 and pixels.ndim == 2
    assert pixels.shape[1] == ATLAS_WIDTH
    # Solid white block at (0, 0) for untextured fills/lines.
    assert (pixels[:WHITE_BLOCK, :WHITE_BLOCK] == 255).all()
    assert set(SIZES) == {SMALL_SIZE, BODY_SIZE, HEADER_SIZE, TITLE_SIZE}
    for size in SIZES:
        g = glyphs[size]
        assert len(g.adv) == GLYPH_COUNT
        assert (g.adv > 0).all()        # every glyph advances the pen
        assert g.line_h > 0
        # uv rects inside the atlas, non-inverted.
        assert (g.u0 >= 0).all() and (g.u1 <= 1).all()
        assert (g.u1 >= g.u0).all() and (g.v1 > g.v0).all()
        assert (g.v0 >= 0).all() and (g.v1 <= 1).all()
    # The four bakes really are four distinct scales.
    assert (glyphs[SMALL_SIZE].line_h < glyphs[BODY_SIZE].line_h
            < glyphs[HEADER_SIZE].line_h < glyphs[TITLE_SIZE].line_h)


def test_bake_atlas_glyphs_have_coverage():
    pixels, glyphs = bake_atlas()
    h, w = pixels.shape
    g = glyphs[BODY_SIZE]
    for ch in "AW#8":
        i = ord(ch) - ASCII_FIRST
        x0, x1 = int(round(g.u0[i] * w)), int(round(g.u1[i] * w))
        y0, y1 = int(round(g.v0[i] * h)), int(round(g.v1[i] * h))
        assert pixels[y0:y1, x0:x1].max() > 128   # visible ink in the cell
