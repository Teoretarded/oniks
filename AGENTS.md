# AGENTS.md — rules for ANY AI agent working on ONIKS

This applies to every agent — Claude, GPT/Codex, Gemini, research subagents,
anything. Full project guide: `CLAUDE.md` (same folder — read it regardless
of which model you are; it is the project manual, not Claude-only).

## Folder layout (repo lives inside `OINKS\`)

- `oinks PROTO\` (this repo) — CODE ONLY: main.py, engine/, world/, sim/,
  game/, models/, tools/, tests/. The only git/GitHub-tracked folder.
- `..\Markdown\` — ALL documentation: plans, specs, research references,
  run logs, audits, session notes, reports. Read background there; write
  every new .md/report/research file there (session evidence goes in the
  next free `NN_topic\` folder under `..\Markdown\documentation and research\`).
- `..\Assets of oinks\` — raw 3D asset dumps (OBJ meshes, manifests).
- `..\README.md` — one-page architecture overview of the whole OINKS folder.

## Hard rules

1. NEVER create markdown, reports, or research files inside this repo.
   `CLAUDE.md`, `README.md`, and this file are the only .md files allowed here.
2. "Go through the codebase" means the code folders only — do not crawl
   `..\Markdown\` unless the task needs a plan, spec, or research number.
3. Obey the project laws in `CLAUDE.md` (physics not dice, fog of war,
   determinism, regression contracts never weaken, GL-free sim, measure
   don't guess).
4. Run `python -m pytest -q -n auto` (or `python -m tools.select_tests --run`)
   before claiming anything works.
