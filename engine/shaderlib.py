"""Shared GLSL snippets (plain string constants — GL-free).

``world/ocean.py`` must stay importable without OpenGL (unit tests run
headless), so GLSL shared between its ocean shader and the renderer's lit
shader lives here rather than in the GL-importing ``engine/renderer.py``.
"""

# Atmospheric haze: the uniforms it reads + apply_haze(). Concatenate into a
# fragment shader body after that shader's own in/out/uniform declarations.
HAZE_GLSL = """
uniform vec3 u_sun_dir;
uniform vec3 u_haze_color, u_sun_haze_color;
uniform float u_haze_density, u_cam_alt;
vec3 apply_haze(vec3 color, vec3 view_vec, float cam_alt){
    float dist = length(view_vec);
    float h = max(cam_alt + view_vec.y * 0.5, 0.0);
    float density = u_haze_density * exp(-h / 6000.0);
    float f = 1.0 - exp(-density * dist);
    vec3 dir = view_vec / max(dist, 1.0);
    float sun_amt = pow(max(dot(dir, u_sun_dir), 0.0), 8.0);
    return mix(color, mix(u_haze_color, u_sun_haze_color, sun_amt), f);
}
"""
