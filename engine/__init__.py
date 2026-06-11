"""Engine package.

PyOpenGL's per-call error checking wraps EVERY GL call in glGetError and
costs more CPU than the calls themselves (~30% of a frame's submit time —
Task 22 perf). It is disabled for normal runs; set ONIKS_GL_DEBUG=1 to turn
the checks back on while debugging GL issues. This must run before any
``OpenGL.GL`` import, and ``engine`` is imported before every GL-touching
module, so it lives here.
"""

import os

try:
    import OpenGL          # top-level package only: flags, no GL/driver load
except ImportError:        # headless test envs without PyOpenGL stay fine
    OpenGL = None

if OpenGL is not None and not os.environ.get("ONIKS_GL_DEBUG"):
    OpenGL.ERROR_CHECKING = False
