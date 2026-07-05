"""Live end-to-end probe of the BLACK BOX loop (AI-testability build).

Boots the real App hidden, forces the ledger/bug dirs to probe paths,
drives a battle through the REAL input path (KEYDOWN events + the map's
own state), then verifies with exit codes:

  1. the battle ledger JSONL exists and holds header/cmd/hint/toggle/hash;
  2. a denied launch left BOTH the ok=False cmd and the hint line;
  3. F3 filed a bug report folder (report.md + ledger.jsonl +
     commands.json + screenshot.png);
  4. tools/replay_battle.py verifies the recording (exit 0, hashes OK).

Run: python tools/probe_blackbox_live.py   -> PASS/FAIL lines, exit 0/1.
"""

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

FAILS = []


def check(name, ok):
    print(f"[probe] {'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        FAILS.append(name)


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    bb_dir = os.path.join("renders", "_probe_blackbox")
    bug_dir = os.path.join("renders", "_probe_bug_reports")
    for d in (bb_dir, bug_dir):
        shutil.rmtree(d, ignore_errors=True)

    from main import App, PHYS_DT
    app = App(hidden=True)
    app.blackbox_dir = bb_dir           # hidden default is None: force it
    app.bug_report_dir = bug_dir
    app.start_combat()
    state = app.state

    check("ledger file opens with the battle",
          state.ledger.path is not None)

    def key(k):
        state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))

    def frame(n=1):
        for _ in range(n):
            state.sim_step(PHYS_DT)

    # --- scripted battle through the real dispatch ------------------------
    frame(60)
    # A real Oniks launch: the map click sets target_point; SPACE fires.
    state.target_point = np.array([0.0, 0.0, 200_000.0])
    key(pygame.K_SPACE)
    frame(30)
    # A DENIED launch: S-300 platform with no air track selected.
    key(pygame.K_TAB)                   # bastion -> s300
    key(pygame.K_SPACE)                 # -> HINT_S300_AIR denial
    # EMCON flip (a replayable toggle).
    key(pygame.K_r)
    frame(30)
    # F3: file the bug report mid-battle.
    key(pygame.K_F3)
    # The App loop saves the bug shot after render — mimic one frame of it.
    state.render(1.0 / 60.0)
    if app.bug_shot_path:
        path, app.bug_shot_path = app.bug_shot_path, None
        pygame.image.save(app.window.read_pixels_to_surface(), path)
    frame(1200)                         # ~10 s: hash records land (600 cadence)

    led = state.ledger
    recs = {r["rec"] for r in led.records}
    check("ledger holds header/cmd/hint/toggle/hash/mark records",
          {"header", "cmd", "hint", "toggle", "hash", "mark"} <= recs)
    cmds = [r for r in led.records if r["rec"] == "cmd"]
    check("the Oniks launch recorded ok=True with resolved args",
          any(c["verb"] == "launch" and c["ok"]
              and c["args"]["target_point"][2] == 200_000.0 for c in cmds))
    check("the denied S-300 press left the hint line",
          any(r["rec"] == "hint" and "S-300" in r["text"]
              for r in led.records))
    check("the EMCON flip recorded as toggle radar",
          any(r["rec"] == "toggle" and r["name"] == "radar"
              for r in led.records))

    # --- bug report bundle -------------------------------------------------
    bugs = sorted(os.listdir(bug_dir)) if os.path.isdir(bug_dir) else []
    check("bug report folder created", len(bugs) == 1)
    if bugs:
        folder = os.path.join(bug_dir, bugs[0])
        names = set(os.listdir(folder))
        check("bundle holds report.md + ledger.jsonl + commands.json + "
              "screenshot.png",
              {"report.md", "ledger.jsonl", "commands.json",
               "screenshot.png"} <= names)
        report = open(os.path.join(folder, "report.md"),
                      encoding="utf-8").read()
        check("report states seed + platform + repro command",
              "SEED" in report and "ACTIVE PLATFORM" in report
              and "replay_battle.py" in report)

    # --- close + replay-verify the ledger ----------------------------------
    ledger_path = led.path
    app.quit_to_menu()                  # dispose() closes the ledger file
    header_ok = os.path.exists(ledger_path)
    check("ledger JSONL persisted", header_ok)
    r = subprocess.run([sys.executable, "tools/replay_battle.py",
                        ledger_path, "--quiet"],
                       capture_output=True, text=True, timeout=600)
    print(r.stdout.strip()[-400:])
    check("replay_battle verifies the recording (exit 0)",
          r.returncode == 0 and "MISMATCH" not in r.stdout)

    pygame.quit()
    print(f"[probe] {'ALL PASS' if not FAILS else f'{len(FAILS)} FAIL'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
