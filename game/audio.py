"""Procedural sound synthesis + the runtime audio manager (Task 21).

Synthesis is pure numpy and deterministic (fixed seeds): each recipe renders
a float64 waveform in [-1, 1] at 44.1 kHz. ``ensure_sound_files`` writes any
missing ``sounds/*.wav`` once at first run and just returns the paths after
that, so startup stays fast — the cached files load straight into
``pygame.mixer.Sound``.

``AudioManager`` is the runtime side:

- distance attenuation from the CAMERA position
  (``gain = clip(1 - dist / 12 km, 0, 1) ** 1.4`` — a boom 600 km away is
  exactly silent, which is correct at this world scale);
- per-missile booster / cruise loops on reserved channels with channel
  reuse (the same channel switches booster -> cruise at separation);
- near/far explosion pick, tiny 2 kHz UI blips for the map and menu.

The mixer is optional: if it cannot initialize (no audio device) or the
caller asks for ``enabled=False`` (hidden-window batch tools), every method
is a silent no-op. GL-free and mixer-free at import — unit tests import the
synthesis functions headless (LOCKED test convention).
"""

from __future__ import annotations

import os
import wave

import numpy as np
import pygame

SAMPLE_RATE = 44_100
SOUND_DIR = "sounds"

# Mixer settings (plan-fixed): 44.1 kHz, signed 16-bit, stereo, 512 buffer.
MIXER_FREQ, MIXER_SIZE, MIXER_CHANNELS, MIXER_BUFFER = 44_100, -16, 2, 512
NUM_CHANNELS = 24              # total mixer channels (one-shots + loops)
LOOP_CHANNELS = 8              # reserved up front for per-missile loops

# Distance attenuation from the camera eye (plan-fixed shape).
ATTEN_RANGE_M = 12_000.0       # gain reaches zero at this distance
ATTEN_POW = 1.4

BOOM_NEAR_M = 2_500.0          # impacts closer than this play boom_near
UI_GAIN = 0.5                  # UI blip loudness (no distance attenuation)
MIN_GAIN = 0.003               # one-shots quieter than this are skipped

# --- Synthesis recipe constants (per sound, plan-fixed where noted) -----------

PEAK_NORM = 0.95               # |peak| for normalized one-shots

LOOP_FADE_S = 0.2              # loop tail -> head crossfade (plan-fixed)
LOOP_SOUNDS = ("booster", "cruise")

LAUNCH_DUR_S = 1.2             # plan-fixed gas-eject thump length
LAUNCH_NOISE_FC_HZ = 300.0     # plan-fixed one-pole lowpass on brown noise
LAUNCH_NOISE_DECAY = 4.0       # plan-fixed exp(-t * 4)
LAUNCH_THUMP_HZ = 55.0         # plan-fixed sine
LAUNCH_THUMP_DECAY = 6.0       # plan-fixed exp(-t * 6)
LAUNCH_THUMP_MIX = 0.9         # sine level relative to the noise bed

BOOSTER_DUR_S = 2.5            # plan-fixed loop length
BOOSTER_FC_HZ = 220.0          # plan-fixed lowpass
BOOSTER_WOBBLE_HZ = 8.0        # plan-fixed amplitude wobble rate
BOOSTER_WOBBLE_DEPTH = 0.15    # "slight" wobble depth

CRUISE_DUR_S = 2.0             # plan-fixed loop length
CRUISE_FC_HZ = 900.0           # plan-fixed lowpass
CRUISE_WHITE_MIX = 0.5         # white added to brown -> "pink-ish" spectrum
CRUISE_PEAK = 0.4              # low gain baked in (heard only in chase cam)

BOOM_FAR_DUR_S = 3.0           # plan-fixed
BOOM_FAR_SINE_HZ = 40.0        # plan-fixed
BOOM_FAR_SINE_DECAY = 1.2      # plan-fixed exp(-t * 1.2)
BOOM_FAR_NOISE_FC_HZ = 150.0   # plan-fixed noise burst lowpass
BOOM_FAR_NOISE_DECAY = 2.2     # burst dies faster than the sine rumble
BOOM_FAR_NOISE_MIX = 0.7       # burst level relative to the sine

BOOM_NEAR_DUR_S = 1.8          # plan-fixed: shorter ...
BOOM_NEAR_SINE_HZ = 40.0
BOOM_NEAR_SINE_DECAY = 2.6
BOOM_NEAR_NOISE_FC_HZ = 800.0  # plan-fixed: ... and sharper (fc 800)
BOOM_NEAR_NOISE_DECAY = 3.5
BOOM_NEAR_NOISE_MIX = 1.1      # crack sits above the rumble up close

SPLASH_DUR_S = 1.0             # plan-fixed
SPLASH_BAND_LO_HZ = 700.0      # bandpass edges around the plan's ~1.2 kHz
SPLASH_BAND_HI_HZ = 2_000.0
SPLASH_DECAY = 5.0             # plan-fixed exp(-t * 5)
SPLASH_PEAK = 0.9

UI_CLICK_DUR_S = 0.06          # tiny 2 kHz blip (plan-fixed pitch)
UI_CLICK_HZ = 2_000.0
UI_CLICK_DECAY = 70.0
UI_CLICK_ATTACK_S = 0.002      # linear ramp-in avoids a start pop
UI_CLICK_PEAK = 0.6

# Task LC launch cinematics: the Oniks cap 'crack' (nose-cap pull-away
# motors) and the full-thrust 'slam' (high-thrust mode lighting — a deep
# detonation rolling into a crackling tear).
CAP_CRACK_DUR_S = 0.30
CAP_CRACK_BAND_HZ = (900.0, 3_500.0)   # bandpassed snap
CAP_CRACK_DECAY = 18.0                 # very fast transient
CAP_CRACK_ATTACK_S = 0.002
CAP_CRACK_PEAK = 0.85

SLAM_DUR_S = 2.4
SLAM_SINE_HZ = 36.0            # deeper than the booms' 40 Hz
SLAM_SINE_DECAY = 1.5
SLAM_NOISE_FC_HZ = 520.0       # mid burst: the body of the slam
SLAM_NOISE_DECAY = 2.2
SLAM_NOISE_MIX = 1.05
SLAM_CRACKLE_FC_HZ = 2_600.0   # sparse crackle riding the tail
SLAM_CRACKLE_DECAY = 1.1
SLAM_CRACKLE_MIX = 0.22

# Fixed synthesis seeds: the cached wav files are reproducible.
_SEEDS = {"launch": 101, "booster": 102, "cruise": 103,
          "boom_far": 104, "boom_near": 105, "splash": 106,
          "cap_crack": 107, "slam": 108}


# ------------------------------------------------------------ DSP helpers

def attenuation(dist_m: float) -> float:
    """Plan-fixed camera-distance falloff: clip(1 - d/12 km, 0, 1) ** 1.4."""
    return float(np.clip(1.0 - dist_m / ATTEN_RANGE_M, 0.0, 1.0) ** ATTEN_POW)


def _time(dur_s: float) -> np.ndarray:
    return np.arange(round(dur_s * SAMPLE_RATE)) / SAMPLE_RATE


def _unit(x: np.ndarray) -> np.ndarray:
    """Scale to unit peak (silence passes through)."""
    peak = float(np.max(np.abs(x)))
    return x / peak if peak > 0.0 else x


def _normalize(x: np.ndarray, peak: float = PEAK_NORM) -> np.ndarray:
    return _unit(x) * peak


def brown_noise(rng, n: int) -> np.ndarray:
    """Plan-fixed brown noise: cumsum of white, scaled to unit peak."""
    x = np.cumsum(rng.standard_normal(n))
    return x / np.abs(x).max()


def one_pole_lowpass(x: np.ndarray, fc_hz: float,
                     fs: int = SAMPLE_RATE) -> np.ndarray:
    """One-pole IIR lowpass (6 dB/oct). Python loop — synthesis runs once at
    first startup and is cached to sounds/*.wav after."""
    a = 1.0 - np.exp(-2.0 * np.pi * fc_hz / fs)
    y = np.empty(len(x))
    acc = 0.0
    for i, xi in enumerate(x):
        acc += a * (xi - acc)
        y[i] = acc
    return y


def bandpass(x: np.ndarray, lo_hz: float, hi_hz: float) -> np.ndarray:
    """Crude bandpass: difference of two one-pole lowpasses."""
    return one_pole_lowpass(x, hi_hz) - one_pole_lowpass(x, lo_hz)


def make_loopable(x: np.ndarray, fade_s: float = LOOP_FADE_S) -> np.ndarray:
    """Crossfade the last ``fade_s`` of ``x`` into its head so the loop wrap
    is seamless; returns the first ``len(x) - fade`` samples (so synths
    render ``duration + fade`` and get exactly ``duration`` back)."""
    fade = round(fade_s * SAMPLE_RATE)
    body, tail = x[:-fade], x[-fade:]
    out = body.copy()
    w = np.linspace(0.0, 1.0, fade)
    out[:fade] = tail * (1.0 - w) + body[:fade] * w
    return out


# --------------------------------------------------------------- recipes

def synth_launch() -> np.ndarray:
    """Gas-eject thump: lowpassed brown noise + 55 Hz sine, both decaying."""
    rng = np.random.default_rng(_SEEDS["launch"])
    t = _time(LAUNCH_DUR_S)
    noise = _unit(one_pole_lowpass(brown_noise(rng, len(t)),
                                   LAUNCH_NOISE_FC_HZ))
    x = noise * np.exp(-t * LAUNCH_NOISE_DECAY)
    x += (LAUNCH_THUMP_MIX * np.sin(2.0 * np.pi * LAUNCH_THUMP_HZ * t)
          * np.exp(-t * LAUNCH_THUMP_DECAY))
    return _normalize(x)


def synth_booster() -> np.ndarray:
    """Solid-booster roar loop: brown noise fc 220 Hz, 8 Hz wobble."""
    rng = np.random.default_rng(_SEEDS["booster"])
    t = _time(BOOSTER_DUR_S + LOOP_FADE_S)
    x = _unit(one_pole_lowpass(brown_noise(rng, len(t)), BOOSTER_FC_HZ))
    x *= 1.0 + BOOSTER_WOBBLE_DEPTH * np.sin(
        2.0 * np.pi * BOOSTER_WOBBLE_HZ * t)
    return _normalize(make_loopable(x))


def synth_cruise() -> np.ndarray:
    """Ramjet hiss loop: pink-ish (brown + white) noise fc 900 Hz, low gain."""
    rng = np.random.default_rng(_SEEDS["cruise"])
    n = len(_time(CRUISE_DUR_S + LOOP_FADE_S))
    mix = (brown_noise(rng, n)
           + CRUISE_WHITE_MIX * _unit(rng.standard_normal(n)))
    x = one_pole_lowpass(mix, CRUISE_FC_HZ)
    return _normalize(make_loopable(x), CRUISE_PEAK)


def synth_boom_far() -> np.ndarray:
    """Distant explosion: 40 Hz rumble + soft lowpassed noise burst."""
    rng = np.random.default_rng(_SEEDS["boom_far"])
    t = _time(BOOM_FAR_DUR_S)
    x = (np.sin(2.0 * np.pi * BOOM_FAR_SINE_HZ * t)
         * np.exp(-t * BOOM_FAR_SINE_DECAY))
    burst = _unit(one_pole_lowpass(brown_noise(rng, len(t)),
                                   BOOM_FAR_NOISE_FC_HZ))
    x += BOOM_FAR_NOISE_MIX * burst * np.exp(-t * BOOM_FAR_NOISE_DECAY)
    return _normalize(x)


def synth_boom_near() -> np.ndarray:
    """Close explosion: same bones, shorter and sharper (noise fc 800 Hz)."""
    rng = np.random.default_rng(_SEEDS["boom_near"])
    t = _time(BOOM_NEAR_DUR_S)
    x = (np.sin(2.0 * np.pi * BOOM_NEAR_SINE_HZ * t)
         * np.exp(-t * BOOM_NEAR_SINE_DECAY))
    burst = _unit(one_pole_lowpass(brown_noise(rng, len(t)),
                                   BOOM_NEAR_NOISE_FC_HZ))
    x += BOOM_NEAR_NOISE_MIX * burst * np.exp(-t * BOOM_NEAR_NOISE_DECAY)
    return _normalize(x)


def synth_splash() -> np.ndarray:
    """Water impact: white noise bandpassed ~1.2 kHz, fast decay."""
    rng = np.random.default_rng(_SEEDS["splash"])
    t = _time(SPLASH_DUR_S)
    x = _unit(bandpass(rng.standard_normal(len(t)),
                       SPLASH_BAND_LO_HZ, SPLASH_BAND_HI_HZ))
    return _normalize(x * np.exp(-t * SPLASH_DECAY), SPLASH_PEAK)


def synth_ui_click() -> np.ndarray:
    """Tiny 2 kHz blip for map/menu interactions."""
    t = _time(UI_CLICK_DUR_S)
    x = np.sin(2.0 * np.pi * UI_CLICK_HZ * t) * np.exp(-t * UI_CLICK_DECAY)
    x *= np.clip(t / UI_CLICK_ATTACK_S, 0.0, 1.0)
    return _normalize(x, UI_CLICK_PEAK)


def synth_cap_crack() -> np.ndarray:
    """Oniks nose-cap pull-away: a sharp bandpassed CRACK over the roar."""
    rng = np.random.default_rng(_SEEDS["cap_crack"])
    t = _time(CAP_CRACK_DUR_S)
    x = _unit(bandpass(rng.standard_normal(len(t)),
                       CAP_CRACK_BAND_HZ[0], CAP_CRACK_BAND_HZ[1]))
    x *= np.exp(-t * CAP_CRACK_DECAY)
    x *= np.clip(t / CAP_CRACK_ATTACK_S, 0.0, 1.0)   # popless attack
    return _normalize(x, CAP_CRACK_PEAK)


def synth_slam() -> np.ndarray:
    """High-thrust ignition: a second, deeper detonation rolling into a
    crackling Saturn-style tear (36 Hz rumble + mid burst + crackle tail)."""
    rng = np.random.default_rng(_SEEDS["slam"])
    t = _time(SLAM_DUR_S)
    x = (np.sin(2.0 * np.pi * SLAM_SINE_HZ * t)
         * np.exp(-t * SLAM_SINE_DECAY))
    burst = _unit(one_pole_lowpass(brown_noise(rng, len(t)),
                                   SLAM_NOISE_FC_HZ))
    x += SLAM_NOISE_MIX * burst * np.exp(-t * SLAM_NOISE_DECAY)
    crackle = rng.standard_normal(len(t))
    crackle = _unit(crackle - one_pole_lowpass(crackle, SLAM_CRACKLE_FC_HZ))
    x += SLAM_CRACKLE_MIX * crackle * np.exp(-t * SLAM_CRACKLE_DECAY)
    return _normalize(x)


SYNTHS = {"launch": synth_launch, "booster": synth_booster,
          "cruise": synth_cruise, "boom_far": synth_boom_far,
          "boom_near": synth_boom_near, "splash": synth_splash,
          "ui_click": synth_ui_click, "cap_crack": synth_cap_crack,
          "slam": synth_slam}


# ------------------------------------------------------------- wav cache

def write_wav(path: str, samples: np.ndarray) -> None:
    """Write mono 16-bit PCM at SAMPLE_RATE."""
    data = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data.tobytes())


def ensure_sound_files(dirpath: str = SOUND_DIR) -> dict[str, str]:
    """Synthesize + write any missing wav; return {name: path} for all."""
    os.makedirs(dirpath, exist_ok=True)
    paths = {}
    for name, synth in SYNTHS.items():
        path = os.path.join(dirpath, f"{name}.wav")
        if not os.path.exists(path):
            write_wav(path, synth())
        paths[name] = path
    return paths


# ---------------------------------------------------------------- manager

class AudioManager:
    """Loads the cached sounds and plays them with camera-distance gain.

    One-shots pick any free unreserved channel; the per-missile engine
    loops own one of the LOOP_CHANNELS reserved channels each (keyed by
    ``id(missile)``, reused across the booster -> cruise hand-off, freed
    when the missile disappears from the per-frame source dict).
    """

    @staticmethod
    def pre_init() -> None:
        """Plan-fixed mixer settings; MUST run before pygame.init()."""
        pygame.mixer.pre_init(MIXER_FREQ, MIXER_SIZE, MIXER_CHANNELS,
                              MIXER_BUFFER)

    def __init__(self, sound_dir: str = SOUND_DIR, enabled: bool = True):
        self.enabled = False
        self.listener = np.zeros(3)
        self.sounds: dict = {}
        self._loops: dict = {}              # key -> [channel_id, loop_name]
        self._free = list(range(LOOP_CHANNELS))
        if not enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(MIXER_FREQ, MIXER_SIZE, MIXER_CHANNELS,
                                  MIXER_BUFFER)
        except pygame.error:
            return                          # no audio device: stay silent
        self.sounds = {name: pygame.mixer.Sound(path)
                       for name, path in ensure_sound_files(sound_dir).items()}
        pygame.mixer.set_num_channels(NUM_CHANNELS)
        # Keeps a stray Sound.play() off the loop channels; our own one-shot
        # path scans the unreserved range explicitly (see ``play``).
        pygame.mixer.set_reserved(LOOP_CHANNELS)
        self.enabled = True

    # ------------------------------------------------------------- listener

    def set_listener(self, eye) -> None:
        """Camera eye (float64 world position) — gains derive from it."""
        self.listener = np.asarray(eye, dtype=np.float64).copy()

    def _gain(self, pos, gain: float) -> float:
        if pos is None:
            return float(gain)
        dist = float(np.linalg.norm(np.asarray(pos, dtype=np.float64)
                                    - self.listener))
        return float(gain) * attenuation(dist)

    # ------------------------------------------------------------- one-shots

    def play(self, name: str, pos=None, gain: float = 1.0) -> None:
        """Fire-and-forget; ``pos`` (world, float64) applies camera-distance
        attenuation, ``pos=None`` plays flat (UI)."""
        if not self.enabled:
            return
        g = self._gain(pos, gain)
        if g < MIN_GAIN:
            return
        # Scan the unreserved range ourselves: pygame's find_channel ignores
        # set_reserved (it only guards Sound.play), and a manual pick lets
        # the volume be set BEFORE the channel starts (no full-gain pop).
        for i in range(LOOP_CHANNELS, NUM_CHANNELS):
            channel = pygame.mixer.Channel(i)
            if not channel.get_busy():
                channel.set_volume(g)
                channel.play(self.sounds[name])
                return

    def boom(self, pos) -> None:
        """Explosion one-shot: near or far variant by camera distance."""
        if not self.enabled:
            return
        dist = float(np.linalg.norm(np.asarray(pos, dtype=np.float64)
                                    - self.listener))
        self.play("boom_near" if dist <= BOOM_NEAR_M else "boom_far", pos=pos)

    def ui_click(self) -> None:
        self.play("ui_click", gain=UI_GAIN)

    # ----------------------------------------------------------------- loops

    def update_loops(self, sources: dict) -> None:
        """Reconcile the engine loops with ``sources``:
        ``{key: (loop_name, pos, gain)}`` for every loop that should sound
        this frame. Keys keep their channel across loop-name changes
        (booster -> cruise); missing keys stop and free their channel."""
        if not self.enabled:
            return
        for key in [k for k in self._loops if k not in sources]:
            cid, _ = self._loops.pop(key)
            pygame.mixer.Channel(cid).stop()
            self._free.append(cid)
        for key, (name, pos, gain) in sources.items():
            slot = self._loops.get(key)
            if slot is None:
                if not self._free:          # all loop channels taken
                    continue
                slot = self._loops[key] = [self._free.pop(), None]
            channel = pygame.mixer.Channel(slot[0])
            if slot[1] != name:
                slot[1] = name
                channel.play(self.sounds[name], loops=-1)
            channel.set_volume(self._gain(pos, gain))

    def stop_loops(self) -> None:
        if not self.enabled:
            return
        for cid, _ in self._loops.values():
            pygame.mixer.Channel(cid).stop()
            self._free.append(cid)
        self._loops.clear()
