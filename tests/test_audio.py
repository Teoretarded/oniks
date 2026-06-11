"""game/audio.py synthesis + attenuation tests (GL-free, mixer never init)."""

import os
import wave

import numpy as np
import pytest

from game import audio

FS = audio.SAMPLE_RATE


# ----------------------------------------------------------- attenuation

def test_attenuation_endpoints():
    assert audio.attenuation(0.0) == pytest.approx(1.0)
    assert audio.attenuation(audio.ATTEN_RANGE_M) == 0.0
    # Sounds far beyond the range (e.g. 600 km away) are exactly silent.
    assert audio.attenuation(600_000.0) == 0.0
    assert audio.attenuation(audio.ATTEN_RANGE_M * 0.5) == pytest.approx(
        0.5 ** audio.ATTEN_POW)


def test_attenuation_monotone_decreasing():
    d = np.linspace(0.0, 14_000.0, 60)
    g = [audio.attenuation(x) for x in d]
    assert all(a >= b for a, b in zip(g, g[1:]))
    assert all(0.0 <= x <= 1.0 for x in g)


# ------------------------------------------------------------- synthesis

EXPECTED = [
    # name        duration s              normalized peak
    ("launch",    audio.LAUNCH_DUR_S,     audio.PEAK_NORM),
    ("booster",   audio.BOOSTER_DUR_S,    audio.PEAK_NORM),
    ("cruise",    audio.CRUISE_DUR_S,     audio.CRUISE_PEAK),
    ("boom_far",  audio.BOOM_FAR_DUR_S,   audio.PEAK_NORM),
    ("boom_near", audio.BOOM_NEAR_DUR_S,  audio.PEAK_NORM),
    ("splash",    audio.SPLASH_DUR_S,     audio.SPLASH_PEAK),
    ("ui_click",  audio.UI_CLICK_DUR_S,   audio.UI_CLICK_PEAK),
    # Task LC launch cinematics
    ("cap_crack", audio.CAP_CRACK_DUR_S,  audio.CAP_CRACK_PEAK),
    ("slam",      audio.SLAM_DUR_S,       audio.PEAK_NORM),
]


def test_cap_crack_is_short_and_sharp():
    """The cap 'crack' is a sharp transient: short, with its energy packed
    into the first third of the waveform."""
    x = audio.SYNTHS["cap_crack"]()
    assert audio.CAP_CRACK_DUR_S <= 0.5
    e = x * x
    third = len(e) // 3
    assert e[:third].sum() > 0.7 * e.sum()


def test_slam_has_deep_sustained_tail():
    """The full-thrust slam rolls longer than the cap crack and keeps
    meaningful energy past the first second (the rolling tear)."""
    x = audio.SYNTHS["slam"]()
    assert audio.SLAM_DUR_S >= 1.5
    fs = audio.SAMPLE_RATE
    tail = x[fs:]
    assert np.abs(tail).max() > 0.05


def test_every_synth_listed_once():
    assert sorted(n for n, _, _ in EXPECTED) == sorted(audio.SYNTHS)


@pytest.mark.parametrize("name,dur,peak", EXPECTED, ids=[e[0] for e in EXPECTED])
def test_synth_duration_and_peak(name, dur, peak):
    x = audio.SYNTHS[name]()
    assert x.ndim == 1
    assert len(x) == round(dur * FS)
    assert np.isfinite(x).all()
    assert np.max(np.abs(x)) == pytest.approx(peak, rel=1e-9)


def test_synths_deterministic():
    a = audio.SYNTHS["launch"]()
    b = audio.SYNTHS["launch"]()
    assert np.array_equal(a, b)


def test_make_loopable_seamless_junction():
    rng = np.random.default_rng(7)
    raw = audio.one_pole_lowpass(rng.standard_normal(FS), 220.0)
    out = audio.make_loopable(raw)
    fade = round(audio.LOOP_FADE_S * FS)
    n = len(raw) - fade
    assert len(out) == n
    # The wrap point continues the raw signal sample-for-sample:
    # out[-1] = raw[n-1] and out[0] = raw[n] (its immediate successor).
    assert out[-1] == raw[n - 1]
    assert out[0] == pytest.approx(raw[n], abs=1e-12)
    # By the end of the crossfade the head is the plain body again.
    assert out[fade - 1] == pytest.approx(raw[fade - 1], abs=1e-12)


def test_loop_sounds_have_small_wrap_step():
    for name in audio.LOOP_SOUNDS:
        x = audio.SYNTHS[name]()
        # |end -> start| is one source-sample step of a lowpassed signal.
        assert abs(float(x[0]) - float(x[-1])) < 0.15


# ----------------------------------------------------------- wav caching

def test_ensure_sound_files_writes_then_caches(tmp_path):
    d = str(tmp_path / "sounds")
    paths = audio.ensure_sound_files(d)
    assert set(paths) == set(audio.SYNTHS)
    for p in paths.values():
        with wave.open(p, "rb") as w:
            assert w.getframerate() == FS
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getnframes() > 0
    mtimes = {p: os.path.getmtime(p) for p in paths.values()}
    assert audio.ensure_sound_files(d) == paths        # second run: cached,
    assert mtimes == {p: os.path.getmtime(p)           # nothing rewritten
                      for p in paths.values()}
