# ONIKS Game Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ONIKS standalone missile game — a 600×600 km to-scale world where the player launches a P-800 Oniks from a coastal Bastion battery at moving ships and land targets — per the approved spec at `docs/superpowers/specs/2026-06-10-oniks-game-design.md`.

**Architecture:** float64 simulation + camera-relative float32 rendering (zero jitter at 600 km), OpenGL 3.3 core shader pipeline with logarithmic depth and atmospheric haze, ring-LOD ocean and per-feature LOD terrain, fixed-timestep (120 Hz) sim decoupled from render with 1×–16× time acceleration, data-driven weapon definitions, procedural numpy-built models.

**Tech Stack:** Python 3.11+, pygame-ce, PyOpenGL (3.3 core), numpy. No other runtime deps. pytest for tests.

**Project root (all paths relative to it):** `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO`

---

## LOCKED CONVENTIONS — read before any task

Every task must follow these. Deviating breaks other tasks.

- **Units:** SI. Meters, seconds, kilograms, radians (degrees only in UI text and config constants suffixed `_deg`).
- **Axes:** X = east, Y = up, Z = north. Heading `h` (radians): 0 = +Z (north), increasing clockwise seen from above. `forward(h) = np.array([sin(h), 0.0, cos(h)])`.
- **Precision:** ALL simulation state (positions, velocities) is `np.float64`. GPU data is `np.float32`, produced only at the render boundary after subtracting the camera eye.
- **Model space:** forward = +Z (nose/bow at max Z), up = +Y. Models built at real scale in meters, origin at the object's center of rotation (missile: mid-body; ship: waterline center; buildings: ground center).
- **Matrices:** numpy `(4,4)` arrays, standard math convention (translation in the last *column*, `M @ v_col`). Uploaded with `transpose=GL_TRUE` so GLSL sees the right thing: `glUniformMatrix4fv(loc, 1, GL_TRUE, m.astype(np.float32))`.
- **Mesh vertex layout:** interleaved float32 `[px py pz nx ny nz r g b]` (9 floats), `uint32` indices, attribute locations 0=pos, 1=normal, 2=color.
- **Common uniform names:** `u_proj`, `u_view_rot` (rotation-only view, eye at origin), `u_model` (camera-relative model matrix), `u_sun_dir` (unit, world space, pointing FROM scene TOWARD sun), `u_cam_alt` (camera altitude m), `u_time` (seconds, float32 wrapped at 3600), `u_log_depth_fcoef`. Haze: `u_haze_density`, `u_haze_color`, `u_sun_haze_color`.
- **Sun:** direction `normalize([0.35, 0.42, 0.55])`, warm white `(1.0, 0.96, 0.88)`, ambient via hemisphere term (in lit shader below).
- **World layout constants** (defined once in `world/generation.py`, imported everywhere):
  - `WORLD_HALF = 350_000.0` (drawable region ±350 km; playable ocean spans ~600 km north of base)
  - Home coastline wiggles around `z = 0`; land at `z < coast`, ocean at `z > coast`. Player base `BASE_POS = (0.0, cliff_top_y, -180.0)` on a ~55 m cliff.
  - Enemy coastline around `z = 500_000`, land at `z > enemy_coast`.
  - Islands between `z = 60_000` and `z = 420_000`.
- **Phase enum (missile):** module-level ints in `sim/missile.py`: `PH_EJECT, PH_BOOST, PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_TERMINAL, PH_DEAD = range(7)`.
- **Git:** commit after every task (or TDD cycle within a task). Conventional messages: `feat:`, `test:`, `fix:`, `perf:`.
- **Tests:** anything that imports OpenGL must NOT be imported by unit tests. Geometry/math/sim modules stay GL-free so pytest runs headless. `engine/mesh.py` separates `MeshBuilder` (pure numpy) from `Mesh` (GL upload) — tests import the builder only via `engine.meshdata`.

### File structure (final)

```
oinks PROTO/
  main.py                     entry: pygame init, GL window, state machine, fixed-timestep loop
  requirements.txt  pytest.ini  .gitignore  run_game.bat  README.md
  engine/__init__.py
  engine/math3d.py            projection/rotation/compose helpers (pure numpy)
  engine/window.py            pygame + 3.3 core context, resize, hidden-window option
  engine/shader.py            Shader class (compile/link/uniform cache)
  engine/meshdata.py          MeshBuilder + primitive generators (pure numpy, GL-free)
  engine/mesh.py              Mesh: VAO/VBO upload + draw (GL)
  engine/camera.py            Camera: float64 eye, basis vectors, view/proj (pure numpy)
  engine/renderer.py          lit-mesh shader, frame begin, draw_mesh, fog/sun uniforms, culling
  engine/particles.py         vectorized particle pools + ribbon trails (numpy sim, GL draw split)
  engine/text.py              font atlas (pygame.font -> GL texture), 2D draw, ortho overlay shader
  world/__init__.py
  world/generation.py         seeded noise, terrain_height, layout, lanes, sites (pure numpy)
  world/terrain.py            per-feature LOD meshes from heightfield (geometry pure; GL thin)
  world/ocean.py              ring-LOD grid + ocean shader (geometry pure; GL thin)
  world/sky.py                sky dome + shader
  world/world.py              WorldState: ships, sites, contacts update
  sim/__init__.py
  sim/physics.py              atmosphere (density, speed of sound), constants
  sim/arsenal.py              WeaponDef/LauncherDef dataclasses, ONIKS + BASTION definitions
  sim/guidance.py             PN, altitude hold, waypoint steering (pure functions)
  sim/missile.py              Missile: phase machine, point-mass integration
  sim/ships.py                Ship: route following, kinematics, damage states
  sim/damage.py               segment-vs-OBB hit test, warhead application
  sim/contacts.py             fuzzy delayed contact picture
  game/__init__.py
  game/states.py              GameState base + state machine + MenuState
  game/sandbox.py             SandboxState: wires sim+world+render+input
  game/cameras.py             chase/orbit/target/launcher/free controllers + transitions
  game/controls.py            key bindings, time accel, pause/frame-step
  game/hud.py                 telemetry overlay
  game/tactical_map.py        full-world map: zoom/pan, contacts, waypoints, launch
  game/audio.py               procedural sound synthesis + manager
  models/__init__.py
  models/common.py            PALETTE + shared part helpers
  models/oniks.py             build_oniks() -> MeshData parts
  models/bastion.py           build_bastion_tel()
  models/ships_models.py      build_cargo/build_tanker/build_warship
  models/structures.py        radar station, fuel depot, harbor
  tools/screenshot_harness.py scripted scenes -> renders/*.png
  tools/perf_harness.py       frame-time benchmark
  tests/                      pytest suite (GL-free)
  sounds/   renders/          (gitignored output ok; sounds generated at first run)
```

---

## Phase A — Scaffold & engine core

### Task 1: Project scaffold

**Files:** Create `requirements.txt`, `pytest.ini`, `.gitignore`, `run_game.bat`, `README.md`, empty `__init__.py` in `engine/ world/ sim/ game/ models/ tests/`.

- [ ] **Step 1: Write files**

`requirements.txt`:
```
pygame-ce>=2.4
PyOpenGL>=3.1.7
numpy>=1.26
```
`pytest.ini`:
```ini
[pytest]
testpaths = tests
addopts = -q
markers =
    slow: long-running sim tests
```
`.gitignore`:
```
__pycache__/
*.pyc
renders/
sounds/*.wav
.pytest_cache/
```
`run_game.bat`:
```bat
@echo off
cd /d "%~dp0"
python main.py
pause
```
`README.md`: title ONIKS, one-paragraph description, install (`pip install -r requirements.txt`), run (`python main.py` or `run_game.bat`), controls table (copy the Controls section at the end of this plan).

- [ ] **Step 2: Commit** `git add -A && git commit -m "feat: project scaffold"`

### Task 2: engine/math3d.py (TDD)

**Files:** Create `engine/math3d.py`, `tests/test_math3d.py`.

Functions (all take/return numpy arrays; angles radians):

```python
import numpy as np

def perspective(fov_y, aspect, near, far) -> np.ndarray  # (4,4) f64, standard GL perspective
def rotation_from_forward(forward, up=(0,1,0)) -> np.ndarray
    # (3,3) f64. Columns = object axes in world: col0=right, col1=up, col2=forward (model +Z maps to forward).
    # Gram-Schmidt: f = normalize(forward); r = normalize(cross(up, f)); u = cross(f, r).
    # If |cross(up, f)| < 1e-9 (looking straight up/down) use up=(0,0,1) fallback.
def compose(rotation3x3, translation3, scale=1.0) -> np.ndarray  # (4,4): R*s in upper-left, t in last column
def view_rotation(right, up, forward) -> np.ndarray
    # (4,4) camera rotation-only view matrix: rows = right, up, -forward (OpenGL looks down -Z)
def heading_to_forward(h) -> np.ndarray  # [sin h, 0, cos h]
def forward_to_heading(f) -> float       # atan2(f[0], f[2])
```

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
from engine.math3d import (perspective, rotation_from_forward, compose,
                           view_rotation, heading_to_forward, forward_to_heading)

def test_heading_roundtrip():
    for h in [0.0, 0.5, np.pi/2, np.pi, -2.3]:
        f = heading_to_forward(h)
        assert np.allclose(f[1], 0.0)
        assert np.isclose(np.mod(forward_to_heading(f) - h + np.pi, 2*np.pi) - np.pi, 0.0, atol=1e-12)

def test_rotation_from_forward_orthonormal():
    R = rotation_from_forward(np.array([1.0, 2.0, 3.0]))
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-12)
    # model +Z maps to normalized forward
    assert np.allclose(R @ np.array([0,0,1.0]), np.array([1,2,3])/np.linalg.norm([1,2,3]), atol=1e-12)

def test_rotation_from_forward_vertical_fallback():
    R = rotation_from_forward(np.array([0.0, 1.0, 0.0]))
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-9)

def test_compose_places_translation():
    M = compose(np.eye(3), np.array([10.0, 20.0, 30.0]))
    assert np.allclose(M[:3, 3], [10, 20, 30])
    assert np.allclose(M[3], [0, 0, 0, 1])

def test_perspective_maps_near_far():
    P = perspective(np.radians(60), 16/9, 1.0, 1000.0)
    near_clip = P @ np.array([0, 0, -1.0, 1.0])
    far_clip = P @ np.array([0, 0, -1000.0, 1.0])
    assert np.isclose(near_clip[2] / near_clip[3], -1.0)
    assert np.isclose(far_clip[2] / far_clip[3], 1.0)

def test_view_rotation_world_forward_maps_to_minus_z():
    f = np.array([0.0, 0.0, 1.0]); r = np.array([1.0, 0.0, 0.0]); u = np.array([0.0, 1.0, 0.0])
    V = view_rotation(r, u, f)
    v = V @ np.array([0, 0, 5.0, 1.0])   # point 5m north, camera facing north
    assert np.allclose(v[:3], [0, 0, -5.0])
```

- [ ] **Step 2: Run** `python -m pytest tests/test_math3d.py -v` — expect FAIL (module missing).
- [ ] **Step 3: Implement** all six functions exactly per the signatures above.
- [ ] **Step 4: Run again** — expect all PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: math3d core with tests"`

### Task 3: engine/meshdata.py — MeshBuilder (TDD, GL-free)

**Files:** Create `engine/meshdata.py`, `tests/test_meshdata.py`.

```python
class MeshData:        # plain container
    vertices: np.ndarray  # (N,9) float32: pos3 normal3 color3
    indices: np.ndarray   # (M,) uint32

class MeshBuilder:
    def __init__(self): ...           # accumulates vertices/indices lists
    def add_mesh(self, md: MeshData, offset=(0,0,0), rotation=None, scale=1.0): ...
    def build(self) -> MeshData

# primitive generators (module functions, all return MeshData):
def make_box(size_xyz, color, offset=(0,0,0)) -> MeshData          # flat normals (24 verts)
def make_cylinder(radius, length, segments, color, axis='z', offset=(0,0,0), cap_ends=True, smooth=True) -> MeshData
def make_lathe(profile, segments, color, smooth=True, offset=(0,0,0)) -> MeshData
    # profile: list[(z, radius)] revolved around +Z axis, ordered increasing z.
    # radius 0 entries create tip points. Smooth normals from adjacent profile slopes.
def make_wedge(size_xyz, color, offset=(0,0,0)) -> MeshData        # triangular prism, slope facing +Z
def make_fin(root_chord, tip_chord, span, sweep, thickness, color, offset=(0,0,0)) -> MeshData
    # flat trapezoidal plate in the X(span)/Z(chord) plane, thickness in Y, leading edge swept back by `sweep` m at tip
def make_grid(xs, zs, heights, colors) -> MeshData
    # heightfield grid: xs (W,), zs (H,), heights (H,W), colors (H,W,3); smooth normals via central differences
```

`add_mesh` applies `rotation` (3,3 float) to positions AND normals, then scale, then offset; reindexes.

- [ ] **Step 1: Write failing tests**

```python
import numpy as np
from engine.meshdata import (MeshBuilder, make_box, make_cylinder, make_lathe,
                             make_fin, make_grid)

def _check(md):
    assert md.vertices.dtype == np.float32 and md.indices.dtype == np.uint32
    assert md.indices.max() < len(md.vertices)
    assert np.isfinite(md.vertices).all()
    n = md.vertices[:, 3:6]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-3)

def test_box():
    md = make_box((2, 4, 6), (1, 0, 0))
    _check(md)
    assert len(md.vertices) == 24 and len(md.indices) == 36
    assert np.allclose(md.vertices[:, :3].min(axis=0), [-1, -2, -3])
    assert np.allclose(md.vertices[:, :3].max(axis=0), [1, 2, 3])

def test_lathe_cone():
    md = make_lathe([(0.0, 1.0), (2.0, 0.0)], 16, (0.5, 0.5, 0.5))
    _check(md)
    assert np.isclose(md.vertices[:, 2].max(), 2.0)          # tip at z=2
    r = np.linalg.norm(md.vertices[:, :2], axis=1)
    assert r.max() <= 1.0 + 1e-5

def test_cylinder_axis_z():
    md = make_cylinder(0.5, 4.0, 12, (0, 1, 0))
    _check(md)
    assert np.isclose(md.vertices[:, 2].max(), 2.0)          # centered: z in [-2, 2]
    assert np.isclose(md.vertices[:, 2].min(), -2.0)

def test_builder_merge_and_transform():
    b = MeshBuilder()
    b.add_mesh(make_box((1, 1, 1), (1, 1, 1)))
    Rz90 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
    b.add_mesh(make_box((1, 1, 1), (1, 1, 1)), offset=(5, 0, 0), rotation=Rz90)
    md = b.build()
    _check(md)
    assert len(md.vertices) == 48 and len(md.indices) == 72
    assert md.vertices[:, 0].max() > 4.0

def test_grid_heightfield():
    xs = np.linspace(0, 10, 6); zs = np.linspace(0, 10, 5)
    h = np.zeros((5, 6)); h[2, 3] = 4.0
    c = np.ones((5, 6, 3), dtype=np.float32) * 0.5
    md = make_grid(xs, zs, h, c)
    _check(md)
    assert len(md.vertices) == 30 and len(md.indices) == 5 * 4 * 6  # (5-1)*(6-1)*2 tris * 3
```

- [ ] **Step 2: Run** — expect FAIL. **Step 3: Implement.** **Step 4: Run** — PASS. **Step 5: Commit** `feat: procedural mesh builder`.

### Task 4: engine/window.py + engine/shader.py + engine/mesh.py (GL layer)

**Files:** Create `engine/window.py`, `engine/shader.py`, `engine/mesh.py`. No unit tests (GL); verified by Task 9's screenshot harness.

`window.py`:
```python
class Window:
    def __init__(self, width=1600, height=900, title="ONIKS", hidden=False):
        # pygame.init(); set GL attribs BEFORE set_mode:
        # CONTEXT_MAJOR/MINOR 3/3, CONTEXT_PROFILE_MASK = GL_CONTEXT_PROFILE_CORE,
        # DOUBLEBUFFER 1, DEPTH_SIZE 24, MULTISAMPLEBUFFERS 1, MULTISAMPLESAMPLES 4
        # flags = OPENGL | DOUBLEBUF | (HIDDEN if hidden else RESIZABLE)
        # then glEnable(GL_DEPTH_TEST), glEnable(GL_CULL_FACE), glEnable(GL_MULTISAMPLE)
    def swap(self): pygame.display.flip()
    def size(self) -> (w, h)
    def read_pixels_to_surface(self) -> pygame.Surface   # glReadPixels RGB, flip vertically
```

`shader.py`:
```python
class Shader:
    def __init__(self, vert_src: str, frag_src: str)   # compile, link, raise RuntimeError with info log on failure
    def use(self)
    def set_mat4(self, name, m)      # glUniformMatrix4fv(loc, 1, GL_TRUE, np.ascontiguousarray(m, np.float32))
    def set_vec3(self, name, v); def set_vec2(self, name, v)
    def set_float(self, name, x); def set_int(self, name, i)
    # uniform locations cached in a dict; unknown names silently ignored (loc -1)
```

`mesh.py`:
```python
class Mesh:
    def __init__(self, md: MeshData)  # VAO + interleaved VBO + EBO; attribs 0,1,2 with stride 36
    def draw(self)                    # glBindVertexArray + glDrawElements
    def delete(self)
```

- [ ] **Step 1: Implement all three files.**
- [ ] **Step 2: Smoke check (no assert):** `python -c "import engine.window, engine.shader, engine.mesh"` — imports OK (GL functions not called at import time).
- [ ] **Step 3: Commit** `feat: GL window, shader, mesh upload`.

### Task 5: engine/camera.py (TDD)

**Files:** Create `engine/camera.py`, `tests/test_camera.py`.

```python
class Camera:
    def __init__(self, fov_y_deg=62.0, near=0.5, far=900_000.0):
        self.eye = np.zeros(3, dtype=np.float64)   # float64 ALWAYS
        self.forward = np.array([0.0, 0.0, 1.0]); self.up = np.array([0.0, 1.0, 0.0])
    def set_look(self, eye_f64, target_f64): ...   # recompute forward/right/up
    def set_orientation(self, forward, up=(0,1,0)): ...
    @property
    def right(self): ...
    def view_rot(self) -> np.ndarray      # (4,4) rotation-only view via math3d.view_rotation
    def proj(self, aspect) -> np.ndarray  # math3d.perspective
    def rel(self, pos_f64) -> np.ndarray  # (pos - self.eye) as float64 -> caller casts f32
```

- [ ] **Step 1: Failing tests**

```python
import numpy as np
from engine.camera import Camera

def test_rel_subtracts_in_float64():
    c = Camera(); c.eye = np.array([500_000.0, 10.0, 500_000.0])
    r = c.rel(np.array([500_000.5, 10.0, 500_000.25]))
    assert r.dtype == np.float64
    assert np.allclose(r, [0.5, 0.0, 0.25], atol=1e-9)   # would fail in float32

def test_set_look_basis():
    c = Camera()
    c.set_look(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 10.0]))
    assert np.allclose(c.forward, [0, 0, 1])
    assert np.allclose(c.right, [1, 0, 0])
    V = c.view_rot()
    assert np.allclose((V @ np.array([0, 0, 1.0, 0]))[:3], [0, 0, -1], atol=1e-12)
```

- [ ] **Steps 2-4: fail → implement → pass.** **Step 5: Commit** `feat: float64 camera`.

### Task 6: engine/renderer.py + core shaders

**Files:** Create `engine/renderer.py`. Visual verification in Task 9.

GLSL (module-level strings). **Lit mesh vertex shader:**
```glsl
#version 330 core
layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_nrm; layout(location=2) in vec3 a_col;
uniform mat4 u_proj, u_view_rot, u_model;
uniform float u_log_depth_fcoef;
out vec3 v_nrm; out vec3 v_col; out vec3 v_view_vec;
void main(){
    vec4 world_rel = u_model * vec4(a_pos, 1.0);      // camera-relative world
    v_view_vec = world_rel.xyz;
    v_nrm = mat3(u_model) * a_nrm;
    v_col = a_col;
    gl_Position = u_proj * u_view_rot * world_rel;
    gl_Position.z = (log2(max(1e-6, 1.0 + gl_Position.w)) * u_log_depth_fcoef - 1.0) * gl_Position.w;
}
```
**Lit mesh fragment shader:**
```glsl
#version 330 core
in vec3 v_nrm; in vec3 v_col; in vec3 v_view_vec;
uniform vec3 u_sun_dir, u_sun_color;
uniform vec3 u_haze_color, u_sun_haze_color; uniform float u_haze_density, u_cam_alt;
out vec4 frag;
vec3 apply_haze(vec3 color, vec3 view_vec, float cam_alt){
    float dist = length(view_vec);
    float h = max(cam_alt + view_vec.y * 0.5, 0.0);
    float density = u_haze_density * exp(-h / 6000.0);
    float f = 1.0 - exp(-density * dist);
    vec3 dir = view_vec / max(dist, 1.0);
    float sun_amt = pow(max(dot(dir, u_sun_dir), 0.0), 8.0);
    return mix(color, mix(u_haze_color, u_sun_haze_color, sun_amt), f);
}
void main(){
    vec3 n = normalize(v_nrm);
    float ndl = max(dot(n, u_sun_dir), 0.0);
    vec3 hemi = mix(vec3(0.18,0.16,0.14), vec3(0.35,0.42,0.52), n.y*0.5+0.5);
    vec3 v = normalize(-v_view_vec);
    vec3 hv = normalize(v + u_sun_dir);
    float spec = pow(max(dot(n, hv), 0.0), 48.0) * 0.25;
    vec3 col = v_col * (u_sun_color * ndl + hemi) + u_sun_color * spec * step(0.01, ndl);
    frag = vec4(apply_haze(col, v_view_vec, u_cam_alt), 1.0);
}
```

```python
SUN_DIR = normalize([0.35, 0.42, 0.55]); SUN_COLOR = (1.0, 0.96, 0.88)
HAZE_DENSITY = 2.5e-5
HAZE_COLOR = (0.62, 0.70, 0.80); SUN_HAZE_COLOR = (0.95, 0.86, 0.72)

class Renderer:
    def __init__(self): ...  # build lit Shader, store far=900_000, fcoef = 2.0/log2(far+1.0)
    def begin(self, camera, aspect):
        # glClearColor to haze color; clear; store camera; compute proj/view_rot once
    def set_common(self, shader):   # sets u_proj u_view_rot u_sun_* u_haze_* u_cam_alt u_log_depth_fcoef
    def draw_mesh(self, mesh, pos_f64, rot3x3=None, scale=1.0):
        # cull: rel = cam.rel(pos); skip if dist > 700_000 or behind camera beyond object bound
        # u_model = compose(rot, rel_f32, scale); mesh.draw()
```

- [ ] **Step 1: Implement.** **Step 2: Commit** `feat: renderer with lit shader, log depth, haze`.

### Task 7: world/generation.py (TDD) — the world itself

**Files:** Create `world/generation.py`, `tests/test_generation.py`.

Deterministic, vectorized, no `random` module — integer hash noise:

```python
SEED = 1337
WORLD_HALF = 350_000.0
ENEMY_COAST_Z = 500_000.0     # note: beyond WORLD_HALF in z; drawable band z in [-40_000, 560_000]

def _hash01(ix, iz, seed):
    # ix, iz int64 arrays -> uniform [0,1) float64
    h = (ix.astype(np.int64) * 374761393 + iz.astype(np.int64) * 668265263 + seed * 982451653) & 0x7FFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0x7FFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0x1000000)

def value_noise(x, z, cell, seed):    # bilinear-interpolated lattice noise, smoothstep weights
def fbm(x, z, cell, octaves, seed, gain=0.5, lacunarity=2.0)  # standard fractal sum, normalized to [0,1]

ISLANDS = [  # (cx, cz, radius_m, peak_m) — hand-placed, ~9 islands
    (-38_000, 95_000, 9_000, 220), (52_000, 140_000, 14_000, 380), (-120_000, 180_000, 7_000, 150),
    (18_000, 235_000, 11_000, 290), (140_000, 260_000, 16_000, 430), (-65_000, 310_000, 8_000, 180),
    (95_000, 355_000, 6_000, 120), (-150_000, 90_000, 5_000, 90), (-20_000, 405_000, 10_000, 240),
]

def terrain_height(x, z):   # vectorized float64; THE single source of truth
    # home continent: coast = 2500*fbm(x,0,30_000,4,SEED+1) wiggle; land rises south of it
    #   h_home = ramp((coast - z)/4000) * (55 + 90*fbm(x,z,8_000,4,SEED+2))  -> cliffs ~55-145m
    # enemy continent: mirrored at ENEMY_COAST_Z rising north
    # islands: for each, radial falloff mask smoothstep(1 - dist/radius) ** 1.5 * (peak * (0.4 + 0.6*fbm(...)))
    # ocean floor: -60 - 80*fbm  (anything < 0 is underwater; ocean rendered at y=0)
    # return maximum of contributions (land) where land, else ocean floor (negative)

def is_land(x, z): return terrain_height(x, z) > 0.0

LANES = [...]    # 4 polylines (lists of (x, z) float64) crossing the ocean between map edges,
                 # hand-placed to dodge ISLANDS by >= 12 km
SITES = [        # dicts: {id, kind, pos(x,z), name}
    {"id":"radar_alpha", "kind":"radar", "pos":(52_000+2_500, 140_000-3_000), "name":"RADAR STN ALPHA"},
    {"id":"depot_bravo", "kind":"depot", "pos":(140_000-4_000, 260_000+2_000), "name":"FUEL DEPOT BRAVO"},
    {"id":"harbor_kilo", "kind":"harbor", "pos":(30_000, 502_000), "name":"HARBOR KILO"},
]
BASE_POS = ...   # (0.0, terrain_height(0,-600)+0m, -600.0) — picked so it's on home land, cliff top
SHIP_SPAWNS = [...]  # 14 entries: {ship_type: "cargo"|"tanker"|"warship", lane_index, lane_t0 (0..1), speed}
```

- [ ] **Step 1: Failing tests**

```python
import numpy as np
from world import generation as G

def test_deterministic():
    x = np.linspace(-300_000, 300_000, 500); z = np.linspace(-10_000, 550_000, 500)
    a = G.terrain_height(x, z); b = G.terrain_height(x, z)
    assert np.array_equal(a, b)

def test_base_on_land_and_high():
    h = G.terrain_height(np.array([G.BASE_POS[0]]), np.array([G.BASE_POS[2]]))[0]
    assert h > 30.0

def test_islands_have_land_and_ocean_between():
    for cx, cz, r, peak in G.ISLANDS:
        assert G.terrain_height(np.array([cx]), np.array([cz]))[0] > 20.0
    assert G.terrain_height(np.array([0.0]), np.array([150_000.0]))[0] < 0.0  # open ocean point

def test_lanes_stay_in_water():
    for lane in G.LANES:
        pts = np.array(lane)
        # sample densely along each segment
        for i in range(len(pts) - 1):
            t = np.linspace(0, 1, 50)[:, None]
            p = pts[i] * (1 - t) + pts[i+1] * t
            h = G.terrain_height(p[:, 0], p[:, 1])
            assert (h < -5.0).all(), f"lane {lane} touches land"

def test_sites_on_land():
    for s in G.SITES:
        h = G.terrain_height(np.array([s["pos"][0]]), np.array([s["pos"][1]]))[0]
        assert h > 5.0

def test_height_continuity():
    x = np.linspace(-50_000, 50_000, 2000); z = np.full(2000, 100_000.0)
    h = G.terrain_height(x, z)
    assert np.abs(np.diff(h)).max() < 30.0   # no cliffs from hashing artifacts at 50m sampling
```

- [ ] **Steps 2-4: fail → implement → pass.** Hand-tune `ISLANDS`/`LANES`/`SITES` constants until tests pass. **Step 5: Commit** `feat: deterministic 600km world generation`.

### Task 8: world/ocean.py + world/sky.py + world/terrain.py

**Files:** Create `world/ocean.py`, `world/sky.py`, `world/terrain.py`, `tests/test_world_geometry.py`.

**Ocean (ring-LOD):** pure function + GL wrapper.
```python
RINGS = [  # (outer_radius_m, cell_m, wave_weight)
    (2_000, 16, 1.0), (8_000, 64, 1.0), (32_000, 256, 0.0), (130_000, 1_500, 0.0), (700_000, 12_000, 0.0),
]
def build_ocean_rings() -> list[MeshData]
    # ring 0: full grid disk radius 2000 at 16m cells. ring n: square annulus [r_{n-1}-2*cell, r_n].
    # vertices y=0; color unused (ocean shader colors); store wave_weight in the color.r channel.
class Ocean:  # GL: builds Meshes once; draw(renderer, camera, time):
    # model translation = camera xz snapped to ring cell:  sx = floor(cam.x/cell)*cell (per ring, its own cell)
    # u_cam_offset = vec2(camera.eye.x - sx... ) NO — simpler: u_world_origin = vec2(sx, sz) passed to shader,
    # vertex world xz = a_pos.xz + u_world_origin; wave phase computed from world xz so waves don't swim.
```
**Ocean vertex shader** (displace + analytic normal):
```glsl
// inputs as lit shader; uniform vec2 u_world_origin; uniform float u_time;
// vec2 wxz = a_pos.xz + u_world_origin;
// float ww = a_col.r;   // wave weight
// 3 directional sines: dirs (0.78,0.62),( -0.45,0.89),(0.95,-0.31); freqs 2π/22m, 2π/59m, 2π/13m;
// amps 0.35, 0.55, 0.18 m; speeds 4.0, 6.5, 3.1 m/s
// y = ww * Σ amp*sin(dot(dir,wxz)*freq + u_time*speed*freq)
// normal = normalize(vec3(-ww*Σ amp*freq*dir.x*cos(...), 1, -ww*Σ amp*freq*dir.z*cos(...)))
// v_view_vec = displaced camera-relative pos (a_pos.xz - (cam.eye.xz - u_world_origin), y - cam.eye.y) — build via u_model as usual with displacement added.
```
**Ocean fragment:** deep water base `(0.045, 0.14, 0.21)`, fresnel `pow(1-max(dot(n,v),0),5)` mixing toward haze color, Blinn specular `pow(.., 600.0) * 1.2` sun glint, then `apply_haze`. Alpha 1.

**Sky:** icosphere or UV dome radius 800_000 centered on camera, drawn FIRST with `glDepthMask(GL_FALSE)`, no log-depth needed but harmless. Fragment: `mix(horizon (0.70,0.78,0.86), zenith (0.18,0.38,0.62), pow(max(dir.y,0),0.45))`, sun disc: `smoothstep(0.9996,0.9999,dot(dir,sun))` white, plus glow `pow(max(dot(dir,sun),0),32)*0.25*sunhazecolor`.

**Terrain:** per-feature static meshes.
```python
FEATURES = [  # (name, x0, x1, z0, z1) bounding rects
    ("home", -340_000, 340_000, -40_000, 12_000),
    ("enemy", -340_000, 340_000, 488_000, 560_000),
] + one per island: (island_i, cx±(r*2.2), cz±(r*2.2))
LODS = [(60.0, 30_000), (300.0, 130_000), (1200.0, 1e12)]  # (cell_m, max_draw_dist)
def build_feature_mesh(rect, cell) -> MeshData
    # sample terrain_height on grid; skip building if rect entirely ocean;
    # clamp heights < -4 to -4 (hidden under ocean); vertex colors by height/slope:
    #   sand (0.62,0.56,0.42) below 6m; grass-scrub (0.35,0.40,0.26) ; rock (0.46,0.42,0.38) by slope>0.5; 
    #   high rock (0.52,0.50,0.48) above 60% of local max
class Terrain:  # GL wrapper: builds all features × LODs once at load (~report vertex totals), draw() picks LOD by distance from camera to rect center, skips if > max_draw_dist or frustum-out (sphere test)
```

- [ ] **Step 1: Failing tests** (geometry only)

```python
import numpy as np
from world.ocean import build_ocean_rings, RINGS
from world.terrain import build_feature_mesh

def test_ocean_rings_flat_and_finite():
    rings = build_ocean_rings()
    assert len(rings) == len(RINGS)
    for md in rings:
        assert np.isfinite(md.vertices).all()
        assert np.allclose(md.vertices[:, 1], 0.0)
    # inner disk fine, outer ring reaches 700 km
    assert np.linalg.norm(rings[-1].vertices[:, [0, 2]], axis=1).max() >= 690_000

def test_ocean_vertex_budget():
    total = sum(len(md.vertices) for md in build_ocean_rings())
    assert total < 400_000

def test_feature_mesh_island():
    md = build_feature_mesh((-38_000-20_000, -38_000+20_000, 95_000-20_000, 95_000+20_000), 300.0)
    assert md is not None
    assert md.vertices[:, 1].max() > 100.0       # island peak present
    assert md.vertices[:, 1].min() >= -4.01      # clamped
```

- [ ] **Steps 2-4: fail → implement → pass.** **Step 5: Commit** `feat: ring-LOD ocean, sky dome, LOD terrain`.

### Task 9: main.py walking skeleton + screenshot harness — MILESTONE 1

**Files:** Create `main.py`, `game/controls.py` (free-cam part), `game/cameras.py` (FreeCam only for now), `tools/screenshot_harness.py`.

`main.py` — THE loop (this exact structure stays for the whole game):
```python
PHYS_DT = 1.0 / 120.0
class App:
    def __init__(self, hidden=False):
        self.window = Window(hidden=hidden); self.renderer = Renderer()
        self.state = SandboxState(...)   # for now: a stub WorldView state with sky/ocean/terrain + free cam
    def run(self):
        clock = pygame.time.Clock(); acc = 0.0; self.time_scale = 1.0
        while running:
            dt_real = min(clock.tick() / 1000.0, 0.1)
            for ev in pygame.event.get(): self.state.handle_event(ev)
            if not paused:
                acc += dt_real * self.time_scale
                steps = 0
                while acc >= PHYS_DT and steps < 64:
                    self.state.sim_step(PHYS_DT); acc -= PHYS_DT; steps += 1
                if steps == 64: acc = 0.0   # overload: drop time, never spiral
            self.state.render(dt_real)
            self.window.swap()
```
Free camera: WASD move, QE down/up, mouse look (right-drag or captured), SHIFT ×40 speed, CTRL+SHIFT ×400 (base 60 m/s — tiers 60 / 2_400 / 24_000 m/s to cross the map). Start position: 200 m above `BASE_POS` looking north over the ocean.

`tools/screenshot_harness.py`:
```python
# usage: python -m tools.screenshot_harness [scene ...]   (default: all)
# Creates App(hidden=True) at 1600x900, sets up the named scene, steps sim N times, renders ONE frame,
# saves renders/<scene>.png via window.read_pixels_to_surface() + pygame.image.save. Prints saved paths.
SCENES = {"overview": ..., "coast": ..., "ocean_low": ...}   # grows in later tasks
# overview: cam 3000m above base looking north (whole bay in view)
# coast: cam 80m alt 2km offshore looking back at the cliffs
# ocean_low: cam 8m above water mid-ocean looking at sun direction (wave/glint check)
```

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Run** `python -m tools.screenshot_harness` → expect 3 PNGs in `renders/`. **VISUAL REVIEW GATE:** the implementing agent must read the PNGs and confirm: horizon line is crisp, haze fades distant water into sky, waves visible near camera with sun glint, terrain cliffs visible with color zones, no z-fighting, no jitter artifacts. Iterate shader constants until convincing.
- [ ] **Step 3: Run** `python main.py` briefly (windowed) — confirm stable interactive FPS (press ESC to quit; print avg FPS on exit).
- [ ] **Step 4: Commit** `feat: walking skeleton - flyable 600km ocean world` (commit the renders too).

## Phase B — Simulation core (all GL-free, heavy TDD)

### Task 10: sim/physics.py + sim/arsenal.py (TDD)

**Files:** Create `sim/physics.py`, `sim/arsenal.py`, `tests/test_physics.py`, `tests/test_arsenal.py`.

`physics.py`:
```python
GRAVITY = 9.81
RHO0 = 1.225
def air_density(alt_m): return RHO0 * np.exp(-np.maximum(alt_m, 0.0) / 8500.0)
def speed_of_sound(alt_m):
    a = np.where(alt_m < 11_000.0, 340.3 - 0.0039 * np.maximum(alt_m, 0.0), 295.1)
    return a
def mach(speed, alt_m): return speed / speed_of_sound(alt_m)
def drag_force(speed, alt_m, cd, ref_area): return 0.5 * air_density(alt_m) * speed**2 * cd * ref_area
def cd_from_mach(m):   # simple supersonic missile curve
    # 0.30 below M0.8; linear rise to 0.85 at M1.05; decay to 0.32 by M2.0; 0.30 above
```

`arsenal.py`:
```python
@dataclass(frozen=True)
class WeaponDef:
    weapon_id: str; display_name: str
    length: float; diameter: float; launch_mass: float; fuel_mass: float
    eject_speed: float; eject_time: float
    booster_thrust: float; booster_time: float
    max_thrust: float; isp: float
    cruise_mach_hi: float; cruise_alt_hi: float; cruise_mach_lo: float; lo_alt: float
    skim_alt: float; terminal_range: float
    seeker_range: float; seeker_half_angle_deg: float
    max_g: float; warhead_mass: float
    ref_area: float

ONIKS = WeaponDef(
    weapon_id="oniks", display_name="P-800 Oniks",
    length=8.9, diameter=0.67, launch_mass=3000.0, fuel_mass=780.0,
    eject_speed=30.0, eject_time=0.9,
    booster_thrust=410_000.0, booster_time=3.2,
    max_thrust=110_000.0, isp=1100.0,
    cruise_mach_hi=2.55, cruise_alt_hi=14_000.0, cruise_mach_lo=2.0, lo_alt=60.0,
    skim_alt=12.0, terminal_range=42_000.0,
    seeker_range=50_000.0, seeker_half_angle_deg=32.0,
    max_g=11.0, warhead_mass=250.0,
    ref_area=0.3526,   # pi * (0.67/2)^2
)
@dataclass(frozen=True)
class LauncherDef: launcher_id: str; display_name: str; weapon_ids: tuple; reload_s: float
BASTION = LauncherDef("bastion", "Bastion-P TEL", ("oniks",), 18.0)
WEAPONS = {"oniks": ONIKS}; LAUNCHERS = {"bastion": BASTION}
```

- [ ] **Step 1: Failing tests**

```python
import numpy as np
from sim import physics as P
from sim.arsenal import ONIKS, WEAPONS

def test_density_falls():
    assert P.air_density(0.0) == 1.225
    assert P.air_density(14_000) < 0.3 * P.air_density(0.0)

def test_speed_of_sound_profile():
    assert 339 < P.speed_of_sound(0.0) <= 341
    assert np.isclose(P.speed_of_sound(20_000), 295.1)

def test_cd_curve_shape():
    assert P.cd_from_mach(0.5) < P.cd_from_mach(1.05)
    assert P.cd_from_mach(1.05) > P.cd_from_mach(2.0)

def test_oniks_definition_sane():
    assert ONIKS.launch_mass > ONIKS.fuel_mass + ONIKS.warhead_mass
    assert ONIKS.cruise_alt_hi > 10_000 and ONIKS.skim_alt < 20
    assert "oniks" in WEAPONS
```

- [ ] **Steps 2-4 → pass.** **Step 5: Commit** `feat: atmosphere model and Oniks definition`.

### Task 11: sim/guidance.py (TDD) — PN, altitude hold, waypoints

**Files:** Create `sim/guidance.py`, `tests/test_guidance.py`.

```python
def pn_accel(mis_pos, mis_vel, tgt_pos, tgt_vel, n_gain=4.0):
    """True 3D proportional navigation. Returns commanded accel (3,) float64,
    perpendicular component only (drop any along-velocity component)."""
    r = tgt_pos - mis_pos
    v_rel = tgt_vel - mis_vel
    r2 = float(r @ r)
    if r2 < 1.0: return np.zeros(3)
    omega = np.cross(r, v_rel) / r2
    a = n_gain * np.cross(v_rel, omega)
    a = -a                      # sign: v_rel is target-relative; verify with the head-on test below
    vhat = mis_vel / max(np.linalg.norm(mis_vel), 1e-9)
    return a - vhat * (a @ vhat)

def altitude_hold_accel(alt, vspeed, target_alt, kp=0.35, kd=1.1, max_a=35.0):
    """PD vertical accel command (positive = up), gravity NOT included."""
    return float(np.clip(kp * (target_alt - alt) - kd * vspeed, -max_a, max_a))

def steer_heading_accel(vel, desired_heading, gain=2.2, max_a=60.0):
    """Horizontal accel perpendicular to velocity that turns current heading toward desired."""
    # err = wrapped angle difference; a_lat = clip(gain * err * horiz_speed, ±max_a); direction = left/right normal of vel

def waypoint_reached(pos, wp, radius=2_500.0) -> bool   # horizontal distance test
```

- [ ] **Step 1: Failing tests** (the PN intercept test is the heart of the game — do not weaken it)

```python
import numpy as np
from sim.guidance import pn_accel, altitude_hold_accel, steer_heading_accel

def _fly_pn(mis_pos, mis_vel, tgt_pos, tgt_vel, t_max=120.0, dt=1/120):
    """Integrate a PN-guided point at constant speed; return min miss distance."""
    mis_pos, mis_vel = mis_pos.copy(), mis_vel.copy()
    speed = np.linalg.norm(mis_vel); best = 1e18
    for _ in range(int(t_max / dt)):
        a = pn_accel(mis_pos, mis_vel, tgt_pos, tgt_vel)
        a = np.clip(a, -110.0, 110.0)             # ~11 g
        mis_vel = mis_vel + a * dt
        mis_vel *= speed / np.linalg.norm(mis_vel)  # constant speed
        mis_pos = mis_pos + mis_vel * dt
        tgt_pos = tgt_pos + tgt_vel * dt
        best = min(best, float(np.linalg.norm(tgt_pos - mis_pos)))
        if best < 3.0: break
    return best

def test_pn_hits_crossing_ship():
    miss = _fly_pn(np.array([0., 12., 0.]), np.array([0., 0., 680.]),
                   np.array([3_000., 8., 30_000.]), np.array([-9., 0., 0.]))
    assert miss < 8.0

def test_pn_hits_fast_crossing_target():
    miss = _fly_pn(np.array([0., 12., 0.]), np.array([0., 0., 680.]),
                   np.array([-5_000., 8., 25_000.]), np.array([14., 0., -6.]))
    assert miss < 8.0

def test_pn_head_on_stays_stable():
    miss = _fly_pn(np.array([0., 12., 0.]), np.array([0., 0., 680.]),
                   np.array([0., 8., 40_000.]), np.array([0., 0., -10.]))
    assert miss < 8.0

def test_pn_accel_perpendicular_to_velocity():
    a = pn_accel(np.zeros(3), np.array([0., 0., 600.]), np.array([5_000., 0., 20_000.]), np.array([-8., 0., 0.]))
    assert abs(a @ np.array([0., 0., 1.])) < 1e-9

def test_altitude_hold_converges():
    alt, vs = 300.0, 0.0
    for _ in range(120 * 60):
        a = altitude_hold_accel(alt, vs, 12.0)
        vs += a * (1/120); alt += vs * (1/120)
    assert abs(alt - 12.0) < 1.0 and abs(vs) < 0.5

def test_steer_heading_turns_correct_way():
    vel = np.array([0., 0., 600.])             # heading 0 (north)
    a = steer_heading_accel(vel, np.radians(20))   # want to turn east
    assert a[0] > 1.0 and abs(a[2]) < abs(a[0])    # accel points east-ish
```

- [ ] **Steps 2-4: fail → implement → pass.** If a PN sign is wrong, the head-on/crossing tests catch it — fix the sign, don't loosen tolerances. **Step 5: Commit** `feat: PN guidance, altitude hold, steering`.

### Task 12: sim/missile.py (TDD) — the Oniks flight

**Files:** Create `sim/missile.py`, `tests/test_missile.py`.

```python
class Missile:
    def __init__(self, weapon: WeaponDef, pos_f64, heading, profile, target_point, waypoints=(), target_ship=None):
        # profile in ("hi-lo", "lo-lo"); target_point np(3,) f64 (sea-level aim point from the map);
        # waypoints tuple of (x, z); target_ship: Ship or None (seeker refines at terminal)
        self.pos, self.vel = pos_f64.copy(), np.zeros(3)
        self.phase = PH_EJECT; self.t = 0.0; self.fuel = weapon.fuel_mass
        self.route = list of (x,z): waypoints + final = target_point.xz
        self.locked_ship = None; self.alive = True; self.impact_pos = None
    @property
    def mass(self): return self.weapon.launch_mass - (self.weapon.fuel_mass - self.fuel)
    def update(self, dt, world):   # world gives ships list for seeker; called at PHYS_DT
```
Phase machine in `update` (each frame: compute accel = thrust/m * vhat + guidance + gravity − drag/m * vhat; semi-implicit Euler: `vel += a*dt; pos += vel*dt`):
- `PH_EJECT` (t < eject_time): vel starts `[0, eject_speed, 0]`; only gravity. No thrust. At `t >= eject_time` → `PH_BOOST`.
- `PH_BOOST`: thrust = `booster_thrust` along vhat (initially up). Pitch-over: steer velocity toward `tilt_dir` = climb direction toward first route point — rotate vhat by up to 40°/s toward target tilt (hi-lo: 38° elevation; lo-lo: 25°). After `booster_time` → `PH_CLIMB` (hi-lo) or `PH_CRUISE` (lo-lo).
- `PH_CLIMB` (hi-lo): sustainer ON (speed controller below), guidance = steer_heading toward current route point + altitude_hold toward `cruise_alt_hi`. When within 92% of cruise alt → `PH_CRUISE`.
- `PH_CRUISE`: hold `cruise_alt` (hi: cruise_alt_hi, lo: lo_alt) and route-follow; pop waypoints with `waypoint_reached`. Speed controller: PI on mach error → thrust in [0, max_thrust]: `thrust = clip(kp_t * (target_mach - mach) * 4e5 + drag_feedforward, 0, max_thrust)`, drag_feedforward = current drag force. Fuel: `fuel -= thrust / (isp * 9.81) * dt`; thrust = 0 when fuel <= 0 (missile decelerates, sinks, dies on water hit).
  - hi-lo: when horizontal distance to target < `descent_range` → `PH_DESCENT`. `descent_range = (cruise_alt_hi - skim_alt) / tan(9°) + terminal_range * 0.4` (≈ 105 km — gets it level before terminal).
- `PH_DESCENT`: altitude_hold toward skim_alt with steeper gains (kp 0.08 but target ramped down at 220 m/s descent rate: `target = max(skim_alt, alt - 220*dt_total_since)` — implement simply: altitude_hold(alt, vs, skim_alt, kp=0.012, kd=0.35) producing a shallow dive, clamp vertical speed ≥ -260). When alt < skim_alt*4 → `PH_TERMINAL`.
- `PH_TERMINAL`: seeker: if `locked_ship is None`: scan world.ships — pick nearest ship within `seeker_range` AND within `seeker_half_angle_deg` of velocity direction AND alive; once locked stays locked. If locked: `pn_accel` horizontal + altitude_hold(skim_alt) vertical; final 800 m: full 3D PN at the ship hull point. If never locked: continue to `target_point`.
- Impact: every update, if `pos[1] <= terrain_height_at(pos)` or `pos[1] <= 0` over water → die (splash, `impact_pos` set). Ship hits are detected by `sim/damage.py` (Task 13) via segment test — missile exposes `prev_pos`.
- G-limit: clamp total guidance accel magnitude to `max_g * 9.81`.

- [ ] **Step 1: Failing tests**

```python
import numpy as np, pytest
from sim.missile import Missile, PH_EJECT, PH_BOOST, PH_CRUISE, PH_TERMINAL, PH_DEAD
from sim.arsenal import ONIKS

DT = 1/120
class _World:  # minimal stub
    ships = []
    def terrain_height_at(self, x, z): return -50.0  # open ocean

def _launch(profile="hi-lo", target=(0., 0., 200_000.)):
    m = Missile(ONIKS, np.array([0., 60., 0.]), heading=0.0, profile=profile,
                target_point=np.array(target))
    return m

def test_cold_launch_goes_straight_up():
    m = _launch(); w = _World()
    for _ in range(int(0.8 / DT)): m.update(DT, w)
    assert m.phase == PH_EJECT
    assert m.pos[1] > 60.0 and abs(m.pos[0]) < 0.5 and abs(m.pos[2]) < 0.5

def test_booster_ignites_and_climbs():
    m = _launch(); w = _World()
    for _ in range(int(3.5 / DT)): m.update(DT, w)
    assert m.phase != PH_EJECT
    assert m.vel[1] > 50.0                      # climbing hard
    assert np.linalg.norm(m.vel) > 250.0

def test_hi_lo_reaches_cruise_alt_and_mach():
    m = _launch(); w = _World()
    for _ in range(int(180 / DT)):
        m.update(DT, w)
        if m.phase == PH_CRUISE and m.t > 120: break
    from sim.physics import mach
    assert m.phase == PH_CRUISE
    assert abs(m.pos[1] - ONIKS.cruise_alt_hi) < 800.0
    assert abs(mach(np.linalg.norm(m.vel), m.pos[1]) - ONIKS.cruise_mach_hi) < 0.25

def test_lo_lo_stays_low():
    m = _launch("lo-lo"); w = _World()
    max_alt = 0.0
    for _ in range(int(90 / DT)):
        m.update(DT, w); max_alt = max(max_alt, m.pos[1])
    assert max_alt < 900.0                       # never balloons
    assert m.phase == PH_CRUISE and abs(m.pos[1] - ONIKS.lo_alt) < 30.0

@pytest.mark.slow
def test_full_hi_lo_flight_sea_skims_then_splashes_at_target():
    m = _launch(target=(0., 0., 250_000.)); w = _World()
    skim_samples = []
    for _ in range(int(900 / DT)):
        m.update(DT, w)
        if m.phase == PH_TERMINAL: skim_samples.append(m.pos[1])
        if not m.alive: break
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - np.array([0., 250_000.])) < 600.0
    settled = np.array(skim_samples[len(skim_samples)//3:])
    assert settled.size and abs(settled.mean() - ONIKS.skim_alt) < 5.0 and settled.max() < 40.0

@pytest.mark.slow
def test_fuel_lasts_long_range():
    m = _launch(target=(0., 0., 340_000.)); w = _World()
    for _ in range(int(900 / DT)):
        m.update(DT, w)
        if not m.alive: break
    assert m.impact_pos is not None and m.fuel > 0.0   # made 340 km with fuel to spare

def test_determinism():
    a = _launch(); b = _launch(); w = _World()
    for _ in range(int(30 / DT)): a.update(DT, w)
    for _ in range(int(30 / DT)): b.update(DT, w)
    assert np.array_equal(a.pos, b.pos) and np.array_equal(a.vel, b.vel)
```

- [ ] **Step 2: Run — FAIL.** **Step 3: Implement the phase machine.** Tune controller gains until tests pass; gains live as module constants with comments. **Step 4: PASS (including `-m slow`).** **Step 5: Commit** `feat: Oniks flight model - cold launch to sea-skim impact`.

### Task 13: sim/ships.py + sim/damage.py + sim/contacts.py (TDD)

**Files:** Create `sim/ships.py`, `sim/damage.py`, `sim/contacts.py`, `tests/test_ships.py`, `tests/test_damage.py`, `tests/test_intercept_e2e.py`.

`ships.py`:
```python
SHIP_TYPES = {  # length, beam, height(above water), speed_mps, hp
    "cargo":   dict(length=180.0, beam=28.0, height=22.0, speed=7.5, hp=2),
    "tanker":  dict(length=240.0, beam=40.0, height=20.0, speed=8.5, hp=3),
    "warship": dict(length=150.0, beam=19.0, height=24.0, speed=13.0, hp=2),
}
ST_ALIVE, ST_BURNING, ST_SINKING, ST_GONE = range(4)
class Ship:
    def __init__(self, ship_id, ship_type, lane_pts, lane_t0, direction=1):
        # position interpolated along lane at t0; heading along lane; state ST_ALIVE; hp from type
    def update(self, dt):
        # follow lane waypoints at type speed, turn rate <= 1.2 deg/s, loop lane ends (reverse direction)
        # ST_BURNING: keep moving at 30% speed, burn_timer -= dt; at 0 -> ST_SINKING
        # ST_SINKING: speed 0; list_angle ramps to 35deg over 25s; y sinks at 1.2 m/s; after 60s -> ST_GONE
    def velocity(self) -> np(3,)
    def obb(self) -> (center(3,), half_extents(3,), rotation3x3)   # hull box for hit test
```
`damage.py`:
```python
def segment_hits_obb(p0, p1, center, half, rot3x3) -> bool
    # transform segment into OBB local frame (rot.T @ (p - center)), then slab test
def apply_missile_hits(missiles, ships, effects_out: list):
    # for each live missile & ship: if segment_hits_obb(prev_pos, pos, *ship.obb()):
    #   ship.hp -= 1; missile dies (impact_pos = midpoint); ship -> ST_BURNING (hp>0) else ST_SINKING
    #   effects_out.append(("ship_hit", pos)) for particles/audio
```
`contacts.py`:
```python
UPDATE_PERIODS = ((100_000, 20.0), (300_000, 60.0), (1e12, 120.0))  # by range from base
class ContactBoard:
    def __init__(self, base_xz): self.tracks = {}   # ship_id -> dict(pos, vel, age, t_next)
    def update(self, ships, dt, sim_time):
        # each track refreshes when sim_time >= t_next (period by range); between refreshes age += dt
        # ships in ST_SINKING/GONE drop from the board after one refresh cycle
    def estimated_pos(self, ship_id, sim_time): return track.pos + track.vel * track.age  # dead-reckoned
```

- [ ] **Step 1: Failing tests** — ships: lane following stays within 200 m of polyline, speed correct, sinking sequence timings; damage: segment through OBB center hits, parallel segment 50 m abeam misses, fast-step tunneling caught (`p0`,`p1` 12 m apart straddling hull); contacts: track refresh periods honored, estimated_pos drifts with target velocity. Plus the END-TO-END:

```python
@pytest.mark.slow
def test_e2e_oniks_sinks_moving_cargo_at_180km():
    # Ship sails a straight lane crossing x at 7.5 m/s; launch with target_point at its CONTACT
    # (dead-reckoned, 40s stale) position; seeker must correct terminal error and hit.
    lane = [(-40_000.0, 180_000.0), (40_000.0, 180_000.0)]
    ship = Ship("c1", "cargo", lane, 0.45)
    w = _WorldWithShips([ship])
    stale_pos = ship.pos + ship.velocity() * 40.0
    m = Missile(ONIKS, np.array([0., 60., 0.]), 0.0, "hi-lo",
                target_point=np.array([stale_pos[0], 0.0, stale_pos[2]]))
    for _ in range(int(700 / DT)):
        m.update(DT, w); ship.update(DT)
        apply_missile_hits([m], [ship], [])
        if not m.alive: break
    assert ship.state in (ST_BURNING, ST_SINKING)     # HIT despite 300m of contact drift

@pytest.mark.slow
def test_e2e_miss_when_contact_hopeless():
    # target_point 25 km away from where the ship actually is; outside seeker basket -> clean miss
    ...
    assert ship.state == ST_ALIVE and not m.alive
```

- [ ] **Steps 2-4 → pass.** **Step 5: Commit** `feat: ships, damage, contact board with e2e intercepts`.

## Phase C — Models (parallel-friendly)

All model tasks: pure `MeshData` builders using `engine.meshdata`, GL-free, dimension-tested, then **visually reviewed via screenshot harness scene `models`** (added in Task 14): all models lined up on a flat pad, camera orbiting shots from 3 angles. The reviewing agent must look at the renders and iterate until silhouettes read clearly. Palette in `models/common.py`:

```python
PALETTE = dict(
    missile_body=(0.82, 0.84, 0.86), radome=(0.16, 0.16, 0.18), fin=(0.55, 0.57, 0.60),
    booster=(0.70, 0.71, 0.72), exhaust_ring=(0.25, 0.22, 0.20),
    mil_green=(0.26, 0.31, 0.23), mil_green_dark=(0.20, 0.24, 0.18), tire=(0.10, 0.10, 0.11),
    cargo_hull=(0.48, 0.20, 0.16), cargo_deck=(0.62, 0.60, 0.55), container_a=(0.65, 0.25, 0.2),
    container_b=(0.22, 0.42, 0.55), container_c=(0.75, 0.65, 0.3),
    tanker_hull=(0.16, 0.17, 0.20), tanker_deck=(0.55, 0.30, 0.25), pipe=(0.7, 0.68, 0.6),
    warship_hull=(0.45, 0.49, 0.53), warship_deck=(0.38, 0.42, 0.46), superstructure=(0.55, 0.59, 0.63),
    concrete=(0.58, 0.57, 0.54), radar_white=(0.85, 0.86, 0.84), tank_white=(0.80, 0.79, 0.75),
)
```

### Task 14: models/oniks.py + models/bastion.py + harness scene

**Files:** Create `models/common.py`, `models/oniks.py`, `models/bastion.py`, `tests/test_models.py`; modify `tools/screenshot_harness.py` (add `models` scene).

`build_oniks() -> MeshData` — 8.9 m long, Ø 0.67 m, built along +Z (nose at z=+4.45):
- Lathe body profile (z from -4.45): flat tail (r 0.30) → cylinder mid (r 0.335) → ogive taper from z=+1.8 → ring-intake lip at z=+3.9 (r 0.24) → INSET cone (the shock cone, radome color, r 0.20 at z=+3.7 tapering to point z=+4.45) — the signature annular intake look.
- 4 clipped-delta fins (`make_fin`, root 1.6, tip 0.55, span 0.55, sweep 0.9, thickness 0.04) at z=-2.6, rotated 90° apart, ×45° offset (X pattern).
- 4 small tail strakes near z=-4.0 (root 0.7, tip 0.3, span 0.30).
- Exhaust ring (dark) at tail.
`build_oniks_booster() -> MeshData` — separate 2.0 m cylinder r 0.30 + nozzle cone, drawn attached behind during EJECT/BOOST, dropped after.
`build_bastion_tel() -> MeshData` — ~12 m 8-wheel truck: hull box (11.5×2.9×2.6) mil_green; cab wedge front; 8 cylinders axis='x' tires r 0.65; TWO launch canisters (cyl r 0.45, len 9.4) side by side on the bed, ELEVATED 88° (rotation about X) when raised — builder takes `elevation_deg` param; 4 outrigger boxes.
`tests/test_models.py`: every builder returns finite mesh, normals unit (reuse `_check` pattern), oniks length within 1 cm of 8.9 m and max radius ≤ 0.34, TEL fits in 13×4×10 m box when elevated.

- [ ] **Steps: failing tests → implement → pass → harness `models` scene → VISUAL REVIEW (3 angles, iterate until they look right) → commit** `feat: Oniks and Bastion TEL models`.

### Task 15: models/ships_models.py + models/structures.py

**Files:** Create `models/ships_models.py`, `models/structures.py`; modify `tests/test_models.py`, harness `models` scene.

- `build_cargo()`: hull with raked bow (use wedges), 180×28 m, deck, 2 rows × 5 stacks of containers (boxes, alternating PALETTE container colors), white bridge castle aft, funnel.
- `build_tanker()`: 240×40, black hull, low profile deck with 3 pipe runs (thin cylinders axis='z'), center catwalk, bridge aft, 2 spherical-ish domes (lathe).
- `build_warship()`: 150×19, shear bow, stepped superstructure blocks, mast (thin cylinders), flat helo deck aft, gun turret cylinder fwd. Haze grey.
- `build_radar_station()`: concrete base box, lattice tower (4 corner thin cylinders + cross-bars... simplify: 2 nested boxes), white radome ball (lathe sphere) on top, small hut.
- `build_fuel_depot()`: 6 white storage tanks (cylinders axis='y', r 8, h 12, lathe domed tops) in 2 rows, pump house, pipe runs.
- `build_harbor()`: 2 concrete quays (long boxes at waterline), 3 warehouse boxes, 2 gantry cranes (boxes+legs).
- Dimension tests for each (length/beam within 1 m; everything above y=-2).

- [ ] **Steps: tests → implement → pass → harness VISUAL REVIEW → commit** `feat: ship and structure models`.

## Phase D — Game assembly

### Task 16: engine/particles.py + effects (TDD on math)

**Files:** Create `engine/particles.py`, `tests/test_particles.py`.

```python
class ParticlePool:   # struct-of-arrays, cap N; numpy float64 pos NO — float64 pos (world), f32 rest
    # fields: pos(N,3) f64, vel(N,3) f32, life(N) f32, max_life(N) f32, size0(N), size1(N), col0(N,3), col1(N,3), alive(N) bool
    def emit(self, n, pos, pos_jitter, vel_mean, vel_jitter, life, size01, col01, rng): ...
    def update(self, dt, drag=0.15, gravity=0.0, buoyancy=0.0):  # vectorized; kills life<=0
    def build_quads(self, cam_eye, cam_right, cam_up) -> np.ndarray  # (M*4, 10) f32: pos3 uv2 col3 alpha2->  pos3 uv2 rgba4 + size folded in; camera-relative positions
class TrailRibbon:    # ring buffer of (pos f64, age); add point every 35 m of travel; build camera-facing strip; width grows 1.5->14 m, alpha fades over 22 s; cap 1600 points
class Effects:        # owns pools: smoke (alpha blend), fire/flash (additive); spawn helpers:
    def booster_plume(pos, dir, throttle, rng)   # per-frame emission while thrusting
    def explosion(pos, scale, rng)               # one-shot: flash + fireball + smoke column + (water: splash ring white)
    def splash(pos, rng)
    def ship_fire(pos, rng)                      # continuous while ST_BURNING/SINKING
# GL side: one soft-disc 64x64 texture built procedurally (np: 1 - smoothstep(0.35, 1.0, r)), streamed VBO,
# draw smoke with glDepthMask(FALSE) alpha blend, fire additive. RNG: np.random.default_rng(seed) owned by Effects.
```
Tests (pure math): emit/update kills particles at life 0, drag slows, vectorized update of 10k particles < 2 ms, build_quads returns camera-relative finite values, ribbon point spacing ≥ 35 m, ribbon capped.

- [ ] **Steps: tests → implement → pass → commit** `feat: particle system and trails`.

### Task 17: game/cameras.py full suite (TDD on math)

**Files:** Modify `game/cameras.py`; create `tests/test_cameras.py`.

```python
class CameraRig:    # owns Camera + active controller + smooth transition (slerp-ish blend over 0.6s)
MODES = ["chase", "orbit", "target", "launcher", "free"]
# chase: eye = missile.pos - vhat*38 + up*10, look at missile.pos + vhat*60; lag eye with critically-damped spring (k=8)
# orbit: eye orbits missile at r=60, azimuth += 0.15 rad/s, alt offset 18; look at missile
# target: eye 25 m above/behind the TARGET looking at incoming missile (cinematic impact view)
# launcher: fixed eye 28 m from TEL, 9 m up, looks at TEL/canister, holds through launch
# free: Task 9 controller
# All eyes computed in float64. If no missile in flight, chase/orbit/target fall back to launcher view.
# Ground clamp: eye.y >= terrain_height(eye.xz)+2 and >= 2 above water.
```
Tests: chase eye stays within [25, 70] m of a missile flying a curve; transition blend is monotonic and ends exactly on the new mode's eye; ground clamp holds when missile sea-skims at 12 m.

- [ ] **Steps: tests → implement → pass → commit** `feat: cinematic camera suite`.

### Task 18: game/world wiring — world/world.py + game/sandbox.py + controls

**Files:** Create `world/world.py`, `game/sandbox.py`, `game/states.py`; modify `game/controls.py`, `main.py`.

`world/world.py`:
```python
class WorldState:
    def __init__(self, rng_seed=SEED):
        self.ships = [Ship(...) for SHIP_SPAWNS]; self.sites = SITES
        self.missiles = []; self.contacts = ContactBoard(BASE_XZ); self.sim_time = 0.0
    def terrain_height_at(self, x, z) -> float    # scalar wrapper over generation.terrain_height
    def step(self, dt):   # ships, missiles, apply_missile_hits, contacts, effects events queue
    def launch(self, profile, target_point, waypoints): # spawn Missile at BASE canister mouth; returns missile
```
`game/sandbox.py` — `SandboxState`: owns WorldState, Terrain/Ocean/Sky, Effects, CameraRig, HUD, TacticalMap, Audio. `sim_step(dt)` → world.step + effects emission from missile phases (plume while BOOST/thrust, trail point feed, events → explosions/splashes/fires). `render(dt)` order: sky → terrain → ocean → sites (place structure meshes at SITES on terrain) → ships (with list/sink transform from state) → TEL at base (elevate canister when armed) → missiles (+ dropped booster with simple ballistic fall + tumble for 6 s) → particles → HUD/map overlay.
`game/controls.py` final bindings (also in README):
```
ESC menu | M map | C camera | SPACE launch | 1/2 profile hi-lo/lo-lo
P pause | N frame-step | - / = time accel down/up (1,2,4,8,16) | F2 screenshot
free cam: WASD QE, mouse look (RMB drag), SHIFT fast, CTRL+SHIFT very fast
```
Time accel REFUSES to go above 1× while a missile is in PH_EJECT/PH_BOOST (the launch always plays real-time; auto-restores requested rate at PH_CLIMB/CRUISE).

- [ ] **Step 1: Implement.** **Step 2:** harness scenes `launch` (t=+2.0 s), `cruise` (chase cam mid-flight), `terminal` (300 m from a tanker) — VISUAL REVIEW each. **Step 3:** run `python main.py`, fly a full hi-lo strike on a ship via temporary debug key (T = launch at nearest contact) — confirm hit, fire, sinking. **Step 4: Commit** `feat: playable sandbox - launch to ship kill`.

### Task 19: engine/text.py + game/hud.py

**Files:** Create `engine/text.py`, `game/hud.py`.

`text.py`: bake `pygame.font.SysFont("consolas", 18, bold=True)` (+ size 28 for headers) glyph atlas (ASCII 32-126) to one GL texture at startup; `draw_text(x, y, s, color, size)` batches quads; ortho shader (no lighting, no log depth). Also `draw_rect(x, y, w, h, rgba)` and `draw_lines(points, rgba, width)` for HUD/map. Screen coords: origin top-left, pixels.
`hud.py`: top-left block: weapon name, phase label (EJECT/BOOST/CLIMB/CRUISE/DESCENT/TERMINAL — straight from phase enum), Mach, altitude m, speed m/s, range-to-target km, fuel %, time accel `×N`, sim clock. Bottom-center: camera mode + controls hint line. Target bracket: project locked ship to screen (proj·view·rel — reuse camera matrices), draw 4 corner lines + range text. When no missile: launcher status (ARMED / RELOADING n s), selected profile, target summary.

- [ ] **Steps: implement → harness `hud` scene VISUAL REVIEW → commit** `feat: text renderer and flight HUD`.

### Task 20: game/tactical_map.py (TDD on transforms)

**Files:** Create `game/tactical_map.py`, `tests/test_tactical_map.py`.

- Map texture: at first open, colorize `terrain_height` on a 1024×1024 grid over x∈[-350k,350k], z∈[-50k,560k] (CPU numpy → pygame surface → GL texture): ocean depth blues, land greens/browns by height, shoreline highlight.
- `MapView` (pure, testable): `center_xz` f64, `meters_per_px`; `world_to_screen(xz)` / `screen_to_world(px)`; zoom on scroll toward cursor (clamp 12 m/px – 800 m/px); pan with MMB/arrow keys.
- Overlays each frame: lane polylines (dim), site icons (square + name), contact triangles oriented by est. course with age-fade + dead-reckon position, BASE star, live missile diamonds + route lines + trail dots, waypoint chain for the planned route, range rings every 100 km around base, seeker-basket cone preview at the target point.
- Interaction: LMB on contact → select as target (target_point = dead-reckoned pos, target tracks contact); LMB on empty ocean → coordinate target; RMB → append waypoint; X → clear waypoints; SPACE → launch (only if target set, weapon ARMED).
- Tests (no GL): world↔screen roundtrip exact; zoom-at-cursor keeps cursor world point fixed (±0.5 px); click-pick selects nearest contact within 14 px else None; waypoint append/clear logic.

- [ ] **Steps: tests → implement → pass → harness `map` scene VISUAL REVIEW → commit** `feat: full-world tactical map`.

### Task 21: game/audio.py + menu (game/states.py)

**Files:** Create `game/audio.py`; modify `game/states.py`.

`audio.py`: `pygame.mixer.pre_init(44100, -16, 2, 512)` before init. Synthesis (numpy, write once to `sounds/*.wav` at first run if missing, else load — keeps startup fast):
- `launch.wav` (1.2 s): gas-eject thump — brown noise lowpassed (one-pole, fc 300 Hz) × exp(-t·4) + 55 Hz sine × exp(-t·6), peak-normalized.
- `booster.wav` (2.5 s loop): brown noise fc 220 Hz, slight 8 Hz amplitude wobble, loopable (crossfade last 0.2 s).
- `cruise.wav` (2 s loop): pink-ish noise fc 900 Hz at low gain (heard only in chase cam).
- `boom_far.wav` (3 s): 40 Hz sine × exp(-t·1.2) + noise burst fc 150 Hz; `boom_near.wav` (1.8 s) sharper (fc 800).
- `splash.wav` (1 s): white noise bandpassed ~1.2 kHz × exp(-t·5).
Manager: distance attenuation `gain = clip(1 - dist/12_000, 0, 1)**1.4` from CAMERA position (sounds at 600 km are silent — correct); booster/cruise loops attached to missile, channel reuse; UI clicks for map (tiny 2 kHz blip). Brown noise = `np.cumsum(rng.standard_normal(n)); x /= abs(x).max()`.
Menu (`states.py`): dark screen, big "ONIKS" title (size-28 font scaled ×3 via quad scale), subtitle "P-800 coastal strike sandbox", items SANDBOX / QUIT navigable by mouse + arrows/enter. ESC in sandbox → menu (sim pauses, RESUME item appears).

- [ ] **Steps: implement → run game, verify sounds audible and menu flows → commit** `feat: procedural audio and main menu`.

## Phase E — Performance & final assembly

### Task 22: tools/perf_harness.py + optimization pass

**Files:** Create `tools/perf_harness.py`.

```python
# python -m tools.perf_harness  -> hidden window 1600x900; worst-case scene:
# camera at 400 m alt over base looking north; ALL 14 ships alive; 4 missiles airborne
# (2 cruise hi @ 100/200 km, 1 terminal @ 8 km w/ full trail, 1 boost t=2 s); 2 ships burning;
# 600 rendered frames at forced time_scale 8. Per-frame timers via time.perf_counter around:
# sim_step total, particles update+build, terrain/ocean draw, models draw, HUD/map, swap.
# Report avg + p95 ms per section and total; FAIL (exit 1) if avg total > 16.0 ms.
```
- [ ] **Step 1: Implement harness.** **Step 2: Run.** If over budget, profile and fix in order: (1) per-ring ocean draw state changes — share one VAO bind; (2) particle quad build → preallocated arrays, no per-frame allocation; (3) text rebuilds — cache static HUD strings, rebuild only on change; (4) matrix math — preallocate, avoid np.linalg in hot loop; (5) reduce ring-0 ocean cells to 24 m if needed. Re-run until pass. **Step 3: Commit** `perf: 60fps worst-case scene` with the harness output pasted into the commit message.

### Task 23: Final integration + README + spec acceptance

- [ ] **Step 1:** Full `python -m pytest` (including slow) — all green.
- [ ] **Step 2:** All harness scenes re-rendered; review every PNG once more.
- [ ] **Step 3:** Update README controls table to match `game/controls.py` exactly.
- [ ] **Step 4:** Play-test checklist (manual, windowed): menu→sandbox; map target a 250 km contact; hi-lo launch real-time; ×16 accel mid-cruise; map shows missile progress; terminal cam shows skim + hit; ship burns and sinks; second launch lo-lo at a land site (harbor) — crater/explosion; free cam tour of an island; ESC→menu→RESUME works.
- [ ] **Step 5: Commit** `feat: ONIKS v1 sandbox complete`.

## Phase F — The user's /loop directive

After Task 23, the build enters the test-until-satisfied loop the user requested (`/loop test the game till your 100% satisfied`): repeat — run full pytest; run perf harness; render all screenshot scenes and **visually judge** physics plausibility, model quality, world scale feel; fix whatever falls short; re-run. Exit only when, in the same iteration: all tests pass AND perf budget holds AND the visual review finds nothing to fix. Log each iteration's findings in `docs/superpowers/loop-log.md`.

---

## Controls reference (single source: game/controls.py)

| Key | Action |
|---|---|
| M | tactical map |
| LMB / RMB (map) | set target / add waypoint |
| X (map) | clear waypoints |
| 1 / 2 | profile hi-lo / lo-lo |
| SPACE | launch |
| C | cycle camera (chase/orbit/target/launcher/free) |
| WASD QE + RMB-drag | free camera (SHIFT fast, CTRL+SHIFT very fast) |
| - / = | time accel down/up (1–16×, locked to 1× during launch) |
| P / N | pause / frame-step |
| F2 | screenshot to renders/ |
| ESC | menu |
```
