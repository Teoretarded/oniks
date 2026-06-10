"""Procedural mesh data: MeshBuilder + primitive generators.

Pure numpy, GL-free (safe to import in headless tests).

Conventions (LOCKED):
- Vertex layout: interleaved float32 ``[px py pz nx ny nz r g b]`` (9 floats),
  ``uint32`` indices. Attribute locations 0=pos, 1=normal, 2=color.
- Model space: forward = +Z, up = +Y. Real scale in meters, origin at the
  object's center of rotation.
- Winding: counter-clockwise front faces, normals point outward.
"""

from __future__ import annotations

import math

import numpy as np

_EPS = 1e-9

# out[:, j] = in[:, perm[j]]  (cyclic permutations: proper rotations)
_AXIS_PERM = {
    "x": (2, 0, 1),  # local z -> world x
    "y": (1, 2, 0),  # local z -> world y
    "z": (0, 1, 2),  # identity
}


class MeshData:
    """Plain container for CPU-side mesh data."""

    __slots__ = ("vertices", "indices")

    def __init__(self, vertices: np.ndarray, indices: np.ndarray):
        self.vertices = vertices  # (N, 9) float32: pos3 normal3 color3
        self.indices = indices    # (M,)  uint32


class MeshBuilder:
    """Accumulates MeshData pieces (with optional transforms) into one mesh."""

    def __init__(self):
        self._vertices: list[np.ndarray] = []
        self._indices: list[np.ndarray] = []
        self._count = 0

    def add_mesh(self, md: MeshData, offset=(0.0, 0.0, 0.0), rotation=None,
                 scale: float = 1.0) -> None:
        """Append a copy of ``md`` transformed by rotation, then scale, then offset.

        ``rotation`` is a (3,3) rotation matrix applied to positions AND normals.
        ``scale`` is uniform (normals unaffected). Indices are re-based.
        """
        v = md.vertices.copy()
        pos = v[:, 0:3]
        nrm = v[:, 3:6]
        if rotation is not None:
            rot = np.asarray(rotation, dtype=np.float32)
            pos = pos @ rot.T
            nrm = nrm @ rot.T
        pos = pos * np.float32(scale) + np.asarray(offset, dtype=np.float32)
        v[:, 0:3] = pos
        v[:, 3:6] = nrm
        self._vertices.append(v)
        self._indices.append(md.indices.astype(np.uint32) + np.uint32(self._count))
        self._count += len(v)

    def build(self) -> MeshData:
        if not self._vertices:
            return MeshData(np.empty((0, 9), np.float32), np.empty(0, np.uint32))
        return MeshData(np.concatenate(self._vertices, axis=0),
                        np.concatenate(self._indices, axis=0))


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _add_poly(verts: list, idx: list, corners, normal, color) -> None:
    """Append a convex polygon (corners CCW about ``normal``) as a triangle fan."""
    base = len(verts)
    nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
    r, g, b = float(color[0]), float(color[1]), float(color[2])
    for c in corners:
        verts.append((float(c[0]), float(c[1]), float(c[2]), nx, ny, nz, r, g, b))
    for i in range(1, len(corners) - 1):
        idx.extend((base, base + i, base + i + 1))


def _finish(verts: list, idx: list, offset) -> MeshData:
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 9)
    off = np.asarray(offset, dtype=np.float32)
    if off.any():
        v[:, 0:3] += off
    return MeshData(v, np.asarray(idx, dtype=np.uint32))


def _face_normal(c0, c1, c2):
    n = np.cross(np.subtract(c1, c0, dtype=np.float64),
                 np.subtract(c2, c0, dtype=np.float64))
    return n / np.linalg.norm(n)


# ---------------------------------------------------------------------------
# primitive generators
# ---------------------------------------------------------------------------

def make_box(size_xyz, color, offset=(0, 0, 0)) -> MeshData:
    """Axis-aligned box centered at origin, flat normals (24 verts, 36 indices)."""
    half = np.asarray(size_xyz, dtype=np.float64) * 0.5
    eye = np.eye(3)
    verts: list = []
    idx: list = []
    for a in range(3):
        ua, va = (a + 1) % 3, (a + 2) % 3
        for s in (1.0, -1.0):
            n = s * eye[a]
            u = s * eye[ua]
            v = eye[va]
            c = n * half[a]
            hu, hv = half[ua], half[va]
            corners = (c - u * hu - v * hv, c + u * hu - v * hv,
                       c + u * hu + v * hv, c - u * hu + v * hv)
            _add_poly(verts, idx, corners, n, color)
    return _finish(verts, idx, offset)


def make_cylinder(radius, length, segments, color, axis="z", offset=(0, 0, 0),
                  cap_ends=True, smooth=True) -> MeshData:
    """Cylinder centered at origin along ``axis`` (extent ±length/2)."""
    h = length * 0.5
    theta = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    cs, sn = np.cos(theta), np.sin(theta)
    verts: list = []
    idx: list = []
    if smooth:
        for zz in (-h, h):
            for k in range(segments):
                verts.append((radius * cs[k], radius * sn[k], zz,
                              cs[k], sn[k], 0.0, *color))
        for k in range(segments):
            k2 = (k + 1) % segments
            b, b2, t, t2 = k, k2, segments + k, segments + k2
            idx.extend((b, b2, t2, b, t2, t))
    else:
        for k in range(segments):
            k2 = (k + 1) % segments
            thm = theta[k] + np.pi / segments  # facet mid-angle
            n = (math.cos(thm), math.sin(thm), 0.0)
            corners = ((radius * cs[k], radius * sn[k], -h),
                       (radius * cs[k2], radius * sn[k2], -h),
                       (radius * cs[k2], radius * sn[k2], h),
                       (radius * cs[k], radius * sn[k], h))
            _add_poly(verts, idx, corners, n, color)
    if cap_ends:
        for zz, nz in ((-h, -1.0), (h, 1.0)):
            base = len(verts)
            verts.append((0.0, 0.0, zz, 0.0, 0.0, nz, *color))
            for k in range(segments):
                verts.append((radius * cs[k], radius * sn[k], zz,
                              0.0, 0.0, nz, *color))
            for k in range(segments):
                k2 = (k + 1) % segments
                if nz > 0.0:
                    idx.extend((base, base + 1 + k, base + 1 + k2))
                else:
                    idx.extend((base, base + 1 + k2, base + 1 + k))
    md = _finish(verts, idx, (0.0, 0.0, 0.0))
    perm = list(_AXIS_PERM[axis])
    md.vertices[:, 0:3] = md.vertices[:, perm]
    md.vertices[:, 3:6] = md.vertices[:, [3 + p for p in perm]]
    md.vertices[:, 0:3] += np.asarray(offset, dtype=np.float32)
    return md


def make_lathe(profile, segments, color, smooth=True, offset=(0, 0, 0)) -> MeshData:
    """Surface of revolution around +Z.

    ``profile``: list of ``(z, radius)`` ordered by increasing z. Radius-0
    entries create tip points. Smooth normals come from adjacent profile
    slopes; non-smooth duplicates rings per band (hard edges between bands).
    """
    zs = np.asarray([p[0] for p in profile], dtype=np.float64)
    rs = np.asarray([p[1] for p in profile], dtype=np.float64)
    nb = len(profile) - 1
    theta = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    cs, sn = np.cos(theta), np.sin(theta)

    # per-band slope normal in the (radial, z) plane: (n_r, n_z) = (dz, -dr) / len
    band_n = []
    for j in range(nb):
        dz, dr = zs[j + 1] - zs[j], rs[j + 1] - rs[j]
        length = math.hypot(dz, dr)
        band_n.append((dz / length, -dr / length))

    verts: list = []
    idx: list = []

    def _ring(rr, zz, nr, nz):
        for k in range(segments):
            verts.append((rr * cs[k], rr * sn[k], zz,
                          nr * cs[k], nr * sn[k], nz, *color))

    def _band_tris(a, b, ra, rb):
        for k in range(segments):
            k2 = (k + 1) % segments
            if ra > _EPS:
                idx.extend((a + k, a + k2, b + k2))
            if rb > _EPS:
                idx.extend((a + k, b + k2, b + k))

    if smooth:
        for i in range(len(profile)):
            if i == 0:
                nr, nz = band_n[0]
            elif i == nb:
                nr, nz = band_n[-1]
            else:
                nr = band_n[i - 1][0] + band_n[i][0]
                nz = band_n[i - 1][1] + band_n[i][1]
                length = math.hypot(nr, nz)
                if length < _EPS:  # opposing slopes; fall back to lower band
                    nr, nz = band_n[i - 1]
                else:
                    nr, nz = nr / length, nz / length
            _ring(rs[i], zs[i], nr, nz)
        for j in range(nb):
            _band_tris(j * segments, (j + 1) * segments, rs[j], rs[j + 1])
    else:
        for j in range(nb):
            nr, nz = band_n[j]
            base = len(verts)
            _ring(rs[j], zs[j], nr, nz)
            _ring(rs[j + 1], zs[j + 1], nr, nz)
            _band_tris(base, base + segments, rs[j], rs[j + 1])
    return _finish(verts, idx, offset)


def make_wedge(size_xyz, color, offset=(0, 0, 0)) -> MeshData:
    """Triangular prism centered at origin; sloped face descends toward +Z.

    Full-height back face at -Z, flat bottom at -Y; the slope runs from the
    top back edge down to the bottom front edge (normal points +Y and +Z).
    """
    hx, hy, hz = (s * 0.5 for s in size_xyz)
    verts: list = []
    idx: list = []
    # +X / -X triangular ends
    _add_poly(verts, idx,
              ((hx, -hy, -hz), (hx, hy, -hz), (hx, -hy, hz)),
              (1.0, 0.0, 0.0), color)
    _add_poly(verts, idx,
              ((-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, -hz)),
              (-1.0, 0.0, 0.0), color)
    # bottom (-Y)
    _add_poly(verts, idx,
              ((-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)),
              (0.0, -1.0, 0.0), color)
    # back (-Z)
    _add_poly(verts, idx,
              ((-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz)),
              (0.0, 0.0, -1.0), color)
    # slope (+Y, +Z)
    slope_n = np.array([0.0, 2.0 * hz, 2.0 * hy])
    slope_n /= np.linalg.norm(slope_n)
    _add_poly(verts, idx,
              ((-hx, hy, -hz), (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, -hz)),
              slope_n, color)
    return _finish(verts, idx, offset)


def make_fin(root_chord, tip_chord, span, sweep, thickness, color,
             offset=(0, 0, 0)) -> MeshData:
    """Flat trapezoidal plate: span along +X, chord along Z, thickness in Y.

    Origin at the root leading edge; chords extend toward -Z (aft). The tip
    leading edge sits ``sweep`` meters behind the root leading edge.
    """
    ht = thickness * 0.5
    # planform corners in CCW order viewed from +Y
    root_le = (0.0, 0.0)
    tip_le = (span, -sweep)
    tip_te = (span, -sweep - tip_chord)
    root_te = (0.0, -root_chord)
    loop = (root_le, tip_le, tip_te, root_te)
    top = [(x, ht, z) for x, z in loop]
    bot = [(x, -ht, z) for x, z in loop]
    verts: list = []
    idx: list = []
    _add_poly(verts, idx, top, (0.0, 1.0, 0.0), color)
    _add_poly(verts, idx, list(reversed(bot)), (0.0, -1.0, 0.0), color)
    for i in range(4):
        j = (i + 1) % 4
        if math.dist(loop[i], loop[j]) < _EPS:  # degenerate edge (e.g. tip_chord=0)
            continue
        corners = (bot[i], bot[j], top[j], top[i])
        _add_poly(verts, idx, corners,
                  _face_normal(corners[0], corners[1], corners[2]), color)
    return _finish(verts, idx, offset)


def make_grid(xs, zs, heights, colors) -> MeshData:
    """Heightfield grid: xs (W,), zs (H,), heights (H,W), colors (H,W,3).

    Smooth normals via central differences. Front faces point +Y.
    """
    xs = np.asarray(xs, dtype=np.float64)
    zs = np.asarray(zs, dtype=np.float64)
    h = np.asarray(heights, dtype=np.float64)
    c = np.asarray(colors, dtype=np.float32)
    nz_rows, nx_cols = h.shape
    gx, gz = np.meshgrid(xs, zs)  # both (H, W)
    dhdz, dhdx = np.gradient(h, zs, xs)
    n = np.stack((-dhdx, np.ones_like(h), -dhdz), axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)

    v = np.empty((nz_rows * nx_cols, 9), dtype=np.float32)
    v[:, 0] = gx.ravel()
    v[:, 1] = h.ravel()
    v[:, 2] = gz.ravel()
    v[:, 3:6] = n.reshape(-1, 3)
    v[:, 6:9] = c.reshape(-1, 3)

    grid = np.arange(nz_rows * nx_cols, dtype=np.uint32).reshape(nz_rows, nx_cols)
    v00 = grid[:-1, :-1].ravel()  # (x,   z)
    v10 = grid[:-1, 1:].ravel()   # (x+1, z)
    v01 = grid[1:, :-1].ravel()   # (x,   z+1)
    v11 = grid[1:, 1:].ravel()    # (x+1, z+1)
    indices = np.stack((v00, v11, v10, v00, v01, v11), axis=1).ravel()
    return MeshData(v, indices.astype(np.uint32))
