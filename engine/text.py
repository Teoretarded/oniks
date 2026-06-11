"""Font-atlas text + 2D overlay primitives (the HUD / map ortho pass).

Bakes Consolas bold at the body and header sizes (ASCII 32-126, plus a
solid-white block for untextured fills) into ONE GL texture at startup.
``draw_text`` / ``draw_rect`` / ``draw_lines`` batch screen-space quads in
submission order; ``flush`` draws the whole batch in a single ortho pass —
no lighting, no log depth. Screen coords: origin top-left, pixels.

GL state: the overlay pass disables depth test and face culling (the
renderer sets glFrontFace(GL_CW) globally and overlay quads make no winding
promise) and enables alpha blending; everything is restored after.

GL imports are deferred to ``TextRenderer.__init__`` (the atlas bake itself
needs only pygame.font), so the module stays importable headless — same
pattern as ``engine.particles`` (LOCKED test convention).
"""

from __future__ import annotations

import numpy as np
import pygame

# --- Atlas tuning -------------------------------------------------------------

FONT_NAME = "consolas"
SMALL_SIZE = 14                # pt, footer/hints/micro-labels (Task UI)
BODY_SIZE = 18                 # pt, plan-fixed body font (bold)
HEADER_SIZE = 28               # pt, plan-fixed header font (bold)
TITLE_SIZE = 56                # pt, menu game title (Task UI)
SIZES = (SMALL_SIZE, BODY_SIZE, HEADER_SIZE, TITLE_SIZE)
ASCII_FIRST, ASCII_LAST = 32, 126   # baked glyph range (95 glyphs)
_GLYPH_COUNT = ASCII_LAST - ASCII_FIRST + 1

ATLAS_WIDTH = 1024             # texels; rows wrap, height computed at bake
GLYPH_PAD = 1                  # texel gap between glyphs (no linear bleed)
WHITE_BLOCK = 4                # texel square of solid white for fills/lines

DEFAULT_LINE_WIDTH = 1.5       # px, draw_lines default stroke width

# Quad corner expansion order: two CCW-in-screen triangles per quad.
_TRI_CORNERS = ((0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1))

_FLOATS_PER_VERT = 8           # [x y u v r g b a]
_STRIDE = _FLOATS_PER_VERT * 4


def _rgba(color) -> tuple:
    """Accept rgb or rgba (floats 0..1); return a 4-tuple."""
    c = tuple(float(v) for v in color)
    return c if len(c) == 4 else c + (1.0,)


class GlyphSet:
    """Per-font-size glyph metrics, parallel arrays indexed by ord(ch)-32."""

    def __init__(self, line_h: int):
        self.line_h = int(line_h)
        n = _GLYPH_COUNT
        self.w = np.zeros(n, dtype=np.float32)     # quad size, px
        self.h = np.zeros(n, dtype=np.float32)
        self.adv = np.zeros(n, dtype=np.float32)   # pen advance, px
        self.u0 = np.zeros(n, dtype=np.float32)
        self.v0 = np.zeros(n, dtype=np.float32)
        self.u1 = np.zeros(n, dtype=np.float32)
        self.v1 = np.zeros(n, dtype=np.float32)


def bake_atlas(sizes=SIZES, width: int = ATLAS_WIDTH):
    """Render ASCII 32..126 for every font size into one alpha image.

    Returns ``(pixels, glyph_sets)``: pixels is (H, width) uint8 coverage
    (row 0 = top, matching uv v=0), glyph_sets maps size -> GlyphSet.
    A WHITE_BLOCK x WHITE_BLOCK solid block sits at (0, 0) so untextured
    fills can sample a guaranteed-white texel. GL-free (pygame.font only).
    """
    if not pygame.font.get_init():
        pygame.font.init()
    placements = []                          # (surf, x, y, glyph_set, index)
    glyph_sets = {}
    x, y, row_h = WHITE_BLOCK + GLYPH_PAD, 0, WHITE_BLOCK
    for size in sizes:
        font = pygame.font.SysFont(FONT_NAME, size, bold=True)
        gs = glyph_sets[size] = GlyphSet(font.get_linesize())
        for i in range(_GLYPH_COUNT):
            ch = chr(ASCII_FIRST + i)
            surf = font.render(ch, True, (255, 255, 255))
            gw, gh = surf.get_size()
            if x + gw + GLYPH_PAD > width:   # wrap to the next row
                x, y, row_h = 0, y + row_h + GLYPH_PAD, 0
            placements.append((surf, x, y, gs, i))
            gs.w[i], gs.h[i] = gw, gh
            gs.adv[i] = font.size(ch)[0]
            row_h = max(row_h, gh)
            x += gw + GLYPH_PAD
    height = y + row_h
    pixels = np.zeros((height, width), dtype=np.uint8)
    pixels[:WHITE_BLOCK, :WHITE_BLOCK] = 255
    for surf, gx, gy, gs, i in placements:
        alpha = pygame.surfarray.array_alpha(surf).T       # (h, w)
        pixels[gy:gy + alpha.shape[0], gx:gx + alpha.shape[1]] = alpha
        gs.u0[i] = gx / width
        gs.u1[i] = (gx + gs.w[i]) / width
        gs.v0[i] = gy / height
        gs.v1[i] = (gy + gs.h[i]) / height
    return pixels, glyph_sets


# ---------------------------------------------------------------- GL side

OVERLAY_VERT = """
#version 330 core
layout(location=0) in vec2 a_pos;   // screen pixels, origin top-left
layout(location=1) in vec2 a_uv;
layout(location=2) in vec4 a_col;
uniform vec2 u_screen;              // viewport size in pixels
out vec2 v_uv; out vec4 v_col;
void main(){
    vec2 ndc = vec2(a_pos.x * 2.0 / u_screen.x - 1.0,
                    1.0 - a_pos.y * 2.0 / u_screen.y);
    gl_Position = vec4(ndc, 0.0, 1.0);  // ortho overlay: no log depth
    v_uv = a_uv; v_col = a_col;
}
"""

OVERLAY_FRAG = """
#version 330 core
in vec2 v_uv; in vec4 v_col;
uniform sampler2D u_tex;
out vec4 frag;
void main(){
    float a = texture(u_tex, v_uv).r * v_col.a;
    if (a < 0.002) discard;
    frag = vec4(v_col.rgb, a);          // unlit: color straight through
}
"""


class TextRenderer:
    """Batched 2D overlay renderer (GL-touching; never imported by tests).

    All draw_* calls append quads to one batch (kept in submission order,
    so panels drawn first sit behind the text drawn onto them); ``flush``
    streams the batch to the GPU and draws it in a single call.
    """

    def __init__(self):
        import ctypes

        import OpenGL.GL as gl

        from engine.shader import Shader
        self._gl = gl
        pixels, self.glyphs = bake_atlas()
        h, w = pixels.shape
        # Center of the solid block: safe under linear filtering.
        self._white_uv = (WHITE_BLOCK * 0.5 / w, WHITE_BLOCK * 0.5 / h)

        self.tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R8, w, h, 0, gl.GL_RED,
                        gl.GL_UNSIGNED_BYTE, np.ascontiguousarray(pixels))
        for pname, val in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                           (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                           (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                           (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, pname, val)

        self.shader = Shader(OVERLAY_VERT, OVERLAY_FRAG)
        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        for loc, n, offset in ((0, 2, 0), (1, 2, 8), (2, 4, 16)):
            gl.glVertexAttribPointer(loc, n, gl.GL_FLOAT, gl.GL_FALSE,
                                     _STRIDE, ctypes.c_void_p(offset))
            gl.glEnableVertexAttribArray(loc)
        gl.glBindVertexArray(0)

        self._batch: list[np.ndarray] = []
        # draw_text quad cache (Task 22 perf): the HUD redraws mostly-static
        # strings at fixed positions every frame; building glyph quads is
        # ~100 us per string, a dict hit is ~1 us. Entries are immutable
        # once stored (flush only reads). Cleared when it hits the cap so
        # ever-changing telemetry values cannot grow it without bound.
        self._text_cache: dict[tuple, np.ndarray] = {}
        self._width_cache: dict[tuple, float] = {}

    _TEXT_CACHE_MAX = 1024

    # ------------------------------------------------------------- metrics

    @staticmethod
    def _codes(s: str) -> np.ndarray:
        """Glyph indices for a string (non-ASCII -> '?', controls -> space)."""
        codes = np.frombuffer(s.encode("ascii", "replace"),
                              dtype=np.uint8).astype(np.intp)
        return np.clip(codes - ASCII_FIRST, 0, _GLYPH_COUNT - 1)

    def text_width(self, s: str, size: int = BODY_SIZE) -> float:
        """Advance width of ``s`` in pixels at the given font size."""
        key = (s, size)
        w = self._width_cache.get(key)
        if w is None:
            if len(self._width_cache) >= self._TEXT_CACHE_MAX:
                self._width_cache.clear()
            w = float(self.glyphs[size].adv[self._codes(s)].sum())
            self._width_cache[key] = w
        return w

    def line_height(self, size: int = BODY_SIZE) -> int:
        """Recommended baseline-to-baseline line height in pixels."""
        return self.glyphs[size].line_h

    # -------------------------------------------------------------- batching

    @staticmethod
    def _quads(x0, y0, w, h, u0, v0, u1, v1, rgba) -> np.ndarray:
        """(n*6, 8) float32 triangle vertices for n axis-aligned quads.
        Array args are (n,) (scalars broadcast); rgba is one 4-tuple."""
        n = len(x0)
        out = np.empty((n, 6, _FLOATS_PER_VERT), dtype=np.float32)
        for c, (fx, fy) in enumerate(_TRI_CORNERS):
            out[:, c, 0] = x0 + w * fx
            out[:, c, 1] = y0 + h * fy
            out[:, c, 2] = u0 + (u1 - u0) * fx
            out[:, c, 3] = v0 + (v1 - v0) * fy
        out[:, :, 4:8] = np.asarray(rgba, dtype=np.float32)
        return out.reshape(n * 6, _FLOATS_PER_VERT)

    def draw_text(self, x, y, s: str, color=(1.0, 1.0, 1.0),
                  size: int = BODY_SIZE, scale: float = 1.0) -> None:
        """Queue ``s`` with its top-left corner at (x, y) screen pixels.

        ``scale`` multiplies the glyph quads + advances (e.g. the menu
        title: 28 pt atlas glyphs x3) without rebaking the atlas; width is
        ``text_width(s, size) * scale``.
        """
        rgba = _rgba(color)
        key = (s, size, scale, rgba, float(x), float(y))
        cached = self._text_cache.get(key)
        if cached is not None:
            self._batch.append(cached)
            return
        g = self.glyphs[size]
        codes = self._codes(s)
        if len(codes) == 0:
            return
        adv = g.adv[codes].astype(np.float64) * scale
        pen = np.round(float(x)
                       + np.concatenate(([0.0], np.cumsum(adv)[:-1])))
        quads = self._quads(
            pen.astype(np.float32), np.float32(round(float(y))),
            g.w[codes] * np.float32(scale), g.h[codes] * np.float32(scale),
            g.u0[codes], g.v0[codes], g.u1[codes], g.v1[codes],
            rgba)
        if len(self._text_cache) >= self._TEXT_CACHE_MAX:
            self._text_cache.clear()
        self._text_cache[key] = quads
        self._batch.append(quads)

    def draw_rect(self, x, y, w, h, rgba) -> None:
        """Queue a filled rectangle (top-left x, y; size w, h pixels)."""
        u, v = self._white_uv
        self._batch.append(self._quads(
            np.array([x], dtype=np.float32), np.float32(y),
            np.array([w], dtype=np.float32), np.array([h], dtype=np.float32),
            np.float32(u), np.float32(v), np.float32(u), np.float32(v),
            _rgba(rgba)))

    def draw_lines(self, points, rgba, width: float = DEFAULT_LINE_WIDTH) -> None:
        """Queue a polyline through ``points`` [(x, y), ...] screen pixels.

        Segments are expanded into quads on the CPU (core-profile
        glLineWidth > 1 is unreliable), so any stroke width works.
        """
        p = np.asarray(points, dtype=np.float32)
        if p.ndim != 2 or p.shape[0] < 2:
            return
        a, b = p[:-1], p[1:]
        d = b - a
        length = np.hypot(d[:, 0], d[:, 1])
        keep = length > 1e-6
        if not keep.any():
            return
        a, b, d, length = a[keep], b[keep], d[keep], length[keep]
        nrm = (np.stack([-d[:, 1], d[:, 0]], axis=1)
               / length[:, None] * (0.5 * float(width)))
        n = len(a)
        out = np.empty((n, 6, _FLOATS_PER_VERT), dtype=np.float32)
        out[:, 0, :2] = a + nrm
        out[:, 1, :2] = b + nrm
        out[:, 2, :2] = b - nrm
        out[:, 3, :2] = a + nrm
        out[:, 4, :2] = b - nrm
        out[:, 5, :2] = a - nrm
        u, v = self._white_uv
        out[:, :, 2] = u
        out[:, :, 3] = v
        out[:, :, 4:8] = np.asarray(_rgba(rgba), dtype=np.float32)
        self._batch.append(out.reshape(n * 6, _FLOATS_PER_VERT))

    # ----------------------------------------------------------------- flush

    def flush(self, screen_w: int, screen_h: int) -> None:
        """Draw and clear the queued batch in one ortho overlay pass."""
        if not self._batch:
            return
        gl = self._gl
        data = (self._batch[0] if len(self._batch) == 1
                else np.concatenate(self._batch))
        self._batch.clear()

        # Overlay pass: no depth, no culling (global glFrontFace(GL_CW)
        # would otherwise drop overlay quads), standard alpha blending.
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        self.shader.use()
        self.shader.set_vec2("u_screen", (float(screen_w), float(screen_h)))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        self.shader.set_int("u_tex", 0)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data,
                        gl.GL_STREAM_DRAW)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, len(data))
        gl.glBindVertexArray(0)

        # Restore the scene-pass state set up by engine.window.
        gl.glDisable(gl.GL_BLEND)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_DEPTH_TEST)

    def delete(self) -> None:
        gl = self._gl
        if self.vao:
            gl.glDeleteVertexArrays(1, [self.vao])
            gl.glDeleteBuffers(1, [self.vbo])
            gl.glDeleteTextures(1, [self.tex])
            self.vao = self.vbo = self.tex = 0
