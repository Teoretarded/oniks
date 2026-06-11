"""SandboxState: wires sim + world + render + input into the playable game.

Owns the WorldState, the Terrain/Ocean/Sky renderers, the Effects pools +
particle renderer and the cinematic CameraRig. ``sim_step`` advances the
world and turns sim happenings into effects (booster plume, exhaust trail,
explosions / splashes / deck fires, the dropped booster's ballistic tumble);
``render`` draws the scene in the fixed order sky -> terrain -> ocean ->
sites -> ships -> TEL -> missiles -> particles -> HUD/map overlay. The
tactical map (M) replaces the HUD while open and drives the player intent
fields (target_point / waypoints). Audio rides the same seams: launch /
boom / splash one-shots fire where the effects do, and per-missile
booster/cruise loops are reconciled every frame in ``render``.

GL-touching module (imports world.sky etc.) — never imported by unit tests.
"""

from __future__ import annotations

import math

import numpy as np

from engine import math3d
from engine.camera import Camera
from engine.mesh import Mesh
from engine.particles import Effects, ParticleRenderer
from engine.text import TextRenderer
from game.cameras import CameraRig
from game.controls import SandboxControls
from game.hud import HUD
from game.states import GameState
from game.tactical_map import TacticalMap
from models.bastion import build_bastion_tel
from models.common import rot_x, rot_y, rot_z
from models.oniks import build_oniks, build_oniks_booster
from models.ships_models import build_cargo, build_tanker, build_warship
from models.structures import (build_fuel_depot, build_harbor,
                               build_radar_station)
from sim.missile import (PH_BOOST, PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_EJECT,
                         PH_TERMINAL)
from sim.physics import GRAVITY
from sim.ships import ST_BURNING, ST_GONE, ST_SINKING
from world.generation import BASE_POS
from world.ocean import Ocean
from world.sky import Sky
from world.terrain import Terrain
from world.world import LAUNCH_ELEV_DEG, WorldState, launch_realtime_lock

# --- Tuning constants ---------------------------------------------------------

MISSILE_HALF_LEN = 4.45        # m, Oniks origin -> tail (models.oniks _TAIL_Z)
BOOSTER_ATTACH_BACK = 5.45     # m, missile origin -> attached booster origin
BOOSTER_TAIL_BACK = 6.45       # m, missile origin -> booster bell (boost plume)
RAMJET_PHASES = (PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_TERMINAL)

# Sustainer exhaust: a small, very short-lived additive jet right at the
# nozzle (the booster_plume's big puffs read as a fireball chain at Mach 2
# and blind the chase camera that flies through them).
RAMJET_FIRE_LIFE = (0.05, 0.12)               # s
RAMJET_FIRE_SIZE = (0.45, 1.0)                # m birth -> death
RAMJET_FIRE_COLORS = ((0.95, 0.85, 0.65), (1.0, 0.45, 0.12))
RAMJET_EXHAUST_SPEED = 18.0                   # m/s backward puff ejection

BOOSTER_LIFE = 6.0             # s the dropped booster falls before despawn
BOOSTER_SEP_DROP = 4.0         # m/s downward kick at separation
BOOSTER_DRAG = 0.55            # 1/s exponential velocity decay while falling
BOOSTER_TUMBLE_RATE = 3.2      # rad/s end-over-end tumble

SHIP_FIRE_PERIOD = 1.0 / 25.0  # s (sim) between deck-fire emissions per ship
SHIP_FIRE_VIS_RANGE = 30_000.0 # m: deck fires emit only near the camera
SHIP_FIRE_DECK_FRAC = 0.35     # fire sits this fraction of hull height up

EXPLOSION_SCALE_SHIP = 1.6     # warhead against a hull (+ splash alongside)
EXPLOSION_SCALE_GROUND = 1.3   # warhead into terrain
SPLASH_SCALE = 1.4             # clean water impact
SHIP_HIT_SPLASH_MAX_Y = 8.0    # hull hits below this height also splash

LAUNCH_PUFF_COUNT = 22         # cold-launch gas puff at the canister mouth

CRUISE_LOOP_GAIN = 1.0         # ramjet loop gain (low level baked in the wav)
BOOSTER_LOOP_GAIN = 1.0        # booster roar loop gain

TEL_ERECT_TIME = 4.0           # s for the canisters to swing 0 <-> 88 deg
TEL_ELEV_STEPS = 12            # prebaked TEL meshes across the elevation arc

_UP = np.array([0.0, 1.0, 0.0])


def _vhat(m) -> np.ndarray:
    """Missile unit velocity (vertical fallback while still in the tube)."""
    v = m.vel
    speed = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return v / speed if speed > 1e-9 else _UP.copy()


class _FallingBooster:
    """Visual-only dropped booster: ballistic fall + end-over-end tumble."""

    def __init__(self, pos, vel, forward):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.vel = np.asarray(vel, dtype=np.float64).copy()
        self.vel[1] -= BOOSTER_SEP_DROP
        self._rot0 = math3d.rotation_from_forward(forward)
        self.angle = 0.0
        self.t = 0.0

    def update(self, dt: float) -> None:
        self.t += dt
        self.vel *= np.exp(-BOOSTER_DRAG * dt)
        self.vel[1] -= GRAVITY * dt
        self.pos += self.vel * dt
        self.angle += BOOSTER_TUMBLE_RATE * dt

    @property
    def rot(self) -> np.ndarray:
        return self._rot0 @ rot_x(self.angle)

    def expired(self, surface_y: float) -> bool:
        return self.t >= BOOSTER_LIFE or self.pos[1] <= surface_y


class SandboxState(GameState):
    """The playable game: launch Oniks strikes from the Bastion battery."""

    def __init__(self, app):
        super().__init__(app)
        self.window = app.window
        self.renderer = app.renderer
        self.world = WorldState()
        self.camera = Camera()
        self.rig = CameraRig(self.camera)
        self.sky = Sky()
        self.ocean = Ocean()
        self.terrain = Terrain()
        self.effects = Effects(seed=4)
        self.particles = ParticleRenderer()
        self.controls = SandboxControls(self)
        self.text = TextRenderer()      # shared by the HUD and the map
        self.hud = HUD(self.text)
        self.hud_visible = True

        # Player intent (driven by the tactical map)
        self.profile = "hi-lo"
        self.target_point = None        # float64 (3,) sea-level aim point
        self.waypoints: list = []       # (x, z) flown before the target
        self.followed = None            # missile the cinematic cameras track
        self.map_open = False           # M toggles the tactical map
        self.tactical_map = TacticalMap(self)

        # Effects bookkeeping
        self._trails: dict[int, object] = {}      # id(missile) -> TrailRibbon
        self._boosters: list[_FallingBooster] = []
        self._fire_acc: dict[str, float] = {}     # ship_id -> emission debt
        self._tel_frac = 1.0            # canister elevation 0..1 (armed = up)

        self._build_meshes()

    # ------------------------------------------------------------ GL meshes

    def _build_meshes(self) -> None:
        self._mesh_oniks = Mesh(build_oniks())
        self._mesh_booster = Mesh(build_oniks_booster())
        self._ship_meshes = {"cargo": Mesh(build_cargo()),
                             "tanker": Mesh(build_tanker()),
                             "warship": Mesh(build_warship())}
        builders = {"radar": build_radar_station, "depot": build_fuel_depot,
                    "harbor": build_harbor}
        self._site_draws = []
        for site in self.world.sites:
            x, z = site["pos"]
            y = max(self.world.terrain_height_at(x, z), 0.0)
            self._site_draws.append((Mesh(builders[site["kind"]]()),
                                     np.array([x, y, z], dtype=np.float64)))
        self._tel_meshes = [Mesh(build_bastion_tel(elevation_deg=e))
                            for e in np.linspace(0.0, LAUNCH_ELEV_DEG,
                                                 TEL_ELEV_STEPS)]
        self._tel_pos = np.array(BASE_POS, dtype=np.float64)

    # --------------------------------------------------------------- intent

    def request_launch(self):
        """SPACE: fire at the current target with the selected profile."""
        if self.target_point is None:
            return None
        m = self.world.launch(self.profile, self.target_point,
                              tuple(self.waypoints))
        if m is not None:
            self.followed = m
            self._launch_puff(m.pos)
            self.app.audio.play("launch", pos=m.pos)
        return m

    def effective_time_scale(self) -> float:
        """Requested accel, forced to 1x while a launch is in EJECT/BOOST."""
        if launch_realtime_lock(self.world.missiles):
            return 1.0
        return self.controls.requested_scale

    # ------------------------------------------------------------ sim step

    def handle_event(self, ev) -> None:
        self.controls.handle_event(ev)

    def sim_step(self, dt: float) -> None:
        world = self.world
        prev = [(m, m.phase) for m in world.missiles]
        world.step(dt)
        self.tactical_map.record(world)     # map trails + tracked target
        live = {id(m) for m in world.missiles}

        self._missile_effects(world.missiles)
        for m, phase in prev:       # booster separation: BOOST -> ramjet
            if (phase in (PH_EJECT, PH_BOOST) and id(m) in live
                    and m.phase in RAMJET_PHASES):
                v = _vhat(m)
                self._boosters.append(_FallingBooster(
                    m.pos - v * BOOSTER_ATTACH_BACK, m.vel, v))
        for key in list(self._trails):      # finish trails of dead missiles
            if key not in live:
                self._trails.pop(key).finished = True

        for kind, pos in world.drain_events():
            if kind == "ship_hit":
                self.effects.explosion(pos, EXPLOSION_SCALE_SHIP,
                                       water=pos[1] < SHIP_HIT_SPLASH_MAX_Y)
                self.app.audio.boom(pos)
            elif kind == "splash":
                self.effects.splash(pos, scale=SPLASH_SCALE)
                self.app.audio.play("splash", pos=pos)
            else:                           # ground_hit
                self.effects.explosion(pos, EXPLOSION_SCALE_GROUND)
                self.app.audio.boom(pos)

        self._ship_fires(dt)
        self._update_boosters(dt)
        self._update_tel(dt)
        self.effects.update(dt)

    def _missile_effects(self, missiles) -> None:
        """Exhaust trail feed + plume emission for every live missile."""
        for m in missiles:
            key = id(m)
            trail = self._trails.get(key)
            if trail is None:
                trail = self._trails[key] = self.effects.add_trail()
            v = _vhat(m)
            tail = m.pos - v * MISSILE_HALF_LEN
            if m.phase == PH_BOOST:
                trail.add_point(tail)
                self.effects.booster_plume(m.pos - v * BOOSTER_TAIL_BACK,
                                           v, 1.0)
            elif m.phase in RAMJET_PHASES:
                trail.add_point(tail)
                if m.fuel > 0.0:
                    self.effects.fire.emit(
                        1, tail, 0.3, -v * RAMJET_EXHAUST_SPEED, 2.0,
                        RAMJET_FIRE_LIFE, RAMJET_FIRE_SIZE,
                        RAMJET_FIRE_COLORS, self.effects.rng)

    def _launch_puff(self, mouth_pos) -> None:
        """Cold-launch gas puff at the canister mouth (the eject is unlit)."""
        self.effects.smoke.emit(
            LAUNCH_PUFF_COUNT, mouth_pos, 1.2, (0.0, 4.0, 0.0), 3.0,
            (1.5, 3.0), (2.0, 9.0),
            ((0.85, 0.84, 0.82), (0.55, 0.55, 0.58)), self.effects.rng)

    def _ship_fires(self, dt: float) -> None:
        """Deck fire + smoke for burning/sinking ships near the camera."""
        eye = self.camera.eye
        for ship in self.world.ships:
            if ship.state not in (ST_BURNING, ST_SINKING):
                self._fire_acc.pop(ship.ship_id, None)
                continue
            sp = ship.pos
            dx = sp[0] - eye[0]
            dy = sp[1] - eye[1]
            dz = sp[2] - eye[2]
            if math.sqrt(dx * dx + dy * dy + dz * dz) > SHIP_FIRE_VIS_RANGE:
                continue
            acc = self._fire_acc.get(ship.ship_id, 0.0) + dt
            deck = ship.pos + _UP * (ship.height * SHIP_FIRE_DECK_FRAC)
            while acc >= SHIP_FIRE_PERIOD:
                acc -= SHIP_FIRE_PERIOD
                self.effects.ship_fire(deck)
            self._fire_acc[ship.ship_id] = acc

    def _update_boosters(self, dt: float) -> None:
        for b in self._boosters:
            b.update(dt)
        self._boosters = [
            b for b in self._boosters
            if not b.expired(max(self.world.terrain_height_at(
                float(b.pos[0]), float(b.pos[2])), 0.0))]

    def _update_tel(self, dt: float) -> None:
        """Swing the canisters up when armed, down while reloading."""
        target = 1.0 if self.world.launcher_armed else 0.0
        step = dt / TEL_ERECT_TIME
        delta = min(max(target - self._tel_frac, -step), step)
        self._tel_frac = min(max(self._tel_frac + delta, 0.0), 1.0)

    # ---------------------------------------------------------------- audio

    def _loop_sources(self) -> dict:
        """Per-missile engine loops for AudioManager.update_loops: booster
        roar through BOOST, ramjet hiss while the sustainer burns. Empty
        while paused (a frozen sim should not roar)."""
        if self.app.paused:
            return {}
        sources = {}
        for m in self.world.missiles:
            if m.phase == PH_BOOST:
                sources[id(m)] = ("booster", m.pos, BOOSTER_LOOP_GAIN)
            elif m.phase in RAMJET_PHASES and m.fuel > 0.0:
                sources[id(m)] = ("cruise", m.pos, CRUISE_LOOP_GAIN)
        return sources

    # ----------------------------------------------------------- state hooks

    def leave(self) -> None:
        """ESC to menu: silence the engine loops, release any mouse grab."""
        self.app.audio.stop_loops()
        self.controls.release_mouse()

    def dispose(self) -> None:
        """Free this session's GL objects (called when SANDBOX restarts)."""
        meshes = ([self._mesh_oniks, self._mesh_booster]
                  + list(self._ship_meshes.values()) + self._tel_meshes
                  + [mesh for mesh, _ in self._site_draws])
        for mesh in meshes:
            mesh.delete()
        self.terrain.delete()
        self.ocean.delete()
        self.sky.delete()
        self.particles.delete()
        self.tactical_map.delete()
        self.text.delete()

    # --------------------------------------------------------------- render

    def render(self, dt_real: float) -> None:
        self.controls.update(dt_real)            # free-cam flies in real time
        self.rig.update(dt_real, self.followed)
        audio = self.app.audio
        audio.set_listener(self.camera.eye)      # gains follow the camera
        audio.update_loops(self._loop_sources())
        w, h = self.window.size()
        self.renderer.begin(self.camera, w / h)
        self.sky.draw(self.renderer)
        self.terrain.draw(self.renderer)
        self.ocean.draw(self.renderer, self.camera, self.world.sim_time)
        for mesh, pos in self._site_draws:
            self.renderer.draw_mesh(mesh, pos)
        self._draw_ships()
        self._draw_tel()
        self._draw_missiles()
        self.particles.draw(self.renderer, self.effects)
        if self.map_open:
            self.tactical_map.update(dt_real)   # arrow-key panning
            self.tactical_map.draw(w, h)
        elif self.hud_visible:
            self.hud.draw(self, w, h)

    def _draw_ships(self) -> None:
        for ship in self.world.ships:
            if ship.state == ST_GONE:
                continue
            rot = rot_y(ship.heading) @ rot_z(ship.list_angle)
            self.renderer.draw_mesh(self._ship_meshes[ship.ship_type],
                                    ship.pos, rot)

    def _draw_tel(self) -> None:
        idx = int(round(self._tel_frac * (TEL_ELEV_STEPS - 1)))
        self.renderer.draw_mesh(self._tel_meshes[idx], self._tel_pos)

    def _draw_missiles(self) -> None:
        for m in self.world.missiles:
            v = _vhat(m)
            rot = math3d.rotation_from_forward(v)
            self.renderer.draw_mesh(self._mesh_oniks, m.pos, rot)
            if m.phase in (PH_EJECT, PH_BOOST):     # booster still attached
                self.renderer.draw_mesh(self._mesh_booster,
                                        m.pos - v * BOOSTER_ATTACH_BACK, rot)
        for b in self._boosters:
            self.renderer.draw_mesh(self._mesh_booster, b.pos, b.rot)
