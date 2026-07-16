"""GL-free asset catalog and feedback bundles for the hidden test lab.

The catalog contains only immutable data and dotted builder references.  Model
modules are imported when :func:`load_mesh_data` is called, never while this
module is imported, so menu/unit-test code does not acquire an OpenGL context.

Catalog ids are intentionally short and stable: they are persisted into test
feedback and should not be renamed when a display label changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import importlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, ClassVar

import numpy as np


CATEGORIES = (
    "ALL",
    "GROUND",
    "STRUCTURES",
    "AIRCRAFT",
    "SHIPS",
    "MISSILES",
    "WEATHER",
    "EFFECTS",
)

_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_MODULE_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


@dataclass(frozen=True, slots=True)
class TestAsset:
    """One immutable catalog entry.

    ``module``/``builder`` are strings by design.  ``builder_kwargs`` is a
    tuple of pairs rather than a dict so a frozen entry cannot hide mutable
    configuration.  Weather entries point at the GL-free preset resolver and
    carry their authoritative preset id; they are not MeshData and therefore
    cannot be passed to :func:`load_mesh_data`.
    """

    __test__: ClassVar[bool] = False

    id: str
    label: str
    category: str
    kind: str
    module: str
    builder: str
    builder_kwargs: tuple[tuple[str, object], ...] = ()
    preset_id: int | None = None
    tags: tuple[str, ...] = ()
    proxy_for: str | None = None

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.id):
            raise ValueError(f"invalid asset id {self.id!r}")
        if not self.label or self.label.strip() != self.label:
            raise ValueError("asset label must be non-empty and trimmed")
        if self.category not in CATEGORIES[1:]:
            raise ValueError(f"invalid asset category {self.category!r}")
        if self.kind not in ("mesh", "weather", "effect"):
            raise ValueError(f"invalid asset kind {self.kind!r}")
        if not _MODULE_RE.fullmatch(self.module):
            raise ValueError(f"invalid builder module {self.module!r}")
        if not self.builder.isidentifier():
            raise ValueError(f"invalid builder name {self.builder!r}")
        if not isinstance(self.builder_kwargs, tuple):
            raise TypeError("builder_kwargs must be an immutable tuple")
        keys: set[str] = set()
        for pair in self.builder_kwargs:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or not pair[0].isidentifier()):
                raise TypeError("builder kwargs must be (identifier, value) pairs")
            key, value = pair
            if key in keys:
                raise ValueError(f"duplicate builder kwarg {key!r}")
            keys.add(key)
            if value is not None and not isinstance(value, (bool, int, float, str)):
                raise TypeError("builder kwarg values must be immutable scalars")
        if not isinstance(self.tags, tuple) or any(
                not isinstance(tag, str) or not tag.strip() for tag in self.tags):
            raise TypeError("tags must be a tuple of non-empty strings")
        if self.kind == "mesh" and self.preset_id is not None:
            raise ValueError("mesh assets cannot carry a weather preset id")
        if self.kind == "weather" and (
                not isinstance(self.preset_id, int) or self.preset_id < 0):
            raise ValueError("weather assets require a non-negative preset id")
        if self.proxy_for is not None:
            if not _ID_RE.fullmatch(self.proxy_for) or self.proxy_for == self.id:
                raise ValueError(f"invalid proxy target {self.proxy_for!r}")
            if "(PROXY)" not in self.label:
                raise ValueError("proxy asset labels must include '(PROXY)'")

    @property
    def kwargs(self) -> dict[str, object]:
        """A fresh kwargs dict suitable for calling the lazy builder."""

        return dict(self.builder_kwargs)

    @property
    def builder_ref(self) -> str:
        return f"{self.module}:{self.builder}"


def _mesh(asset_id: str, label: str, category: str, module: str,
          builder: str, *, tags: tuple[str, ...] = (),
          proxy_for: str | None = None, **kwargs) -> TestAsset:
    return TestAsset(
        asset_id, label, category, "mesh", module, builder,
        tuple(sorted(kwargs.items())), tags=tags, proxy_for=proxy_for,
    )


def _weather(asset_id: str, label: str, preset_id: int,
             *tags: str) -> TestAsset:
    return TestAsset(
        asset_id, label, "WEATHER", "weather",
        "sim.atmosphere", "weather_preset", (("value", preset_id),),
        preset_id=preset_id, tags=tuple(tags),
    )


def _effect(asset_id: str, label: str, *tags: str) -> TestAsset:
    """A looping particle-effect driver (game/effects_catalog.py)."""
    return TestAsset(
        asset_id, label, "EFFECTS", "effect",
        "game.effects_catalog", "effect_driver",
        (("effect_id", asset_id),), tags=tuple(tags),
    )


# Public procedural model builders used by game/sandbox.py and game/combat.py.
# Variant rows correspond to geometry that is genuinely instantiated during a
# launch, not cosmetic aliases (for example Kalibr currently reuses Tomahawk).
TEST_ASSETS: tuple[TestAsset, ...] = (
    # Ground vehicles / launchers
    _mesh("bastion_tel_stowed", "BASTION TEL - STOWED", "GROUND",
          "models.bastion", "build_bastion_tel", elevation_deg=0.0,
          tags=("p-800", "launcher", "truck")),
    _mesh("bastion_tel_raised", "BASTION TEL - RAISED", "GROUND",
          "models.bastion", "build_bastion_tel", elevation_deg=88.0,
          tags=("p-800", "launcher", "truck")),
    _mesh("s300_tel_stowed", "S-300 TEL - STOWED", "GROUND",
          "models.s300", "build_s300_tel", elevation_deg=0.0,
          tags=("sam", "launcher", "truck")),
    _mesh("s300_tel_raised", "S-300 TEL - RAISED", "GROUND",
          "models.s300", "build_s300_tel", elevation_deg=90.0,
          tags=("sam", "launcher", "truck")),
    _mesh("pantsir", "PANTSIR-S1", "GROUND",
          "models.pantsir", "build_pantsir",
          tags=("sam", "shorad", "gun")),
    _mesh("buk_telar", "BUK 9A317 TELAR", "GROUND",
          "models.support_assets", "build_buk_telar",
          tags=("buk", "9a317", "launcher", "sam", "tracked")),
    _mesh("swarm_pod", "SWARM POD", "GROUND",
          "models.support_assets", "build_swarm_pod",
          tags=("loitering munition", "launcher", "palletized")),

    # Static structures
    _mesh("radar_station", "RADAR STATION", "STRUCTURES",
          "models.structures", "build_radar_station",
          tags=("sensor", "site")),
    _mesh("cbr_radar", "COUNTER-BATTERY RADAR", "STRUCTURES",
          "models.support_assets", "build_cbr_radar",
          tags=("sensor", "missile warning", "lattice mast")),
    _mesh("decoy_emitter", "DECOY EMITTER", "STRUCTURES",
          "models.support_assets", "build_decoy_emitter",
          tags=("sensor decoy", "emitter", "mast")),
    _mesh("corner_reflector", "CORNER REFLECTOR CLUSTER", "STRUCTURES",
          "models.support_assets", "build_corner_reflector",
          tags=("radar decoy", "passive", "trihedral")),
    _mesh("sam_pad", "S-300 HARDSTAND", "STRUCTURES",
          "models.support_assets", "build_sam_pad",
          tags=("concrete", "launcher pad", "site")),
    _mesh("fuel_depot", "FUEL DEPOT", "STRUCTURES",
          "models.structures", "build_fuel_depot",
          tags=("tank", "site")),
    _mesh("harbor", "HARBOR", "STRUCTURES",
          "models.structures", "build_harbor",
          tags=("port", "quay", "site")),
    _mesh("airfield", "AIRFIELD", "STRUCTURES",
          "models.airfield", "build_airfield",
          tags=("runway", "hangar", "site")),

    # Aircraft (generic fallback silhouettes plus dedicated combat models)
    _mesh("patrol_aircraft", "PATROL AIRCRAFT", "AIRCRAFT",
          "models.aircraft_model", "build_patrol_aircraft",
          tags=("generic", "maritime")),
    _mesh("fast_aircraft", "FAST AIRCRAFT", "AIRCRAFT",
          "models.aircraft_model", "build_fast_aircraft",
          tags=("generic", "jet")),
    _mesh("recon_drone", "RECON DRONE", "AIRCRAFT",
          "models.drone", "build_recon_drone",
          tags=("uav", "reconnaissance")),
    _mesh("fighter", "FIGHTER", "AIRCRAFT",
          "models.fighter", "build_fighter",
          tags=("jet", "interceptor")),
    _mesh("awacs", "AWACS", "AIRCRAFT",
          "models.awacs", "build_awacs",
          tags=("radar", "early warning")),
    _mesh("jammer", "ESCORT JAMMER", "AIRCRAFT",
          "models.jammer", "build_jammer",
          tags=("electronic warfare", "growler")),

    # Ships
    _mesh("cargo", "CARGO SHIP", "SHIPS",
          "models.ships_models", "build_cargo",
          tags=("merchant", "transport")),
    _mesh("tanker", "TANKER", "SHIPS",
          "models.ships_models", "build_tanker",
          tags=("merchant", "oil")),
    _mesh("warship", "WARSHIP", "SHIPS",
          "models.ships_models", "build_warship",
          tags=("generic", "combatant")),
    _mesh("destroyer", "DESTROYER", "SHIPS",
          "models.destroyer", "build_destroyer",
          tags=("combatant", "aegis")),
    _mesh("flagship", "TICONDEROGA FLAGSHIP", "SHIPS",
          "models.flagship", "build_flagship",
          tags=("combatant", "aegis", "command cruiser", "ticonderoga")),
    _mesh("carrier", "AIRCRAFT CARRIER", "SHIPS",
          "models.carrier", "build_carrier",
          tags=("combatant", "flight deck")),
    _mesh("transport", "AMPHIBIOUS TRANSPORT", "SHIPS",
          "models.ships_models", "build_transport",
          tags=("amphibious", "landing", "well deck")),
    _mesh("lcac", "LCAC", "SHIPS",
          "models.ships_models", "build_lcac",
          tags=("landing craft", "air cushion", "amphibious")),
    _mesh("submarine", "PROJECT 636 SUBMARINE", "SHIPS",
          "models.support_assets", "build_submarine",
          tags=("ssk", "diesel electric", "kalibr", "kilo")),

    # Missiles and visible launch variants/debris
    _mesh("oniks", "P-800 ONIKS", "MISSILES",
          "models.oniks", "build_oniks",
          tags=("anti-ship", "ramjet", "missile")),
    _mesh("oniks_capped", "P-800 ONIKS - CAPPED", "MISSILES",
          "models.oniks", "build_oniks", nose_cap=True,
          tags=("anti-ship", "launch variant", "missile")),
    _mesh("oniks_folded", "P-800 ONIKS - FOLDED/CAPPED", "MISSILES",
          "models.oniks", "build_oniks", nose_cap=True, wings_folded=True,
          tags=("anti-ship", "tube variant", "missile")),
    _mesh("oniks_nose_cap", "ONIKS NOSE CAP", "MISSILES",
          "models.oniks", "build_oniks_nose_cap",
          tags=("launch debris", "cap")),
    _mesh("tomahawk", "BGM-109 TOMAHAWK", "MISSILES",
          "models.missiles", "build_tomahawk",
          tags=("cruise missile", "land attack")),
    _mesh("jassm", "AGM-158 JASSM", "MISSILES",
          "models.missiles", "build_jassm",
          tags=("cruise missile", "stealth")),
    _mesh("harm", "AGM-88 HARM", "MISSILES",
          "models.missiles", "build_harm",
          tags=("anti-radiation", "arm")),
    _mesh("kh31p", "KH-31P", "MISSILES",
          "models.missiles", "build_kh31p",
          tags=("anti-radiation", "arm")),
    _mesh("aim9x", "AIM-9X", "MISSILES",
          "models.missiles", "build_aim9x",
          tags=("air-to-air", "ir")),
    _mesh("s300_missile_legacy", "S-300 MISSILE - LEGACY", "MISSILES",
          "models.s300", "build_s300_missile",
          tags=("sam", "legacy")),
    _mesh("48n6", "48N6", "MISSILES",
          "models.missiles", "build_48n6",
          tags=("s-300", "sam")),
    _mesh("40n6", "40N6", "MISSILES",
          "models.missiles", "build_40n6",
          tags=("s-300", "sam", "long range")),
    _mesh("sm2", "SM-2", "MISSILES",
          "models.missiles", "build_sm2",
          tags=("naval", "sam")),
    _mesh("sm6", "SM-6", "MISSILES",
          "models.missiles", "build_sm6",
          tags=("naval", "sam")),
    _mesh("57e6", "57E6", "MISSILES",
          "models.missiles", "build_57e6",
          tags=("pantsir", "sam", "bicalibre")),
    _mesh("zircon", "3M22 ZIRCON", "MISSILES",
          "models.missiles", "build_zircon",
          tags=("anti-ship", "hypersonic", "missile")),
    _mesh("kalibr", "3M14 KALIBR (PROXY)", "MISSILES",
          "models.missiles", "build_tomahawk", proxy_for="tomahawk",
          tags=("proxy for tomahawk", "cruise missile", "land attack")),
    _mesh("buk_9m317", "BUK 9M317 (PROXY)", "MISSILES",
          "models.missiles", "build_48n6", proxy_for="48n6",
          tags=("proxy for 48n6", "buk", "sam")),
    _mesh("buk_9m338", "BUK 9M338 (PROXY)", "MISSILES",
          "models.missiles", "build_57e6", proxy_for="57e6",
          tags=("proxy for 57e6", "buk", "sam")),
    _mesh("asbm", "ANTI-SHIP BALLISTIC MISSILE (PROXY)", "MISSILES",
          "models.missiles", "build_40n6", proxy_for="40n6",
          tags=("proxy for 40n6", "asbm", "ballistic", "anti-ship")),
    _mesh("swarm_loiterer", "SWARM LOITERER (PROXY)", "MISSILES",
          "models.missiles", "build_aim9x", proxy_for="aim9x",
          tags=("proxy for aim9x", "loitering munition", "swarm")),

    # The seven authoritative V2 weather recipes (sim.atmosphere).
    _weather("clear", "CLEAR", 0, "sky"),
    _weather("fair", "FAIR", 1, "cumulus", "sky"),
    _weather("partly_cloudy", "PARTLY CLOUDY", 2, "cumulus", "sky"),
    _weather("overcast", "OVERCAST", 3, "stratus", "sky"),
    _weather("high_cirrus", "HIGH CIRRUS", 4, "cirrus", "sky"),
    _weather("towering_cumulus", "TOWERING CUMULUS", 5,
             "convective", "sky"),
    _weather("thunderstorm", "THUNDERSTORM", 6,
             "supercell", "lightning", "rain", "sky"),

    # Particle effects (the EFFECTS tab: every effect gets a front-row
    # inspection seat — game/effects_catalog.py drives the loops).
    _effect("fx_muzzle_blast", "MUZZLE BLAST", "pantsir", "launch"),
    _effect("fx_ignition_fireball", "IGNITION FIREBALL", "sam", "launch"),
    _effect("fx_explosion_ground", "EXPLOSION - GROUND", "impact"),
    _effect("fx_explosion_water", "EXPLOSION - WATER", "impact", "sea"),
    _effect("fx_splash", "SPLASH", "sea"),
    _effect("fx_magazine_detonation", "MAGAZINE DETONATION",
            "damage", "impact", "sea"),
    _effect("fx_rideout_plume", "RIDE-OUT PLUME", "sam", "smoke"),
    _effect("fx_boost_plume", "BOOST PLUME", "sam", "smoke"),
    _effect("fx_ship_fire", "SHIP FIRE", "damage", "smoke"),
    _effect("fx_cold_eject", "COLD EJECT - 48N6", "cinematic", "s-300"),
    _effect("fx_pad_blast_48n6", "PAD BLAST - 48N6", "cinematic", "s-300"),
    _effect("fx_pad_blast_40n6", "PAD BLAST - 40N6", "cinematic", "s-400"),
    _effect("fx_pad_blast_9m96", "PAD BLAST - 9M96", "cinematic"),
    _effect("fx_launch_48n6", "FULL LAUNCH - 48N6", "cinematic", "s-300"),
    _effect("fx_launch_5v55", "FULL LAUNCH - 5V55", "cinematic", "s-300"),
    _effect("fx_launch_9m96", "FULL LAUNCH - 9M96E2", "cinematic"),
    _effect("fx_launch_40n6", "FULL LAUNCH - 40N6", "cinematic", "s-400"),
)


def _catalog_index() -> dict[str, TestAsset]:
    index: dict[str, TestAsset] = {}
    for asset in TEST_ASSETS:
        if asset.id in index:
            raise RuntimeError(f"duplicate testing asset id {asset.id!r}")
        index[asset.id] = asset
    for asset in TEST_ASSETS:
        if asset.proxy_for is not None and asset.proxy_for not in index:
            raise RuntimeError(
                f"testing asset {asset.id!r} has unknown proxy target "
                f"{asset.proxy_for!r}")
    return index


_ASSET_BY_ID = _catalog_index()


def get_asset(asset_id: str) -> TestAsset:
    """Return one entry by stable id (case-insensitive, outer space ignored)."""

    if not isinstance(asset_id, str):
        raise TypeError("asset_id must be a string")
    key = asset_id.strip().casefold()
    if not key:
        raise ValueError("asset_id cannot be empty")
    try:
        return _ASSET_BY_ID[key]
    except KeyError:
        raise KeyError(f"unknown testing asset {asset_id!r}") from None


def _search_text(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").replace("-", " ").split())


def filter_assets(category: str = "ALL", query: str = "") -> tuple[TestAsset, ...]:
    """Filter by category and an AND-token search over labels, ids and tags."""

    if not isinstance(category, str):
        raise TypeError("category must be a string")
    selected = category.strip().upper()
    if selected not in CATEGORIES:
        raise ValueError(f"unknown testing category {category!r}")
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    tokens = tuple(_search_text(query).split())
    result: list[TestAsset] = []
    for asset in TEST_ASSETS:
        if selected != "ALL" and asset.category != selected:
            continue
        haystack = _search_text(" ".join(
            (asset.id, asset.label, asset.category, asset.kind,
             asset.proxy_for or "", *asset.tags)))
        if all(token in haystack for token in tokens):
            result.append(asset)
    return tuple(result)


def mesh_metadata(meshdata) -> dict[str, object]:
    """Return validated, JSON-friendly geometry and bounding-box metadata."""

    if not hasattr(meshdata, "vertices") or not hasattr(meshdata, "indices"):
        raise TypeError("expected MeshData-like object with vertices and indices")
    vertices = np.asarray(meshdata.vertices)
    indices = np.asarray(meshdata.indices)
    if vertices.ndim != 2 or vertices.shape[1] < 3:
        raise ValueError("mesh vertices must have shape (N, >=3)")
    if len(vertices) == 0:
        raise ValueError("mesh has no vertices")
    if indices.ndim != 1 or len(indices) == 0 or len(indices) % 3:
        raise ValueError("mesh indices must be a non-empty triangle list")
    if not np.issubdtype(indices.dtype, np.integer):
        raise TypeError("mesh indices must be integers")
    positions = np.asarray(vertices[:, :3], dtype=np.float64)
    if not np.isfinite(positions).all():
        raise ValueError("mesh positions must be finite")
    if int(indices.min()) < 0 or int(indices.max()) >= len(vertices):
        raise ValueError("mesh index is outside the vertex array")

    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    center = (lo + hi) * 0.5
    dimensions = hi - lo
    radius = float(np.linalg.norm(positions - center, axis=1).max())
    return {
        "bbox_min": tuple(float(v) for v in lo),
        "bbox_max": tuple(float(v) for v in hi),
        "dimensions": tuple(float(v) for v in dimensions),
        "center": tuple(float(v) for v in center),
        "radius": radius,
        "vertices": int(len(vertices)),
        "triangles": int(len(indices) // 3),
    }


def load_mesh_data(asset: TestAsset | str):
    """Lazily call a mesh builder and verify that it returned usable data."""

    if isinstance(asset, str):
        asset = get_asset(asset)
    if not isinstance(asset, TestAsset):
        raise TypeError("asset must be a TestAsset or stable asset id")
    if asset.kind != "mesh":
        raise TypeError(f"{asset.id!r} is {asset.kind}, not a mesh asset")
    module = importlib.import_module(asset.module)
    try:
        builder = getattr(module, asset.builder)
    except AttributeError:
        raise LookupError(f"missing builder {asset.builder_ref}") from None
    if not callable(builder):
        raise TypeError(f"builder {asset.builder_ref} is not callable")
    meshdata = builder(**asset.kwargs)
    mesh_metadata(meshdata)  # validate once at the catalog boundary
    return meshdata


def _clean_text(value: Any, field: str, *, limit: int,
                multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    allowed_breaks = "\n\t" if multiline else ""
    cleaned = "".join(
        ch for ch in value
        if (ord(ch) >= 32 and ord(ch) != 127) or ch in allowed_breaks
    ).strip()
    if len(cleaned) > limit:
        raise ValueError(f"{field} is longer than {limit} characters")
    return cleaned


def _json_safe(value: Any, field: str, *, depth: int = 0):
    """Convert common camera/metadata values to bounded strict JSON data."""

    if depth > 8:
        raise ValueError(f"{field} is nested too deeply")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, str):
        return _clean_text(value, field, limit=8_000, multiline=True)
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, Mapping):
        if len(value) > 256:
            raise ValueError(f"{field} has too many keys")
        result = {}
        for key, item in value.items():
            clean_key = _clean_text(str(key), field, limit=80)
            if not clean_key:
                raise ValueError(f"{field} contains an empty key")
            result[clean_key] = _json_safe(item, field, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 1_024:
            raise ValueError(f"{field} contains too many values")
        return [_json_safe(item, field, depth=depth + 1) for item in value]
    raise TypeError(f"{field} contains unsupported value {type(value).__name__}")


def _feedback_asset(value: Any) -> TestAsset:
    if isinstance(value, TestAsset):
        return value
    if isinstance(value, Mapping):
        value = value.get("id")
    if not isinstance(value, str):
        raise TypeError("context.asset must be a TestAsset, id string, or id mapping")
    return get_asset(value)


def _safe_screenshot_name(value: Any) -> str:
    raw = _clean_text(value, "screenshot_name", limit=240)
    # Treat both path separators as hostile regardless of host platform.
    leaf = re.split(r"[\\/]", raw)[-1]
    leaf = re.sub(r"[^A-Za-z0-9._-]+", "_", leaf).lstrip(".")
    if not leaf or leaf in (".", ".."):
        raise ValueError("screenshot_name must contain a safe file name")
    return leaf[:120]


def _safe_seed(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("seed must be an integer")
    try:
        seed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise TypeError("seed must be an integer") from None
    if seed < 0 or seed > (2 ** 63 - 1):
        raise ValueError("seed is outside the supported non-negative range")
    return seed


def _safe_mesh_stats(value: Any) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("mesh_stats must be a mapping")
    data = _json_safe(value, "mesh_stats")
    required = {"bbox_min", "bbox_max", "dimensions", "center",
                "radius", "vertices", "triangles"}
    if not required.issubset(data):
        missing = ", ".join(sorted(required - set(data)))
        raise ValueError(f"mesh_stats is missing: {missing}")

    vectors: dict[str, list[float]] = {}
    for key in ("bbox_min", "bbox_max", "dimensions", "center"):
        raw = data[key]
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError(f"mesh_stats.{key} must contain three numbers")
        vector = []
        for component in raw:
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                raise TypeError(f"mesh_stats.{key} must contain numbers")
            number = float(component)
            if not math.isfinite(number):
                raise ValueError(f"mesh_stats.{key} must be finite")
            vector.append(number)
        vectors[key] = vector
    if any(value < 0.0 for value in vectors["dimensions"]):
        raise ValueError("mesh_stats.dimensions cannot be negative")
    if any(hi < lo for lo, hi in zip(vectors["bbox_min"],
                                     vectors["bbox_max"])):
        raise ValueError("mesh_stats bbox maximum is below its minimum")

    radius = data["radius"]
    if isinstance(radius, bool) or not isinstance(radius, (int, float)):
        raise TypeError("mesh_stats.radius must be a number")
    radius = float(radius)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError("mesh_stats.radius must be finite and non-negative")

    counts: dict[str, int] = {}
    for key in ("vertices", "triangles"):
        raw = data[key]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise TypeError(f"mesh_stats.{key} must be an integer")
        if raw <= 0:
            raise ValueError(f"mesh_stats.{key} must be positive")
        counts[key] = int(raw)
    return {**vectors, "radius": radius, **counts}


def _validate_claim(context: Mapping, key: str, expected: str) -> None:
    if key not in context:
        return
    actual = _clean_text(context[key], key, limit=80).casefold()
    if actual != expected.casefold():
        raise ValueError(
            f"context {key}={context[key]!r} does not match asset {expected!r}")


def _feedback_markdown(payload: Mapping[str, Any]) -> str:
    stats = payload["mesh_stats"]
    lines = [
        "# Testing feedback",
        "",
        f"- Asset: {payload['asset_label']} (`{payload['asset']}`)",
        f"- Kind: {payload['kind']}",
        f"- Category: {payload['category']}",
        f"- Type: {payload['type']}",
    ]
    if payload["kind"] == "weather":
        lines.append(f"- Seed: {payload['seed']}")
    lines.append(f"- Screenshot: `{payload['screenshot_name']}`")
    if payload.get("proxy_for"):
        lines.append(f"- Proxy geometry: `{payload['proxy_for']}`")
    if "timestamp" in payload:
        lines.append(f"- Timestamp: {payload['timestamp']}")
    if "commit" in payload:
        lines.append(f"- Commit: `{payload['commit']}`")
    if stats is not None:
        dims = " x ".join(f"{float(v):.3f}" for v in stats["dimensions"])
        lines.extend((
            f"- Mesh: {stats['vertices']} vertices / {stats['triangles']} triangles",
            f"- Bounds: {dims} m; radius {float(stats['radius']):.3f} m",
        ))
    lines.extend((
        "",
        "## Camera",
        "",
        "```json",
        json.dumps(payload["camera"], indent=2, sort_keys=True,
                   ensure_ascii=False, allow_nan=False),
        "```",
        "",
        "## Feedback",
        "",
        payload["note"] or "(No note supplied.)",
        "",
    ))
    return "\n".join(lines)


def write_testing_feedback(base_dir: str | os.PathLike,
                           context: Mapping[str, Any]) -> str:
    """Write ``feedback_NNN/{feedback.md,context.json}`` and return the report.

    Battle-ledger fields are deliberately absent.  Identity is derived from
    the immutable catalog entry, while caller-supplied camera/settings data is
    converted to strict JSON and notes/file names are bounded and sanitized.
    Directory creation is atomic, so concurrent testers cannot claim the same
    number.
    """

    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    if isinstance(base_dir, (str, os.PathLike)):
        raw_base = os.fspath(base_dir)
    else:
        raise TypeError("base_dir must be path-like")
    if not raw_base or (isinstance(raw_base, str) and not raw_base.strip()):
        raise ValueError("base_dir cannot be empty")

    asset = _feedback_asset(context.get("asset"))
    _validate_claim(context, "kind", asset.kind)
    _validate_claim(context, "category", asset.category)

    camera = context.get("camera", {})
    if not isinstance(camera, Mapping):
        raise TypeError("camera must be a mapping")
    camera_json = _json_safe(camera, "camera")

    supplied_stats = context.get("mesh_stats")
    if supplied_stats is None and asset.kind == "mesh":
        stats: object = _safe_mesh_stats(mesh_metadata(load_mesh_data(asset)))
    elif supplied_stats is None:
        stats = None
    else:
        if asset.kind != "mesh":
            raise ValueError("weather feedback cannot claim mesh stats")
        stats = _safe_mesh_stats(supplied_stats)

    feedback_type = _clean_text(
        context.get("type", "feedback"), "type", limit=48).casefold()
    feedback_type = re.sub(r"[^a-z0-9_-]+", "_", feedback_type).strip("_")
    if not feedback_type:
        raise ValueError("type must contain a letter or number")

    payload: dict[str, Any] = {
        "schema_version": 1,
        "asset": asset.id,
        "asset_label": asset.label,
        "kind": asset.kind,
        "category": asset.category,
        "proxy_for": asset.proxy_for,
        "seed": _safe_seed(context.get("seed", 0)),
        "camera": camera_json,
        "mesh_stats": stats,
        "note": _clean_text(context.get("note", ""), "note",
                            limit=8_000, multiline=True),
        "type": feedback_type,
        "screenshot_name": _safe_screenshot_name(
            context.get("screenshot_name",
                        context.get("screenshot", "screenshot.png"))),
    }
    for optional in ("timestamp", "commit"):
        if optional in context and context[optional] is not None:
            value = _clean_text(context[optional], optional, limit=160)
            if value:
                payload[optional] = value
    if "details" in context:
        if not isinstance(context["details"], Mapping):
            raise TypeError("details must be a mapping")
        payload["details"] = _json_safe(context["details"], "details")

    base = Path(raw_base).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        folder = base / f"feedback_{number:03d}"
        try:
            folder.mkdir()
            break
        except FileExistsError:
            number += 1

    report_path = folder / "feedback.md"
    context_path = folder / "context.json"
    context_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False,
                   allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_feedback_markdown(payload), encoding="utf-8")
    return str(report_path)


__all__ = (
    "CATEGORIES",
    "TEST_ASSETS",
    "TestAsset",
    "filter_assets",
    "get_asset",
    "load_mesh_data",
    "mesh_metadata",
    "write_testing_feedback",
)
