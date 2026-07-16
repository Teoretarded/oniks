"""Bake deterministic tree instances and a procedural billboard atlas.

This is the GL-free companion to :mod:`world.cinematic_trees`.  It turns
the LiDAR clutter layer into sparse tree records by combining height with
orthophoto greenness, then applies deterministic spacing and density
limits.  Coordinates follow the cinematic scene convention: X east, Z
north, Y up; height grids and the full-scene DTM have row 0 at SOUTH,
while orthophoto row 0 is NORTH.

Output, beside ``scene.json``::

    trees_<e>_<n>.npz  x, z, base_y, height, radius, tint, species
    tree_atlas.png     three 256 x 512 RGBA procedural silhouettes

No external image assets or OpenGL context are required.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import numpy as np
from PIL import Image, ImageFilter


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES_ROOT = os.path.join(REPO_ROOT, "assets", "cinematic")

TREE_MIN_HEIGHT = 2.5
TREE_MAX_HEIGHT = 45.0
MAX_TREES_PER_TILE = 14_000
MIN_SPACING_M = 4.0
ATLAS_CELL_W = 256
ATLAS_H = 512


def _ortho_grid_rgb(ortho: Image.Image, shape: tuple[int, int]) -> np.ndarray:
    """Return RGB sampled onto a south-first ``(nz, nx)`` point grid.

    BOX resampling averages a small source-pixel neighbourhood (about one
    metre for the normal 4096 px / 1 km imagery), suppressing single-pixel
    JPEG colour noise.  The vertical flip converts image north-first rows
    to the LiDAR grid's south-first rows.
    """
    nz, nx = shape
    rgb = ortho.convert("RGB").resize((nx, nz), Image.Resampling.BOX)
    return np.asarray(rgb, dtype=np.uint8)[::-1].copy()


def classify_tree_cells(
    clutter_1m: np.ndarray,
    ortho: Image.Image,
    *,
    halo: bool = True,
) -> np.ndarray:
    """Classify plausible tree points from clutter height and greenness.

    ``clutter_1m`` may be a baked grid with its one-cell halo (the default)
    or an already-interior grid with ``halo=False``.  The returned bool
    mask has the shape of the corresponding interior.  Green is deliberately
    a relative test: shaded forest remains eligible while neutral grey and
    brown roofs are rejected.
    """
    clutter = np.asarray(clutter_1m, dtype=np.float32)
    if clutter.ndim != 2:
        raise ValueError("clutter_1m must be a 2D array")
    if halo:
        if min(clutter.shape) < 3:
            raise ValueError("haloed clutter_1m must be at least 3 x 3")
        clutter = clutter[1:-1, 1:-1]

    rgb = _ortho_grid_rgb(ortho, clutter.shape).astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    green = (g > r * 1.05) & (g > b * 1.05)
    tall = (clutter >= TREE_MIN_HEIGHT) & (clutter <= TREE_MAX_HEIGHT)
    return tall & green & np.isfinite(clutter)


def _coordinate_hash(x: np.ndarray, z: np.ndarray, seed: int = 0) -> np.ndarray:
    """Stable SplitMix64-style hash for signed integer grid coordinates."""
    ux = np.asarray(x, dtype=np.int64).view(np.uint64)
    uz = np.asarray(z, dtype=np.int64).view(np.uint64)
    h = ux * np.uint64(0x9E3779B185EBCA87)
    h ^= uz * np.uint64(0xC2B2AE3D27D4EB4F)
    h ^= np.uint64(seed & 0xFFFFFFFFFFFFFFFF)
    h ^= h >> np.uint64(30)
    h *= np.uint64(0xBF58476D1CE4E5B9)
    h ^= h >> np.uint64(27)
    h *= np.uint64(0x94D049BB133111EB)
    h ^= h >> np.uint64(31)
    return h


def thin_tree_cells(
    rows: np.ndarray,
    cols: np.ndarray,
    heights: np.ndarray,
    *,
    max_count: int = MAX_TREES_PER_TILE,
    min_spacing: float = MIN_SPACING_M,
    origin_col: int = 0,
    origin_row: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Thin candidate cell coordinates deterministically.

    A global-grid-aligned winner-take-all pass keeps the tallest candidate
    in each spacing-sized bin (hash breaks exact ties).  A small exact disk
    pass then prevents close winners across adjacent bin edges.  If the
    result still exceeds ``max_count``, a coordinate hash chooses the final
    set with a mild height preference.  Output is row-major and therefore
    byte-identical for identical inputs, including differently ordered
    candidate arrays.
    """
    rows = np.asarray(rows, dtype=np.int64).ravel()
    cols = np.asarray(cols, dtype=np.int64).ravel()
    heights = np.asarray(heights, dtype=np.float32).ravel()
    if not (rows.size == cols.size == heights.size):
        raise ValueError("rows, cols and heights must have equal lengths")
    if rows.size == 0 or max_count <= 0:
        empty = np.empty(0, dtype=np.int32)
        return empty, empty.copy()
    if min_spacing <= 0.0:
        raise ValueError("min_spacing must be positive")

    gx = cols + int(origin_col)
    gz = rows + int(origin_row)
    hashes = _coordinate_hash(gx, gz, seed=0x54524545)

    # One local maximum per globally aligned spacing-sized bin.
    block = max(1, int(round(min_spacing)))
    bx = np.floor_divide(gx, block)
    bz = np.floor_divide(gz, block)
    span = int(bx.max() - bx.min() + 1)
    group = (bz - bz.min()) * span + (bx - bx.min())
    order = np.lexsort((hashes, -heights, group))
    sorted_group = group[order]
    first = np.empty(order.size, dtype=bool)
    first[0] = True
    first[1:] = sorted_group[1:] != sorted_group[:-1]
    winners = order[first]

    # Enforce the actual Euclidean spacing across adjacent block edges.
    wr = rows[winners]
    wc = cols[winners]
    wh = heights[winners]
    w_hash = hashes[winners]
    priority = np.lexsort((w_hash, -wh))
    r0, c0 = int(rows.min()), int(cols.min())
    forbidden = np.zeros(
        (int(rows.max()) - r0 + 1, int(cols.max()) - c0 + 1), dtype=bool
    )
    reach = int(np.ceil(min_spacing))
    offsets = [(dr, dc) for dr in range(-reach, reach + 1)
               for dc in range(-reach, reach + 1)
               if dr * dr + dc * dc < min_spacing * min_spacing]
    kept: list[int] = []
    for wi in priority:
        rr = int(wr[wi]) - r0
        cc = int(wc[wi]) - c0
        if forbidden[rr, cc]:
            continue
        kept.append(int(wi))
        for dr, dc in offsets:
            y, x = rr + dr, cc + dc
            if 0 <= y < forbidden.shape[0] and 0 <= x < forbidden.shape[1]:
                forbidden[y, x] = True

    kept_arr = np.asarray(kept, dtype=np.int64)
    if kept_arr.size > max_count:
        # Lower score wins.  Hash is dominant, height gently improves odds.
        u = (w_hash[kept_arr] >> np.uint64(11)).astype(np.float64)
        u *= 1.0 / float(1 << 53)
        preference = 0.75 + np.clip(wh[kept_arr], TREE_MIN_HEIGHT,
                                    TREE_MAX_HEIGHT) / TREE_MAX_HEIGHT
        score = u / preference
        take = np.argpartition(score, max_count - 1)[:max_count]
        kept_arr = kept_arr[take]

    out_r = wr[kept_arr].astype(np.int32, copy=False)
    out_c = wc[kept_arr].astype(np.int32, copy=False)
    final_order = np.lexsort((out_c, out_r))
    return out_r[final_order].copy(), out_c[final_order].copy()


def _shape_masks(species: int, xx: np.ndarray, yy: np.ndarray) -> tuple:
    """Return silhouette and band id for one normalized atlas cell."""
    trunk = (np.abs(xx) < (0.075 if species != 1 else 0.10)) \
        & (yy > 0.002) & (yy < 0.30)
    if species == 0:  # dense alpine spruce: stacked triangular skirts
        crown = np.zeros_like(xx, dtype=bool)
        band = np.zeros_like(xx, dtype=np.int16)
        for k, (centre, half_h, half_w) in enumerate((
                (0.31, 0.18, 0.78), (0.47, 0.20, 0.66),
                (0.63, 0.20, 0.53), (0.78, 0.18, 0.36),
                (0.90, 0.12, 0.18))):
            local = (yy - (centre - half_h)) / (2.0 * half_h)
            layer = (local >= 0.0) & (local <= 1.0) \
                & (np.abs(xx) <= half_w * (1.0 - local))
            crown |= layer
            band[layer] = k + 1
    elif species == 1:  # broadleaf crown made from overlapping lobes
        crown = np.zeros_like(xx, dtype=bool)
        band = np.zeros_like(xx, dtype=np.int16)
        lobes = ((-0.34, 0.55, 0.48, 0.23),
                 (0.31, 0.56, 0.50, 0.24),
                 (0.00, 0.73, 0.56, 0.27),
                 (-0.03, 0.42, 0.70, 0.23))
        for k, (cx, cy, rx, ry) in enumerate(lobes):
            layer = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
            crown |= layer
            band[layer] = k + 1
    else:  # narrow, irregular fir/pine
        crown = np.zeros_like(xx, dtype=bool)
        band = np.zeros_like(xx, dtype=np.int16)
        for k, (centre, half_h, half_w) in enumerate((
                (0.30, 0.14, 0.62), (0.42, 0.16, 0.56),
                (0.55, 0.17, 0.49), (0.68, 0.17, 0.40),
                (0.80, 0.16, 0.29), (0.91, 0.11, 0.15))):
            local = (yy - (centre - half_h)) / (2.0 * half_h)
            wobble = 1.0 + 0.08 * np.sin(yy * 91.0 + k * 2.1)
            layer = (local >= 0.0) & (local <= 1.0) \
                & (np.abs(xx) <= half_w * (1.0 - local) * wobble)
            crown |= layer
            band[layer] = k + 1
    return crown | trunk, crown, trunk, band


def generate_tree_atlas(seed: int = 7319) -> Image.Image:
    """Return the deterministic 768 x 512 RGBA three-species atlas."""
    width = ATLAS_CELL_W * 3
    atlas = np.zeros((ATLAS_H, width, 4), dtype=np.uint8)
    rng = np.random.default_rng(seed)
    x = (np.arange(ATLAS_CELL_W, dtype=np.float32) + 0.5) \
        / ATLAS_CELL_W * 2.0 - 1.0
    # Image row 0 is top; normalized y grows upward from the sprite base.
    y = 1.0 - (np.arange(ATLAS_H, dtype=np.float32) + 0.5) / ATLAS_H
    xx, yy = np.meshgrid(x, y)
    palettes = (
        (np.array([42, 80, 35]), np.array([77, 119, 57])),
        (np.array([48, 78, 31]), np.array([92, 126, 53])),
        (np.array([31, 70, 39]), np.array([61, 106, 58])),
    )

    for species in range(3):
        mask, crown, trunk, band = _shape_masks(species, xx, yy)
        noise = rng.random(mask.shape, dtype=np.float32)
        # A one-pixel inner edge gets noisy alpha and occasional erosion.
        eroded = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255)
                            .filter(ImageFilter.MinFilter(3))) > 0
        edge = mask & ~eroded
        alpha = np.zeros(mask.shape, dtype=np.uint8)
        alpha[eroded] = 255
        edge_alpha = (70.0 + noise * 185.0).astype(np.uint8)
        alpha[edge] = edge_alpha[edge]
        alpha[edge & (noise < 0.10)] = 0

        dark, light = palettes[species]
        ao = np.clip(0.48 + yy * 0.62, 0.42, 1.0)[..., None]
        band_light = (0.80 + (band % 3) * 0.085)[..., None]
        grain = (0.90 + noise[..., None] * 0.18)
        mix = np.clip(yy[..., None] * 0.75 + noise[..., None] * 0.25,
                      0.0, 1.0)
        rgb = (dark + (light - dark) * mix) * ao * band_light * grain
        trunk_rgb = np.array([54, 39, 24], dtype=np.float32) \
            * np.clip(0.52 + yy[..., None] * 0.55, 0.45, 1.0)
        rgb = np.where(trunk[..., None] & ~crown[..., None], trunk_rgb, rgb)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        rgb[~mask] = 0

        x0 = species * ATLAS_CELL_W
        atlas[:, x0:x0 + ATLAS_CELL_W, :3] = rgb
        atlas[:, x0:x0 + ATLAS_CELL_W, 3] = alpha
    return Image.fromarray(atlas, mode="RGBA")


def _tree_output_name(hgt_name: str) -> str:
    match = re.fullmatch(r"tile_(.+)_hgt\.npz", os.path.basename(hgt_name))
    if not match:
        raise ValueError(f"unexpected cinematic tile name: {hgt_name}")
    return "trees_" + match.group(1) + ".npz"


def bake_scene(scene: str) -> list[tuple[str, int]]:
    """Bake every tile in ``scene`` and return ``[(tile_id, count), ...]``."""
    scene_dir = scene if os.path.isdir(scene) else os.path.join(SCENES_ROOT, scene)
    scene_dir = os.path.abspath(scene_dir)
    with open(os.path.join(scene_dir, "scene.json"), encoding="utf-8") as f:
        meta = json.load(f)

    atlas_path = os.path.join(scene_dir, "tree_atlas.png")
    if not os.path.exists(atlas_path):
        generate_tree_atlas().save(atlas_path, optimize=True)
        print(f"[{meta.get('name', scene)}] wrote tree_atlas.png")

    dtm_rec = meta["dtm"]
    dtm_cell = float(dtm_rec.get("cell", 1.0))
    dtm = np.load(os.path.join(scene_dir, dtm_rec["file"]), mmap_mode="r")
    scene_x0, scene_z0 = float(meta["x0"]), float(meta["z0"])
    results: list[tuple[str, int]] = []

    for rec in meta["tiles"]:
        size = float(rec["size"])
        hgt_path = os.path.join(scene_dir, rec["hgt"])
        tex_path = os.path.join(scene_dir, rec["tex"])
        out_name = _tree_output_name(rec["hgt"])
        out_path = os.path.join(scene_dir, out_name)
        tile_id = out_name[len("trees_"):-len(".npz")]

        with np.load(hgt_path) as hgt:
            clutter_halo = np.asarray(hgt["clutter_1m"], dtype=np.float32)
        inner = clutter_halo[1:-1, 1:-1]
        cell = size / float(inner.shape[1] - 1)
        cells_x = min(inner.shape[1], int(round(size / cell)))
        cells_z = min(inner.shape[0], int(round(size / cell)))

        with Image.open(tex_path) as ortho:
            mask = classify_tree_cells(clutter_halo, ortho, halo=True)
            mask = mask[:cells_z, :cells_x]
            rows, cols = np.nonzero(mask)
            heights = inner[rows, cols]
            origin_col = int(round((float(rec["x0"]) - scene_x0) / cell))
            origin_row = int(round((float(rec["z0"]) - scene_z0) / cell))
            rows, cols = thin_tree_cells(
                rows, cols, heights,
                max_count=MAX_TREES_PER_TILE,
                min_spacing=MIN_SPACING_M / cell,
                origin_col=origin_col,
                origin_row=origin_row,
            )

            if rows.size:
                # Sample exact orthophoto pixels for the per-instance tint.
                source = np.asarray(ortho.convert("RGB"), dtype=np.uint8)
                px = np.rint(cols * cell / size * (source.shape[1] - 1)) \
                    .astype(np.int64)
                py = np.rint((1.0 - rows * cell / size)
                             * (source.shape[0] - 1)).astype(np.int64)
                tint = source[py, px].astype(np.float32) * (0.85 / 255.0)

        count = int(rows.size)
        if count == 0:
            if os.path.exists(out_path):
                os.remove(out_path)
            print(f"  tile {tile_id}: 0 trees (skipped)")
            results.append((tile_id, 0))
            continue

        x = cols.astype(np.float32) * np.float32(cell)
        z = rows.astype(np.float32) * np.float32(cell)
        height = inner[rows, cols].astype(np.float32)
        radius = np.clip(height * np.float32(0.28), 0.8, 4.5).astype(np.float32)

        gx = np.rint((float(rec["x0"]) + x - scene_x0) / dtm_cell) \
            .astype(np.int64)
        gz = np.rint((float(rec["z0"]) + z - scene_z0) / dtm_cell) \
            .astype(np.int64)
        gx = np.clip(gx, 0, dtm.shape[1] - 1)
        gz = np.clip(gz, 0, dtm.shape[0] - 1)
        base_y = np.asarray(dtm[gz, gx], dtype=np.float32)
        species_hash = _coordinate_hash(gx, gz, seed=0x53504543)
        species = (species_hash % np.uint64(3)).astype(np.uint8)

        np.savez_compressed(
            out_path,
            x=x.astype(np.float32),
            z=z.astype(np.float32),
            base_y=base_y,
            height=height,
            radius=radius,
            tint=np.asarray(tint, dtype=np.float32),
            species=species,
        )
        print(f"  tile {tile_id}: {count} trees")
        results.append((tile_id, count))

    total = sum(count for _, count in results)
    print(f"[{meta.get('name', scene)}] tree bake complete: {total} instances")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", nargs="?", default="lauterbrunnen",
                        help="scene name or path (default: lauterbrunnen)")
    args = parser.parse_args()
    bake_scene(args.scene)
    return 0


if __name__ == "__main__":
    sys.exit(main())
