# S-300/S-400 family launch phenomenology (GPT-5.6 Sol research, 2026-07-16)

Game-ready "nominal clear-day" numbers for rendering cold launches viewed
from 100 m / 500 m / 1 km / 10 km. `~` = estimated from launch footage and
photographs, not published engineering values. RGB sRGB, opacity = alpha.
Feeds `game/cinematic_missiles.py` — keep the two in sync.

Confirmed: air-start vertical (cold) launch for 48N6/9M96; footage puts
ignition around 30 m. Dimensions: 5V55 7.25x0.514 m, 48N6 7.5x0.514 m,
9M96E ~4.75x0.24 m. Sources: Rosoboronexport Rif-M brochure
(roe.ru/pdfs/pdf_2250.pdf), GICHD explosive ordnance guide for Ukraine,
Russian MoD Buk footage (Wikimedia).

## 1. Cold ejection and ignition

| Missile | Eject puff RGB/alpha | Puff dia init->max | Puff life | Ignition h | Exit->ignition | Fireball | Flash | Temp |
|---|---|---|---|---|---|---|---|---|
| 5V55 | ~190,185,170/.55 | ~4->10 m | ~2.5 s | ~22-30 m | ~0.75-0.95 s | ~3.1-4.6 m (6-9D) | ~0.10-0.18 s | ~2800-3300 K |
| 48N6 | ~180,175,160/.60 | ~5->12 m | ~3 s | ~25-32 m | ~0.75-1.0 s | ~3.6-5.2 m (7-10D) | ~0.12-0.20 s | ~3000-3400 K |
| 9M96E/E2 | ~195,190,178/.45 | ~3->7 m | ~2 s | ~20-30 m | ~0.55-0.85 s | ~1.9-2.9 m (8-12D) | ~0.08-0.15 s | ~2800-3300 K |
| 40N6 | ~175,170,155/.65 | ~5->13 m | ~3.5 s | ~25-35 m | ~0.8-1.1 s | ~3.6-5.7 m (7-11D) | ~0.12-0.22 s | ~3000-3400 K |

"Hang time" is visual only — the missile still coasts upward while
pitching, it never floats. Ignition core `255,250,225`, inner flame
`255,205,105`, fireball edge `255,125,25`; bloom can enlarge the visible
fireball another ~30-80%.

## 2. Boost flame and exhaust

| Missile | Flame length | Core / edge RGB | Flicker | Fresh exhaust RGB/alpha | Daylight at 10 km |
|---|---|---|---|---|---|
| 5V55 | ~0.8-1.2L = 5.8-8.7 m | 255,245,215 / 255,135,35 | ~25-45 Hz | 235,232,218/.85 | tiny point; smoke easier |
| 48N6 | ~0.9-1.4L = 6.8-10.5 m | 255,250,225 / 255,145,35 | ~25-45 Hz | 238,235,220/.88 | ~3' flame point, lost in haze |
| 9M96 | ~0.7-1.1L = 3.3-6.2 m | 255,245,220 / 255,150,40 | ~35-60 Hz | 240,238,225/.72 | marginal; trail identifies it |
| 40N6 | ~0.9-1.5L = 7-12 m | 255,250,225 / 255,140,30 | ~25-45 Hz | 235,232,216/.90 | visible point; column dominates |

Add slower amplitude modulation ~6-12 Hz, +/-15-25%, over the flicker.

## 3. Smoke column

| Missile | Base cloud width | Trail width @200 m | Fresh -> 30 s RGB | 30 s width | Persistence | Burnout trail height |
|---|---|---|---|---|---|---|
| 5V55 | ~14-20 m | ~4-6 m | 235,233,220 -> 175,180,180 | ~30-50 m | ~3-7 min | ~6-10 km |
| 48N6 | ~16-24 m | ~5-8 m | 238,235,220 -> 175,180,182 | ~35-60 m | ~4-8 min | ~8-12 km |
| 9M96E | ~8-14 m | ~2.5-4.5 m | 242,240,228 -> 185,188,188 | ~20-40 m | ~2-5 min | ~3-6 km |
| 40N6 | ~18-26 m | ~6-9 m | 235,232,215 -> 170,178,180 | ~40-65 m | ~5-10 min | ~8-15 km first burn |

Light wind preset: 2-4 m/s; drift after 30 s = 60-120 m; radial expansion
~0.4-0.8 m/s; alpha fresh .75-.90, 30 s .18-.30, 5 min .03-.08. Break the
column into turbulent segments after ~20-40 s.

## 4. Burn and acceleration

| Missile | Powered time | Net axial accel | Notes |
|---|---|---|---|
| 5V55 | ~8-12 s | ~14-22 g avg; 25-30 g late | some tables claim 26 s; footage favours shorter |
| 48N6 | ~11-12.5 s | ~14-19 g avg; 22-28 g late | published burn ~12 s |
| 9M96E | ~5-8 s | ~16-24 g avg | E = single pulse |
| 9M96D/E2 | ~5-7 s + ~3-5 s | ~18-28 g in pulses | pulse separation 5-25 s, engagement-dependent |
| 40N6 | ~8-12 s first; 12-18 s total | ~12-20 g first pulse | dual-pulse unconfirmed; render 2nd as detached high segment |

## 5. Apparent angular sizes (48N6: 7.5 m body, 4.5 m fireball, 9 m flame, 20 m cloud)

| Distance | Missile | Fireball | Flame | Cloud |
|---|---|---|---|---|
| 100 m | 4.30 deg | 2.58 deg | 5.15 deg | 11.4 deg |
| 500 m | 0.86 deg | 0.52 deg | 1.03 deg | 2.29 deg |
| 1 km | 0.43 deg | 0.26 deg | 0.52 deg | 1.15 deg |
| 10 km | 2.58' | 1.55' | 3.09' | 6.88' |

## 6. Observer + sound

| Range | Eject arrives | Ignition arrives | Level | Dominates |
|---|---|---|---|---|
| 100 m | 0.29 s | ~1.1-1.3 s | ~135-145 dB | flash, cap fragments, dust blast, ground rumble |
| 500 m | 1.46 s | ~2.2-2.5 s | ~121-131 dB | pop then cracking roar; full missile visible |
| 1 km | 2.92 s | ~3.7-4.0 s | ~115-125 dB | flash first, heavy delayed boom; smoke is the scale cue |
| 10 km | 29.2 s | ~30-31 s | ~90-103 dB | tiny bright point, long trail, low rumble late |

Eject pop ~25-35 dB below ignition (inaudible at 10 km). Rocket noise is
strongly low-frequency with crackling transients (NASA KSC-STD-164C).

## 7. Hot-launch contrast (for future Buk/Pantsir scenes)

Buk 9M38: rail-level ignition, 0 s delay, immediate flame/exhaust wash at
the vehicle. Pantsir 57E6: tube-mouth flash ~1.2-2 m, booster burns
~1.5-2 s then separates. The cold-launch signature is the fireball tens
of meters ABOVE the launcher and the pop-pause-boom rhythm.
