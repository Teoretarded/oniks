"""Deterministic, visual-only weather presentation.

The controller is GL-free and advances on render time.  It turns the selected
weather preset into camera-local darkness/rain plus a seeded lightning and
delayed-thunder schedule.  It never mutates the world or participates in
sensor/weapon physics.

``WeatherOverlayRenderer`` is a small deferred-GL fullscreen pass.  It tints
the scene beneath heavy cloud, draws procedural screen-space rain, and flashes
lightning after clouds/particles but before the HUD.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from sim.atmosphere import (CLOUD_STREAM_TAG, CONVECTIVE_DOMAIN_M,
                            WEATHER_PRESETS, Supercell, build_supercells,
                            weather_preset, weather_recipe_key)


WEATHER_FX_COMPONENT = 91
SPEED_OF_SOUND_MS = 343.0
FLASH_LIFETIME_S = 0.42
THUNDER_MAX_DELAY_S = 12.0
THUNDER_AUDIBLE_M = 75_000.0


@dataclass(frozen=True)
class PresentationTuning:
    base_darkness: float
    local_darkness: float
    rain_scale: float = 0.0
    lightning_min_s: float = 0.0
    lightning_max_s: float = 0.0


# Indexed by the seven atmosphere presets. FAIR stays an exact no-op.
PRESENTATION_TUNING: tuple[PresentationTuning, ...] = (
    PresentationTuning(0.00, 0.00),              # clear
    PresentationTuning(0.00, 0.00),              # fair
    PresentationTuning(0.015, 0.060),            # partly cloudy
    PresentationTuning(0.120, 0.160),            # overcast
    PresentationTuning(0.025, 0.000),            # high cirrus
    PresentationTuning(0.045, 0.190),            # towering cumulus
    PresentationTuning(0.100, 0.520, 1.0, 4.5, 11.0),  # thunderstorm
)
assert len(PRESENTATION_TUNING) == len(WEATHER_PRESETS)


def presentation_tuning(preset) -> PresentationTuning:
    spec = weather_preset(preset)
    if (0 <= spec.preset_id < len(WEATHER_PRESETS)
            and spec == WEATHER_PRESETS[spec.preset_id]):
        return PRESENTATION_TUNING[spec.preset_id]
    coverage = max(
        (layer.coverage for layer in (spec.lower, spec.upper)
         if layer.enabled), default=0.0)
    base_darkness = max(0.0, (coverage - 0.42) * 0.22)
    return PresentationTuning(
        base_darkness=base_darkness,
        local_darkness=0.52 if spec.storm > 0.0 else 0.08,
        rain_scale=1.0 if spec.precip_mmh > 0.0 else 0.0,
        lightning_min_s=4.5 if spec.storm > 0.0 else 0.0,
        lightning_max_s=11.0 if spec.storm > 0.0 else 0.0,
    )


@dataclass(frozen=True)
class WeatherFrame:
    darkness: float
    rain: float
    lightning: float
    local_storm: float


@dataclass(frozen=True)
class ThunderCue:
    due_time: float
    gain: float
    position: tuple[float, float, float]


@dataclass(frozen=True)
class WeatherUpdate:
    frame: WeatherFrame
    thunder: tuple[ThunderCue, ...]


@dataclass(frozen=True)
class _Flash:
    time: float
    position: tuple[float, float, float]


@dataclass(frozen=True)
class _PendingThunder:
    due_time: float
    gain: float
    position: tuple[float, float, float]


def _smoothstep(lo: float, hi: float, value: float) -> float:
    if hi <= lo:
        return float(value >= hi)
    u = min(1.0, max(0.0, (float(value) - lo) / (hi - lo)))
    return u * u * (3.0 - 2.0 * u)


def lightning_pulse(age_s: float) -> float:
    """Two short deterministic optical pulses for one lightning event."""

    age = float(age_s)
    if age < 0.0 or age >= FLASH_LIFETIME_S:
        return 0.0
    first = max(0.0, 1.0 - age / 0.105)
    second_age = age - 0.155
    second = (0.58 * max(0.0, 1.0 - second_age / 0.13)
              if second_age >= 0.0 else 0.0)
    return max(first, second)


class WeatherEffectsController:
    """Seeded render-time weather state with no GL or simulation mutations."""

    def __init__(self, seed: int, preset=1):
        self.seed = 0
        self.preset_id = -1
        self.recipe_key = ""
        self.time = 0.0
        self.preset = WEATHER_PRESETS[1]
        self.tuning = PRESENTATION_TUNING[1]
        self.storm_cells: tuple[Supercell, ...] = ()
        self._rng = None
        self._next_lightning = math.inf
        self._flashes: list[_Flash] = []
        self._pending: list[_PendingThunder] = []
        self.configure(seed, preset, force=True)

    @property
    def overlay_seed(self) -> float:
        """Small exactly representable seed sent to the rain shader."""

        return float((self.seed ^ (self.preset_id * 8191)) & 0xFFFF)

    def configure(self, seed: int, preset, force: bool = False) -> bool:
        """Reset only when the selected battle seed/preset actually changes."""

        spec = weather_preset(preset)
        recipe_key = weather_recipe_key(spec)
        seed = int(seed)
        if not force and seed == self.seed and recipe_key == self.recipe_key:
            return False
        self.seed = seed
        self.preset_id = spec.preset_id
        self.recipe_key = recipe_key
        self.preset = spec
        self.tuning = presentation_tuning(spec)
        self.time = 0.0
        # SeedSequence rejects negative integers even though CombatConfig's
        # programmatic contract accepts any int. Fold to a stable unsigned
        # visual seed without changing the user-visible/configured value.
        stream_seed = seed & 0xFFFFFFFF
        self.storm_cells = build_supercells(stream_seed, spec)
        self._rng = np.random.default_rng(
            [stream_seed, CLOUD_STREAM_TAG, WEATHER_FX_COMPONENT,
             spec.preset_id])
        self._flashes = []
        self._pending = []
        if (spec.storm > 0.0 and self.storm_cells
                and self.tuning.lightning_max_s > 0.0):
            # First activity arrives soon enough to establish the preset, while
            # subsequent intervals retain natural variation.
            self._next_lightning = float(self._rng.uniform(1.2, 4.0))
        else:
            self._next_lightning = math.inf
        return True

    def _local_storm(self, camera_pos) -> float:
        if not self.storm_cells:
            layers = [x.coverage for x in (self.preset.lower,
                                           self.preset.upper) if x.enabled]
            layers.extend((self.preset.high.cirrus_coverage,
                           self.preset.high.strata_coverage))
            return max(layers, default=0.0)

        p = np.asarray(camera_pos, dtype=np.float64)
        wx, wz = self.preset.wind_ms
        # Cloud shaders sample (world + wind*time), so evaluate the same moving
        # periodic material coordinate here.
        x = (float(p[0]) + wx * self.time) % CONVECTIVE_DOMAIN_M
        z = (float(p[2]) + wz * self.time) % CONVECTIVE_DOMAIN_M
        best = 0.0
        for cell in self.storm_cells:
            cx = cell.x * CONVECTIVE_DOMAIN_M
            cz = cell.z * CONVECTIVE_DOMAIN_M
            dx = abs(x - cx)
            dz = abs(z - cz)
            dx = min(dx, CONVECTIVE_DOMAIN_M - dx)
            dz = min(dz, CONVECTIVE_DOMAIN_M - dz)
            dist = math.hypot(dx, dz)
            radius = cell.core_radius_m
            edge = 1.0 - _smoothstep(radius * 0.55,
                                     radius * 1.45, dist)
            best = max(best, edge * cell.intensity)
        return min(1.0, best)

    def _cloud_top(self) -> float:
        tops = [layer.top_m for layer in (self.preset.lower,
                                          self.preset.upper) if layer.enabled]
        if max(self.preset.high.cirrus_coverage,
               self.preset.high.strata_coverage) > 0.0:
            tops.append(self.preset.high.altitude_m + 720.0)
        if self.storm_cells:
            tops.extend(cell.top_m + cell.overshoot_m
                        for cell in self.storm_cells)
        return max(tops, default=0.0)

    def _rain_ceiling(self) -> float:
        if self.preset.lower.enabled:
            return self.preset.lower.top_m
        if self.preset.upper.enabled:
            return self.preset.upper.base_m
        return 0.0

    def _nearest_periodic(self, value: float, target: float) -> float:
        return value + round((target - value) / CONVECTIVE_DOMAIN_M) \
            * CONVECTIVE_DOMAIN_M

    def _make_strike(self, strike_time: float, camera_pos) -> _Flash:
        cell = self.storm_cells[int(self._rng.integers(len(self.storm_cells)))]
        angle = float(self._rng.uniform(0.0, 2.0 * math.pi))
        radius = float(self._rng.uniform(0.0, cell.core_radius_m * 0.42))
        wx, wz = self.preset.wind_ms
        x = cell.x * CONVECTIVE_DOMAIN_M - wx * strike_time \
            + math.sin(angle) * radius
        z = cell.z * CONVECTIVE_DOMAIN_M - wz * strike_time \
            + math.cos(angle) * radius
        camera = np.asarray(camera_pos, dtype=np.float64)
        x = self._nearest_periodic(x, float(camera[0]))
        z = self._nearest_periodic(z, float(camera[2]))
        y = cell.top_m - 0.08 * (cell.top_m - cell.base_m)
        return _Flash(float(strike_time), (float(x), float(y), float(z)))

    def _queue_thunder(self, flash: _Flash, camera_pos) -> None:
        camera = np.asarray(camera_pos, dtype=np.float64)
        strike = np.asarray(flash.position, dtype=np.float64)
        distance = float(np.linalg.norm(strike - camera))
        delay = min(THUNDER_MAX_DELAY_S,
                    max(0.15, distance / SPEED_OF_SOUND_MS))
        audible = max(0.0, 1.0 - distance / THUNDER_AUDIBLE_M)
        gain = 0.82 * audible ** 1.25
        self._pending.append(_PendingThunder(
            flash.time + delay, gain, flash.position))

    def advance(self, dt_real: float, camera_pos) -> WeatherUpdate:
        """Advance the visual clock and return newly due thunder cues."""

        dt = float(dt_real)
        if not math.isfinite(dt) or dt < 0.0:
            dt = 0.0
        end = self.time + dt
        while self._next_lightning <= end:
            strike_time = self._next_lightning
            flash = self._make_strike(strike_time, camera_pos)
            self._flashes.append(flash)
            self._queue_thunder(flash, camera_pos)
            self._next_lightning = strike_time + float(self._rng.uniform(
                self.tuning.lightning_min_s, self.tuning.lightning_max_s))
        self.time = end

        due = []
        remaining = []
        for item in self._pending:
            if item.due_time <= end:
                due.append(ThunderCue(item.due_time, item.gain, item.position))
            else:
                remaining.append(item)
        self._pending = remaining
        self._flashes = [f for f in self._flashes
                         if end - f.time < FLASH_LIFETIME_S]
        return WeatherUpdate(self.sample(camera_pos), tuple(due))

    def sample(self, camera_pos) -> WeatherFrame:
        """Presentation values at the current clock for this camera."""

        camera = np.asarray(camera_pos, dtype=np.float64)
        local = self._local_storm(camera)
        top = self._cloud_top()
        under_cloud = (1.0 - _smoothstep(top, top + 3_000.0, camera[1])
                       if top > 0.0 else 0.0)
        darkness = (self.tuning.base_darkness
                    + self.tuning.local_darkness * local) * under_cloud

        rain_top = self._rain_ceiling()
        below_rain = (1.0 - _smoothstep(rain_top, rain_top + 2_500.0,
                                        camera[1]) if rain_top > 0.0 else 0.0)
        rain = (min(1.0, self.preset.precip_mmh / 25.0)
                * self.tuning.rain_scale * local * below_rain)

        flash_strength = 0.0
        for flash in self._flashes:
            pulse = lightning_pulse(self.time - flash.time)
            if pulse <= 0.0:
                continue
            strike = np.asarray(flash.position, dtype=np.float64)
            distance = float(np.linalg.norm(strike - camera))
            visibility = 0.25 + 0.75 / (1.0 + distance / 80_000.0)
            flash_strength = max(flash_strength, pulse * visibility)
        return WeatherFrame(
            darkness=min(0.72, max(0.0, darkness)),
            rain=min(1.0, max(0.0, rain)),
            lightning=min(1.0, max(0.0, flash_strength)),
            local_storm=min(1.0, max(0.0, local)),
        )


WEATHER_OVERLAY_VERT = """
#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_ndc;
void main(){
    v_ndc = a_pos;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

WEATHER_OVERLAY_FRAG = """
#version 330 core
in vec2 v_ndc;
uniform float u_darkness;
uniform float u_rain;
uniform float u_lightning;
uniform float u_time;
uniform float u_seed;
out vec4 frag;

float hash11(float p){
    return fract(sin(p * 127.1 + u_seed * 0.013) * 43758.5453123);
}

float rain_layer(vec2 px, float lane_width, float speed, float salt){
    float slanted = px.x + px.y * 0.115;
    float lane = floor(slanted / lane_width);
    float across = abs(fract(slanted / lane_width) - 0.5);
    float period = 125.0 + hash11(lane + salt) * 105.0;
    float along = fract((px.y + u_time * speed
                         + hash11(lane * 3.17 + salt) * period) / period);
    float segment = smoothstep(0.015, 0.055, along)
                    * (1.0 - smoothstep(0.20, 0.34, along));
    float width = 1.0 - smoothstep(0.035, 0.12, across);
    float sparse = step(0.28, hash11(lane * 11.73 + salt));
    return segment * width * sparse;
}

void main(){
    if (u_darkness <= 0.0001 && u_rain <= 0.0001
        && u_lightning <= 0.0001) discard;
    vec2 px = gl_FragCoord.xy;
    float streak = max(rain_layer(px, 8.0, 870.0, 17.0),
                       rain_layer(px + vec2(31.0, 0.0), 13.0, 690.0, 53.0));
    streak *= u_rain;

    vec3 color = vec3(0.025, 0.050, 0.074);
    float alpha = u_darkness * 0.78;
    float rain_alpha = streak * (0.28 + 0.32 * u_rain);
    color = mix(color, vec3(0.68, 0.76, 0.84), rain_alpha);
    alpha = max(alpha, rain_alpha);

    // Lightning should read as a deliberate, brief exposure spike even when
    // the selected seeded strike is tens of kilometres from the camera.
    float flash_alpha = u_lightning * 0.82;
    color = mix(color, vec3(0.86, 0.92, 1.0), flash_alpha);
    alpha = max(alpha, flash_alpha);
    frag = vec4(color, min(alpha, 0.88));
}
"""


class WeatherOverlayRenderer:
    """One cheap fullscreen presentation pass; all GL imports are deferred."""

    def __init__(self):
        import OpenGL.GL as gl
        from engine.shader import Shader

        self._gl = gl
        self.shader = Shader(WEATHER_OVERLAY_VERT, WEATHER_OVERLAY_FRAG)
        self._vao = int(gl.glGenVertexArrays(1))
        self._vbo = int(gl.glGenBuffers(1))
        gl.glBindVertexArray(self._vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo)
        tri = np.asarray([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0],
                         dtype=np.float32)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, tri.nbytes, tri, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 8, None)
        gl.glBindVertexArray(0)

    def draw(self, frame: WeatherFrame, visual_time: float,
             overlay_seed: float) -> None:
        if (frame.darkness <= 0.0001 and frame.rain <= 0.0001
                and frame.lightning <= 0.0001):
            return
        gl = self._gl
        sh = self.shader
        sh.use()
        sh.set_float("u_darkness", frame.darkness)
        sh.set_float("u_rain", frame.rain)
        sh.set_float("u_lightning", frame.lightning)
        sh.set_float("u_time", float(visual_time))
        sh.set_float("u_seed", float(overlay_seed))
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glEnable(gl.GL_DEPTH_TEST)

    def delete(self) -> None:
        gl = self._gl
        if self._vao:
            gl.glDeleteVertexArrays(1, [self._vao])
            gl.glDeleteBuffers(1, [self._vbo])
            self._vao = self._vbo = 0
