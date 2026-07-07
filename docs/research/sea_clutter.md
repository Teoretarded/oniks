# Sea-clutter detection degradation — NORMATIVE (F3-P2, 2026-07-07)

Status: NORMATIVE for `sim/clutter.py` (`sea_clutter_range_factor`).
Companion to `docs/research/radar_scan_and_bands.md`; consumed inside
`sim/radar.Radar.detects` for size classes `missile`/`stealth` below
`CLUTTER_ALT_M`.

## The physics being modeled

A surface radar looking at a low-altitude target looks THROUGH the sea
surface return.  Sea backscatter (σ⁰) rises with wind speed / sea state and
with grazing angle — the GIT (Georgia Institute of Technology) empirical
model is the standard reference shape: at the shallow grazing angles of a
sea-skimmer engagement (< 1°), σ⁰ climbs roughly 3–5 dB per Douglas state
step in the mid states, more steeply from calm.  The target's echo must
compete with the clutter power inside the same range–Doppler cells; a
skimmer at 5–15 m sits in the strongest part of the clutter ridge, a
target above a few hundred meters of altitude separates cleanly in
elevation and Doppler.

Detection range against clutter-limited (not noise-limited) targets does
NOT follow the radar equation's 4th root; clutter power falls roughly with
range³ (pulse-limited surface patch) while signal falls with range⁴, so
range degradation with rising clutter is gentler than the raw σ⁰ ratio —
which is why the model below is a bounded LINEAR factor per state rather
than dB-for-dB, with the absolute band anchored by the locked two-sided
contract (state 6 cuts a SPY-1-class radar vs a 15 m skimmer to 45–85 % of
its state-3 range — the "meaningfully hurt but never blinded" doctrine
band from the F3 review).

## The locked model

```
CLUTTER_ALT_M = 100.0                      # above this: clean separation
depth(alt)   = clamp(1 - alt / CLUTTER_ALT_M, 0, 1)
factor(s, alt) = 1.0                        for s <= 3   (EXACT — state 3
                                            is the byte-identical default;
                                            calmer seas give no bonus: the
                                            legacy ranges already assume a
                                            benign sea)
factor(s, alt) = 1.0 - R[s] * depth(alt)    for s >= 4, clamped to s = 9
R = {4: 0.10, 5: 0.22, 6: 0.38, 7: 0.52, 8: 0.63, 9: 0.72}
```

- Monotonic non-increasing in state at fixed altitude; floor
  1 − 0.72 = 0.28 ≥ the 0.25 contract bound (never blinds).
- `factor(6, 15 m) = 1 − 0.38·0.85 = 0.68` — inside the locked
  [0.45, 0.85] duel band with margin on both sides.
- R's spacing follows the GIT-shape intuition: the step from slight to
  moderate seas costs little (0.10), the rough-and-up states climb faster
  (≈ +0.13/state), flattening toward phenomenal seas where the clutter
  ridge saturates the cell anyway.
- Altitude dependence is linear in `depth`: elevation separation improves
  smoothly as the target climbs out of the ridge, gone by 100 m
  (`CLUTTER_ALT_M` — consistent with the multipath region's 150 m scale in
  sim/sam.py; the two model different phenomena and stay independent).

## Deliberate simplifications (documented, not hidden)

1. **No band dependence in v1.** Clutter σ⁰ is band-dependent, but the
   dominant effect (state × grazing) is shared; the band axis arrives with
   W-P10 rain attenuation if probes justify it.
2. **Applies over land too** when the target is under 100 m — low-altitude
   ground clutter is at least as punishing as sea clutter, so the factor
   is not gated on being over water (and the sim never asks).
3. **No radial-velocity/Doppler-notch modeling** — the missile-vs-clutter
   Doppler geometry is folded into the state factor.
4. Ships/fighters at altitude and the `ship`/`lcac` classes are untouched
   (a hull IS the surface return; its detection is horizon/EW-limited).
