"""Refine the saturation contrast: with INFINITE ammo (magazine removed as a
confound), characterise the lone-round and spaced-trickle leak distributions
across many seeds, and confirm synced always leaks >= 1 with both runs spending
comparable SM-2.
"""
import sys

sys.path.insert(0, ".")

from tools.probe_swarm_satcheck import run    # noqa: E402

BIG = 100000

if __name__ == "__main__":
    seeds = range(12)
    print("LONE round, INFINITE ammo, 12 seeds:")
    lone = [run(1, s, synced=True, ammo=BIG) for s in seeds]
    print("  hits:", [r["hits"] for r in lone],
          " max:", max(r["hits"] for r in lone),
          " spent:", [r["spent"] for r in lone])

    print("\nSYNCED 8, INFINITE ammo, 12 seeds:")
    syn = [run(8, s, synced=True, ammo=BIG) for s in seeds]
    print("  hits:", [r["hits"] for r in syn],
          " min:", min(r["hits"] for r in syn),
          " spent:", [r["spent"] for r in syn])

    print("\nTRICKLE 8, spacing 600s, INFINITE ammo, 12 seeds:")
    tr = [run(8, s, synced=False, ammo=BIG, spacing=600.0) for s in seeds]
    print("  hits:", [r["hits"] for r in tr],
          " max:", max(r["hits"] for r in tr),
          " spent:", [r["spent"] for r in tr])

    print("\nTRICKLE 8, spacing 900s, INFINITE ammo, 12 seeds:")
    tr9 = [run(8, s, synced=False, ammo=BIG, spacing=900.0) for s in seeds]
    print("  hits:", [r["hits"] for r in tr9],
          " max:", max(r["hits"] for r in tr9))
