"""M1 (Legibility Foundation) verification probe — drives REAL headless
battles and MEASURES the new HUD-helper behavior with numbers.

Run from the repo root:  python tools/probe_m1_legibility.py

Tests (matching the GAME-TEST brief 1-6):
  1. threat_rows live: sorted by TTI, severity bands, TTI shrinks, drops off.
  2. FOG honesty: a hostile in world.missiles but NOT in contacts.tracks is
     ABSENT from threat_rows.
  3. tube_cells after firing: RELOADING frac rises -> READY.
  4. contact_intel on a live track + a high-age coasting track.
  5. DETERMINISM: two worlds stepped ~3000 steps, MAX positional delta == 0.0.
  6. No crashes: all three helpers called repeatedly over 6+ sim minutes.

This script is read-only w.r.t. source/tests — it only imports and measures.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from game.hud import (HOSTILE_KINDS, TTI_CRIT_S, TTI_WARN_S, AGE_CLASSIFIED_S,
                      AGE_IDENTIFIED_S, contact_intel, threat_rows,
                      tube_cells)  # noqa: E402
from sim.arsenal import TOMAHAWK  # noqa: E402
from sim.strike import StrikeMissile  # noqa: E402
from world.combat import CombatWorld  # noqa: E402
from world.combat_config import CombatConfig  # noqa: E402
from world.generation import BASE_POS  # noqa: E402

PHYS_DT = 1.0 / 120.0
FRIENDLY = (BASE_POS[0], BASE_POS[2])

# Verdict accumulator.
_CONCERNS = []
_CRITICAL = []


def note_concern(msg):
    _CONCERNS.append(msg)
    print(f"  [CONCERN] {msg}", flush=True)


def note_critical(msg):
    _CRITICAL.append(msg)
    print(f"  [CRITICAL] {msg}", flush=True)


def hdr(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}", flush=True)


# --------------------------------------------------------------------------
# Shared: build a world and step it (radar emitting) until the enemy launches
# hostile rounds we can see on the strip. Returns (world, first_seen_time).
# --------------------------------------------------------------------------

def run_until_inbound(max_sim_s=600.0, want_strip=True):
    """Step a default CombatWorld with the player radar emitting until a
    hostile round shows on threat_rows (want_strip) or until any hostile
    missile exists in world.missiles. Returns (world, t_first, log)."""
    w = CombatWorld()
    # Radar emits by default; confirm.
    assert w.radar_station.emitting, "radar should emit at spawn"
    log = []
    t_first_missile = None
    t_first_strip = None
    n = int(max_sim_s / PHYS_DT)
    for i in range(n):
        w.step(PHYS_DT)
        w.drain_events()
        hostiles = [m for m in w.missiles
                    if getattr(m, "is_hostile", False) and m.alive]
        rows = threat_rows(w, FRIENDLY, w.sim_time)
        if hostiles and t_first_missile is None:
            t_first_missile = w.sim_time
        if rows and t_first_strip is None:
            t_first_strip = w.sim_time
        # Sample roughly every 5 s for the log once things are moving.
        if (i % int(5.0 / PHYS_DT) == 0) and (hostiles or rows):
            log.append((w.sim_time, len(hostiles), len(rows)))
        if want_strip and t_first_strip is not None:
            break
        if (not want_strip) and t_first_missile is not None:
            break
    return w, t_first_strip, t_first_missile, log


# --------------------------------------------------------------------------
# TEST 1 + 2 — threat strip live + FOG honesty.
# --------------------------------------------------------------------------

def test_threat_and_fog():
    hdr("TEST 1 — Threat strip live  (+  TEST 2 — FOG honesty)")
    w, t_strip, t_missile, log = run_until_inbound(max_sim_s=600.0,
                                                   want_strip=True)
    print(f"  HOSTILE_KINDS gate = {sorted(HOSTILE_KINDS)}")
    print(f"  first hostile missile in world.missiles at t = "
          f"{t_missile if t_missile else 'NONE'}")
    print(f"  first row on threat_rows           at t = "
          f"{t_strip if t_strip else 'NONE'}")

    if t_missile is None:
        note_critical("No hostile missiles appeared within 600 s of radar "
                      "emission — could not drive inbounds.")
        return None

    # --- TEST 2 FOG honesty: at the moment the FIRST hostile missile exists,
    # was it absent from the strip (i.e. radar-gated, under the horizon)?  We
    # re-run a fresh world to catch that exact instant cleanly.
    fog_ok = False
    wf = CombatWorld()
    for _ in range(int(600.0 / PHYS_DT)):
        wf.step(PHYS_DT)
        wf.drain_events()
        hostiles = [m for m in wf.missiles
                    if getattr(m, "is_hostile", False) and m.alive]
        if not hostiles:
            continue
        # Which hostiles are NOT on the contact board (under the horizon)?
        on_board = set(wf.contacts.tracks.keys())
        unseen = [m for m in hostiles if m.aircraft_id not in on_board]
        rows = threat_rows(wf, FRIENDLY, wf.sim_time)
        strip_ids = {r.sid for r in rows}
        if unseen:
            # confirm none of the unseen hostiles leaked onto the strip
            leaked = [m.aircraft_id for m in unseen
                      if m.aircraft_id in strip_ids]
            print(f"  FOG @ t={wf.sim_time:6.1f}s : hostile missiles in flight"
                  f" = {len(hostiles)}, on contact board = {len(hostiles) - len(unseen)},"
                  f" UNSEEN (under horizon) = {len(unseen)}, strip rows = {len(rows)}")
            if not leaked:
                fog_ok = True
                kinds = sorted({(getattr(getattr(m, 'weapon', None),
                                 'weapon_id', None) or getattr(m, 'weapon_id',
                                 '?')) for m in unseen})
                print(f"      -> {len(unseen)} undetected hostile(s) {kinds} "
                      f"correctly ABSENT from the strip. FOG HONEST.")
                break
            else:
                note_critical(f"FOG LEAK: undetected hostiles {leaked} appeared"
                              f" on threat_rows at t={wf.sim_time:.1f}s")
                break
    if not fog_ok and not _CRITICAL:
        note_concern("Could not catch a moment with an undetected hostile "
                     "missile in flight (all inbounds were instantly visible — "
                     "e.g. launch-warning SM-2s). FOG honesty not directly "
                     "exercised; see analysis.")

    # --- TEST 1: drive a DETECTED, CLOSING inbound onto the strip so we can
    # measure sort-by-TTI, the severity bands, TTI shrink and drop-off. The
    # commander's Tomahawks (t=90) stay radar-gated under the horizon for
    # minutes (FOG, above), so we inject controlled hostile rounds within radar
    # range exactly as smoke_combat does for the Pantsir test (combat.py path).
    # We isolate the defenses so the round survives to close and impact (the
    # natural drop-off) rather than being shot down before it can shrink.
    w = CombatWorld()
    w.radar_station.emitting = False          # isolate from the commander layer
    for s in w.ships:                         # silence the fleet SAMs
        s.sm2_ammo = 0
        s.ciws_ammo = 0
    for p in w.pantsirs:                      # silence the Pantsirs
        p.missile_ammo = 0
        if hasattr(p, "gun"):
            p.gun.ammo = 0
    # Two Tomahawks closing on the base from the north, staggered in range so
    # they carry DISTINCT TTIs (tests the sort + multi-row strip). Low cruise
    # altitude, inside the radar net's missile-class detection range.
    for off_km, lateral in ((26.0, -400.0), (40.0, 400.0)):
        tm = StrikeMissile(
            TOMAHAWK,
            np.array([BASE_POS[0] + lateral, 60.0,
                      BASE_POS[2] + off_km * 1000.0]),
            np.array([0.0, 0.0, -220.0]),     # heading toward the base
            (BASE_POS[0], BASE_POS[2]), target_y=0.0)
        tm.launch_platform = None
        w.missiles.append(tm)

    print("\n  --- threat_rows snapshots (injected closing Tomahawks) ---")
    print("  t(s)   | rows | sorted? | severities | top: kind brg rng(km) tti(s) sev")
    snapshots = []
    prev_top_tti = {}        # sid -> last tti, to confirm shrinking
    shrink_seen = False
    drop_seen = False
    sort_ok = True
    band_ok = True
    seen_sids = set()
    last_sids = set()
    seen_danger = seen_warn = seen_muted = False
    ever_had_rows = False
    for k in range(int(360.0 / PHYS_DT)):     # up to 6 min — let them close+hit
        w.step(PHYS_DT)
        w.drain_events()
        if k % int(2.0 / PHYS_DT) != 0:       # 2 s sampling (catch DANGER band)
            continue
        rows = threat_rows(w, FRIENDLY, w.sim_time)
        for r in rows:
            seen_danger = seen_danger or r.severity == "DANGER"
            seen_warn = seen_warn or r.severity == "WARN"
            seen_muted = seen_muted or r.severity == "MUTED"
        # sort check: tti ascending with None last
        ttis = [(r.tti is None, r.tti if r.tti is not None else 0.0)
                for r in rows]
        is_sorted = ttis == sorted(ttis)
        sort_ok = sort_ok and is_sorted
        # severity band check
        for r in rows:
            exp = ("DANGER" if (r.tti is not None and r.tti < TTI_CRIT_S)
                   else "WARN" if (r.tti is not None and r.tti < TTI_WARN_S)
                   else "MUTED")
            if r.severity != exp:
                band_ok = False
        cur_sids = {r.sid for r in rows}
        # shrink check: a sid present last snapshot whose tti decreased
        for r in rows:
            if r.tti is not None and r.sid in prev_top_tti:
                if r.tti < prev_top_tti[r.sid] - 0.01:
                    shrink_seen = True
        # drop check: a sid that was present is now gone
        if last_sids - cur_sids:
            drop_seen = True
        prev_top_tti = {r.sid: r.tti for r in rows if r.tti is not None}
        seen_sids |= cur_sids
        last_sids = cur_sids
        sev_counts = {}
        for r in rows:
            sev_counts[r.severity] = sev_counts.get(r.severity, 0) + 1
        top = rows[0] if rows else None
        topstr = (f"{(top.kind or '?'):8s} {top.brg:03d} "
                  f"{top.rng/1e3:6.1f} "
                  f"{('%.0f' % top.tti) if top.tti is not None else '--':>4s} "
                  f"{top.severity}") if top else "(empty)"
        if rows:
            ever_had_rows = True
        print(f"  {w.sim_time:6.1f} | {len(rows):4d} | {str(is_sorted):5s}  "
              f"| {sev_counts} | {topstr}")
        snapshots.append((w.sim_time, rows))
        # Early out: once we've had rows and they've all dropped (impact),
        # and no hostile rounds remain alive, stop.
        if (ever_had_rows and not rows
                and not [m for m in w.missiles
                         if getattr(m, "is_hostile", False) and m.alive]):
            break

    print(f"\n  ever populated the strip with detected inbounds: {ever_had_rows}")
    print(f"  sorted-by-TTI ascending always: {sort_ok}")
    print(f"  severity bands correct (DANGER<{TTI_CRIT_S:.0f}s / "
          f"WARN<{TTI_WARN_S:.0f}s / else MUTED): {band_ok}")
    print(f"  severity bands EXERCISED: DANGER={seen_danger} WARN={seen_warn} "
          f"MUTED={seen_muted}")
    print(f"  TTI shrinks as a round closes: {shrink_seen}")
    print(f"  a track drops off the strip (intercepted/passed): {drop_seen}")
    print(f"  distinct hostile sids seen on strip: {len(seen_sids)}")
    if not ever_had_rows:
        note_critical("Could not get any detected inbound onto threat_rows.")
    if not sort_ok:
        note_critical("threat_rows not sorted by TTI ascending.")
    if not band_ok:
        note_critical("threat_rows severity band mismatch.")
    if not shrink_seen:
        note_concern("Did not observe TTI shrinking on any tracked round "
                     "(rounds may have been killed/diverted before closing).")
    if not drop_seen:
        note_concern("Did not observe a round dropping off the strip in the "
                     "180 s window.")
    return w


# --------------------------------------------------------------------------
# TEST 3 — tube_cells after firing.
# --------------------------------------------------------------------------

def test_tube_cells():
    hdr("TEST 3 — tube_cells after firing (RELOADING frac -> READY)")
    w = CombatWorld()
    cells0 = tube_cells(w, "bastion")
    print(f"  initial bastion tube_cells ({len(cells0)} tubes):")
    for label, state, frac in cells0:
        print(f"    tube {label}: {state:9s} frac={frac:.3f}")
    states0 = {c[1] for c in cells0}
    print(f"  initial states: {states0}")

    tube_reload = float(getattr(w, "_oniks_tube_reload_s", 0.0))
    print(f"  per-tube reload time _oniks_tube_reload_s = {tube_reload:.1f} s")

    # Fire one Oniks (READY tube -> RELOADING).
    tgt = np.array([BASE_POS[0], 0.0, BASE_POS[2] + 150_000.0])
    m = w.launch("hi-lo", tgt)
    if m is None:
        note_critical("launch() returned None on a fresh world (no ready tube).")
        return
    cells1 = tube_cells(w, "bastion")
    reloading = [c for c in cells1 if c[1] == "RELOADING"]
    print(f"\n  after firing 1 Oniks: {len(reloading)} tube(s) RELOADING")
    if not reloading:
        note_critical("No tube entered RELOADING after a launch.")
        return
    rl_label = reloading[0][0]
    print(f"  tracking tube {rl_label}'s reload frac trajectory:")
    print("  t-since-fire(s) | state      | frac")
    traj = []
    saw_ready_again = False
    for k in range(int((tube_reload + 2.0) / PHYS_DT)):
        w.step(PHYS_DT)
        if k % int(max(tube_reload, 1.0) / 8.0 / PHYS_DT) == 0 or k == 0:
            cell = next(c for c in tube_cells(w, "bastion") if c[0] == rl_label)
            traj.append((k * PHYS_DT, cell[1], cell[2]))
            print(f"  {k * PHYS_DT:14.2f} | {cell[1]:10s} | {cell[2]:.3f}")
        cell = next(c for c in tube_cells(w, "bastion") if c[0] == rl_label)
        if cell[1] == "READY":
            saw_ready_again = True
            print(f"  -> tube {rl_label} back to READY at "
                  f"t+{k * PHYS_DT:.2f}s (frac={cell[2]:.3f})")
            break
    fracs = [f for (_, st, f) in traj if st == "RELOADING"]
    monotonic = all(b >= a - 1e-6 for a, b in zip(fracs, fracs[1:]))
    print(f"\n  RELOADING frac monotonically rising toward 1.0: {monotonic} "
          f"({fracs[0]:.3f} -> {fracs[-1]:.3f})" if fracs else
          "  (no reloading fracs captured)")
    print(f"  tube returned to READY: {saw_ready_again}")
    if not monotonic:
        note_critical("RELOADING frac not monotonically rising.")
    if not saw_ready_again:
        note_critical("Tube never returned to READY after the reload window.")

    # Also exercise the s300 battery path (it READYs off the shared pool).
    cs = tube_cells(w, "s300")
    print(f"\n  s300 tube_cells: {len(cs)} tubes, states="
          f"{ {c[1] for c in cs} }")


# --------------------------------------------------------------------------
# TEST 4 — contact_intel on a real live track + a coasting (high-age) track.
# --------------------------------------------------------------------------

def test_contact_intel():
    hdr("TEST 4 — contact_intel (live fix + dead-reckoned coast)")
    # Drive a DETECTED, closing Tomahawk so we get a genuinely FRESH air track
    # (missile-class tracks inside radar range refresh on the fast AIR period)
    # with a real course/speed/altitude — a true live fix, not a stale ELINT
    # coast. This exercises cls=MISSILE + a high-confidence IDENTIFIED fix.
    w = CombatWorld()
    w.radar_station.emitting = False
    for s in w.ships:
        s.sm2_ammo = 0
        s.ciws_ammo = 0
    for p in w.pantsirs:
        p.missile_ammo = 0
        if hasattr(p, "gun"):
            p.gun.ammo = 0
    tm = StrikeMissile(
        TOMAHAWK,
        np.array([BASE_POS[0] + 300.0, 60.0, BASE_POS[2] + 28_000.0]),
        np.array([0.0, 0.0, -220.0]),
        (BASE_POS[0], BASE_POS[2]), target_y=0.0)
    tm.launch_platform = None
    w.missiles.append(tm)
    sid = None
    last_age = 999.0
    for _ in range(int(120.0 / PHYS_DT)):
        w.step(PHYS_DT)
        w.drain_events()
        cands = [c for c in w.contacts.tracks
                 if c.startswith("strike_")]
        if cands:
            sid = cands[0]
            last_age = w.contacts.tracks[sid]["age"]
            # wait for a low-age (freshly refreshed) sample
            if last_age < AGE_IDENTIFIED_S:
                break
    if sid is None:
        note_critical("No missile track formed for contact_intel live test.")
        return

    intel = contact_intel(w, sid, FRIENDLY, w.sim_time)
    print(f"  LIVE track sid={sid}  (track age={last_age:.2f}s)")
    for kk in ("cls", "id", "confidence", "course", "speed", "alt",
               "rng", "brg", "kind", "age", "dead_reckoned", "source"):
        v = intel[kk]
        if isinstance(v, float):
            print(f"    {kk:14s} = {v:.3f}")
        else:
            print(f"    {kk:14s} = {v}")
    # sanity
    if not (0.0 <= intel["confidence"] <= 1.0):
        note_critical("confidence out of [0,1].")
    if not (0 <= intel["brg"] < 360 and 0 <= intel["course"] < 360):
        note_critical("bearing/course out of [0,360).")
    if intel["cls"] not in ("MISSILE", "AIR", "SURFACE"):
        note_critical(f"unexpected cls {intel['cls']}.")
    if intel["id"] not in ("IDENTIFIED", "CLASSIFIED", "UNKNOWN"):
        note_critical(f"unexpected id {intel['id']}.")
    # A freshly-refreshed missile track should classify sensibly.
    if intel["cls"] != "MISSILE":
        note_concern(f"closing Tomahawk track cls={intel['cls']} (expected "
                     f"MISSILE — track size stamp may be off).")
    if intel["kind"] != "tomahawk":
        note_concern(f"closing Tomahawk track kind={intel['kind']} "
                     f"(expected 'tomahawk').")
    if last_age < AGE_IDENTIFIED_S:
        if intel["id"] != "IDENTIFIED":
            note_concern(f"fresh fix (age {last_age:.1f}s) id={intel['id']} "
                         f"(expected IDENTIFIED).")
        if intel["confidence"] < 0.8:
            note_concern(f"fresh fix confidence {intel['confidence']:.2f} "
                         f"< 0.8 (expected high-confidence band).")
        if intel["dead_reckoned"]:
            note_concern("fresh fix reported dead_reckoned=True.")
        print(f"  fresh-fix verdict: id={intel['id']} "
              f"conf={intel['confidence']:.2f} dr={intel['dead_reckoned']} "
              f"src={intel['source']}")

    # --- High-age coasting track: take the live track, force its age past
    # AGE_CLASSIFIED_S by reading directly (the helper reads age off the
    # track; we age it to confirm id='UNKNOWN' + dead_reckoned True).
    trk = w.contacts.tracks[sid]
    trk_age_before = trk["age"]
    trk["age"] = AGE_CLASSIFIED_S + 5.0       # coasting, no refresh
    intel2 = contact_intel(w, sid, FRIENDLY, w.sim_time)
    print(f"\n  COASTING track (age forced {trk_age_before:.1f}s -> "
          f"{trk['age']:.1f}s):")
    print(f"    id            = {intel2['id']}   (expect UNKNOWN)")
    print(f"    dead_reckoned = {intel2['dead_reckoned']}   (expect True)")
    print(f"    confidence    = {intel2['confidence']:.3f}   (expect low)")
    print(f"    source        = {intel2['source']}   (expect COAST)")
    if intel2["id"] != "UNKNOWN":
        note_critical("high-age track id != UNKNOWN.")
    if not intel2["dead_reckoned"]:
        note_critical("high-age track dead_reckoned != True.")
    if intel2["source"] != "COAST":
        note_concern("high-age track source != COAST.")
    # None on a missing sid
    if contact_intel(w, "does_not_exist", FRIENDLY, w.sim_time) is not None:
        note_critical("contact_intel did not return None for a missing sid.")
    if contact_intel(w, None, FRIENDLY, w.sim_time) is not None:
        note_critical("contact_intel did not return None for sid=None.")
    print("  contact_intel returns None for missing/None sid: OK")


# --------------------------------------------------------------------------
# TEST 5 — DETERMINISM (bit-identical, max positional delta == 0.0).
# --------------------------------------------------------------------------

def test_determinism(n_steps=3000):
    hdr(f"TEST 5 — DETERMINISM (two worlds, {n_steps} steps, bit-identical)")
    a = CombatWorld()
    b = CombatWorld()
    for _ in range(n_steps):
        a.step(PHYS_DT)
        b.step(PHYS_DT)
        a.drain_events()
        b.drain_events()

    max_delta = 0.0
    detail = []

    # sim_time
    dt_time = abs(a.sim_time - b.sim_time)
    detail.append(("sim_time", dt_time))

    # ships
    if len(a.ships) != len(b.ships):
        note_critical(f"ship count differs: {len(a.ships)} vs {len(b.ships)}")
    for sa, sb in zip(a.ships, b.ships):
        d = float(np.max(np.abs(np.asarray(sa.pos) - np.asarray(sb.pos))))
        max_delta = max(max_delta, d)
    detail.append(("ships(max pos)", max_delta))

    # missiles
    mdelta = 0.0
    if len(a.missiles) != len(b.missiles):
        note_critical(f"missile count differs: {len(a.missiles)} vs "
                      f"{len(b.missiles)}")
    else:
        for ma, mb in zip(a.missiles, b.missiles):
            mdelta = max(mdelta, float(np.max(np.abs(
                np.asarray(ma.pos) - np.asarray(mb.pos)))))
    max_delta = max(max_delta, mdelta)
    detail.append(("missiles(max pos)", mdelta))

    # enemy air
    edelta = 0.0
    if len(a.enemy_air) != len(b.enemy_air):
        note_critical(f"enemy_air count differs: {len(a.enemy_air)} vs "
                      f"{len(b.enemy_air)}")
    else:
        for ea, eb in zip(a.enemy_air, b.enemy_air):
            edelta = max(edelta, float(np.max(np.abs(
                np.asarray(ea.pos) - np.asarray(eb.pos)))))
    max_delta = max(max_delta, edelta)
    detail.append(("enemy_air(max pos)", edelta))

    # contacts.tracks — every field (pos/vel/age/kind/size)
    ka, kb = set(a.contacts.tracks), set(b.contacts.tracks)
    track_delta = 0.0
    track_mismatch = []
    if ka != kb:
        note_critical(f"contacts.tracks keys differ: only-A={ka - kb}, "
                      f"only-B={kb - ka}")
    for cid in ka & kb:
        ta, tb = a.contacts.tracks[cid], b.contacts.tracks[cid]
        for fld in ("pos", "vel"):
            track_delta = max(track_delta, float(np.max(np.abs(
                np.asarray(ta[fld]) - np.asarray(tb[fld])))))
        if abs(ta["age"] - tb["age"]) > 0.0:
            track_delta = max(track_delta, abs(ta["age"] - tb["age"]))
        if ta.get("kind") != tb.get("kind"):
            track_mismatch.append((cid, "kind", ta.get("kind"), tb.get("kind")))
        if ta.get("size") != tb.get("size"):
            track_mismatch.append((cid, "size", ta.get("size"), tb.get("size")))
    max_delta = max(max_delta, track_delta)
    detail.append(("tracks(max pos/vel/age)", track_delta))

    print(f"  worlds: ships={len(a.ships)}/{len(b.ships)}  "
          f"missiles={len(a.missiles)}/{len(b.missiles)}  "
          f"enemy_air={len(a.enemy_air)}/{len(b.enemy_air)}  "
          f"tracks={len(ka)}/{len(kb)}")
    print(f"  sim_time A={a.sim_time:.6f}  B={b.sim_time:.6f}")
    print("\n  field                      | max |A-B| delta")
    print("  ---------------------------|----------------")
    for name, d in detail:
        print(f"  {name:26s} | {d!r}")
    if track_mismatch:
        print(f"  track kind/size mismatches: {track_mismatch}")
        note_critical(f"contacts.tracks kind/size mismatch: {track_mismatch}")

    print(f"\n  >>> MAX positional delta across ALL entities = {max_delta!r}")
    if max_delta == 0.0 and dt_time == 0.0 and not track_mismatch:
        print("  >>> DETERMINISM: BIT-IDENTICAL (max delta EXACTLY 0.0)")
        return 0.0
    note_critical(f"DETERMINISM BROKEN: max positional delta = {max_delta!r} "
                  f"(sim_time delta {dt_time!r}). The regression contract "
                  f"requires EXACTLY 0.0.")
    return max_delta


# --------------------------------------------------------------------------
# TEST 6 — No crashes: call all three helpers every few seconds over 6+ min.
# --------------------------------------------------------------------------

def test_no_crashes(sim_minutes=6.5):
    hdr(f"TEST 6 — No crashes ({sim_minutes} sim-minutes, all 3 helpers)")
    w = CombatWorld()
    calls = 0
    exceptions = []
    interval = int(3.0 / PHYS_DT)            # every 3 s
    n = int(sim_minutes * 60.0 / PHYS_DT)
    for i in range(n):
        w.step(PHYS_DT)
        w.drain_events()
        if i % interval != 0:
            continue
        try:
            rows = threat_rows(w, FRIENDLY, w.sim_time)
            calls += 1
            for r in rows:                   # touch every row
                _ = (r.sid, r.kind, r.brg, r.rng, r.tti, r.severity)
            for plat in ("bastion", "s300", "drone", "garbage"):
                _ = tube_cells(w, plat)
                calls += 1
            # contact_intel on EVERY current track (KeyError hunt on a track
            # that might lack kind/size — e.g. the ship-track injection path).
            for sid in list(w.contacts.tracks.keys()):
                _ = contact_intel(w, sid, FRIENDLY, w.sim_time)
                calls += 1
        except Exception as e:               # noqa: BLE001
            import traceback
            tb = traceback.format_exc().strip().splitlines()
            exceptions.append((w.sim_time, str(e), tb[-1] if tb else ""))
            note_critical(f"helper raised at t={w.sim_time:.1f}s: "
                          f"{tb[-1] if tb else e}")

    print(f"  total helper calls: {calls}")
    print(f"  exceptions raised:  {len(exceptions)}")
    if exceptions:
        for t, e, last in exceptions[:5]:
            print(f"    t={t:.1f}s  {last}")
    else:
        print("  -> NO exceptions across all helper calls. CLEAN.")
    # Also explicitly probe a known edge: a track WITHOUT kind/size keys
    # (the ship-track injection at combat.py ~850 builds a dict without them).
    try:
        w.contacts.tracks["__synthetic_bare__"] = dict(
            pos=np.zeros(3), vel=np.zeros(3), age=1.0,
            t_next=w.sim_time + 1.0, is_air=False)
        ci = contact_intel(w, "__synthetic_bare__", FRIENDLY, w.sim_time)
        tr = threat_rows(w, FRIENDLY, w.sim_time)   # must not KeyError
        print(f"  bare-track (no kind/size) contact_intel.cls = {ci['cls']}, "
              f"threat_rows len = {len(tr)} (no KeyError): OK")
    except Exception as e:                   # noqa: BLE001
        note_critical(f"bare track (no kind/size) crashed a helper: {e}")


# --------------------------------------------------------------------------

def main():
    print("M1 LEGIBILITY VERIFICATION PROBE")
    print(f"  CombatWorld default config; PHYS_DT={PHYS_DT:.6f}s; "
          f"BASE_POS={tuple(round(x,1) for x in BASE_POS)}")
    test_threat_and_fog()
    test_tube_cells()
    test_contact_intel()
    # 3000-step contract (the brief's minimum) AND a longer run that covers the
    # commander's t=90 inbound launches, so missiles/enemy_air/tracks are all
    # populated and compared — a far stronger regression contract.
    max_delta_3k = test_determinism(3000)
    max_delta_long = test_determinism(15000)   # 125 s: past the first salvo
    max_delta = max(max_delta_3k, max_delta_long)
    test_no_crashes(6.5)

    hdr("VERDICT")
    print(f"  DETERMINISM max positional delta = {max_delta!r} "
          f"(3000-step={max_delta_3k!r}, 15000-step={max_delta_long!r}; "
          f"contract: EXACTLY 0.0)")
    print(f"  CRITICAL findings: {len(_CRITICAL)}")
    for c in _CRITICAL:
        print(f"    - {c}")
    print(f"  CONCERNS: {len(_CONCERNS)}")
    for c in _CONCERNS:
        print(f"    - {c}")
    verdict = "PASS" if not _CRITICAL else "CONCERNS / FAIL"
    print(f"\n  OVERALL: {verdict}")
    return 0 if not _CRITICAL else 1


if __name__ == "__main__":
    sys.exit(main())
