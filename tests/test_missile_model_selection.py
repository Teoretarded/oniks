from types import SimpleNamespace

import numpy as np

from game.sandbox import _missile_mesh_key
from sim.a2a import IrMissile


class _Target:
    alive = True

    def __init__(self):
        self.pos = np.array([0.0, 0.0, 1000.0])

    def velocity(self):
        return np.zeros(3)


def test_missile_mesh_key_uses_weapon_id_for_dedicated_models():
    for weapon_id in ("tomahawk", "jassm", "harm", "s300", "40n6", "sm2",
                      "pantsir_57e6", "zircon", "sm6"):
        m = SimpleNamespace(weapon=SimpleNamespace(weapon_id=weapon_id))
        assert _missile_mesh_key(m) == weapon_id


def test_missile_mesh_key_identifies_aim9x_ir_round():
    m = IrMissile(np.zeros(3), np.array([0.0, 0.0, 300.0]), _Target())
    assert _missile_mesh_key(m) == "aim9x"
