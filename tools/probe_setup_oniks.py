"""Probe the ONIKS TELs setup stepper: clamp round-trip, world build, and a
render of the World page so the new row can be eyeballed for overflow."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from world.combat import CombatWorld
from world.combat_config import clamp_config

# 1) clamp round-trip + world build (GL-free)
c3 = clamp_config(n_oniks=3)
c99 = clamp_config(n_oniks=99)
print(f"clamp n_oniks: 3 -> {c3.n_oniks}, 99 -> {c99.n_oniks} (expect 3, 5)")
w = CombatWorld(c3)
nl = len(w._oniks_launcher_positions)
nb = sum(1 for s in w.structures if s.kind == "bastion_tel")
print(f"world from setup config n_oniks=3: launchers={nl} bastion_tel={nb}")

# 2) render the setup World page
from main import App, PHYS_DT          # noqa: E402  (App after the GL-free part)

app = App(hidden=True)
app.open_combat_setup()
state = app.state
for _ in range(18):
    state.render(PHYS_DT)
os.makedirs("renders", exist_ok=True)
pygame.image.save(app.window.read_pixels_to_surface(),
                  os.path.join("renders", "setup_world_oniks.png"))
print("[shot] renders/setup_world_oniks.png")
pygame.quit()
