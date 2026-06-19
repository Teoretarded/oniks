"""One-shot golden capture of the PRE-REFACTOR inline back-projection math from
sim/commander.process_missile_track (HEAD lines ~1386-1416), VERBATIM.

This file exists so the Task A bit-identical test can assert the extracted
back_plot_surface() returns EXACTLY what the inline code returned. The inline
math is duplicated here on purpose (this is the golden oracle, captured from
HEAD before the extract); it is NOT imported from the model.

Run: python tools/_backplot_golden_capture.py  -> prints a Python literal table.
"""

import math

# Constants verbatim from sim/commander.py (HEAD).
HOME_COAST_Z = 0.0
BACKPLOT_CLIMB_VY = 50.0
BACKPLOT_MIN_CLOSE_VZ = 50.0


def inline_back_project(first_pos, first_vel):
    """VERBATIM copy of the HEAD inline back-projection (lines ~1386-1416),
    returning (launch_x, launch_z) or None."""
    vx = float(first_vel[0])
    vy = float(first_vel[1])
    vz = float(first_vel[2])
    fx = float(first_pos[0])
    fy = float(first_pos[1])
    fz = float(first_pos[2])

    if vy >= BACKPLOT_CLIMB_VY:
        t_back = fy / vy
        launch_x = fx - vx * t_back
        launch_z = fz - vz * t_back
    else:
        dz = fz - HOME_COAST_Z
        if vz <= BACKPLOT_MIN_CLOSE_VZ or dz <= 0.0:
            return None
        s = dz / vz
        launch_x = fx - vx * s
        launch_z = HOME_COAST_Z
    return (launch_x, launch_z)


# Synthetic track table — every regime the spec enumerates.
CASES = [
    # name, first_pos (x,y,z), first_vel (vx,vy,vz)
    ("climb_near_launch",      (0.0, 500.0, 1000.0),     (0.0, 100.0, 800.0)),
    ("climb_steep_offset",     (1500.0, 800.0, 3000.0),  (50.0, 200.0, 600.0)),
    ("climb_exactly_threshold",(0.0, 600.0, 2000.0),     (10.0, 50.0, 700.0)),
    ("level_closing",          (0.0, 60.0, 200_000.0),   (0.0, 1.0, 800.0)),
    ("level_closing_offset",   (5000.0, 50.0, 150_000.0),(120.0, 0.0, 750.0)),
    ("level_receding",         (0.0, 60.0, 200_000.0),   (0.0, 1.0, -800.0)),
    ("coast_parallel_slow_vz", (0.0, 60.0, 100_000.0),   (700.0, 0.0, 40.0)),
    ("dz_le_zero",             (0.0, 60.0, -50.0),        (0.0, 1.0, 800.0)),
    ("already_at_surface_climb",(0.0, 0.0, 5000.0),      (0.0, 100.0, 800.0)),
    ("vz_exactly_min_close",   (0.0, 60.0, 100_000.0),   (700.0, 0.0, 50.0)),
    ("level_negative_x_vel",   (-2000.0, 80.0, 80_000.0),(-300.0, 5.0, 900.0)),
]


def main():
    print("# (name, first_pos, first_vel, expected_or_None)")
    print("GOLDEN = [")
    for name, fp, fv in CASES:
        out = inline_back_project(fp, fv)
        print(f"    ({name!r}, {fp!r}, {fv!r}, {out!r}),")
    print("]")


if __name__ == "__main__":
    main()
