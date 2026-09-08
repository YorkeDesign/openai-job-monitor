# openai-job-monitor

Daily GitHub Actions job that scrapes OpenAI careers, matches against profile.json, and emails a digest. CI regenerates `config.json` from Actions secrets at runtime - never commit a real `config.json` (see `.gitignore` and `config.example.json`).

Commit autonomy: move-fast
Harvest approval: gated


## Operations reporting (hardware + services)

**Reports to: hardware-planning (direct)**

This project reports to the central **hardware-planning** repo, which plans one
shared fleet and one wallet across the whole portfolio. Two living docs:

| Doc | Covers | Convention |
|---|---|---|
| `docs/hardware-requirements.md` | Compute, storage, backups, devices this project needs **now and next** | `/Users/simonyorke/Projects/repos/hardware-planning/requirements-guide.md` |
| `docs/services.md` | Subscriptions, vendors, fees, and free tiers with a ceiling | `/Users/simonyorke/Projects/repos/hardware-planning/services-guide.md` |

- **Both are trajectory-first.** Report what is needed now *and* what will be
  needed and roughly when. A doc that only describes today has under-reported -
  the planner budgets ahead of the need.
- **Update them in the same commit as the change that moves a requirement**:
  new always-on process, storage or dataset jump, new device, new vendor or API,
  plan change, trial started, or a scope decision that changes either.
- **Run `/ops-review` at the first session of the week** in this repo. The
  central `/ops-sweep` catches anything missed.
- **Never record credentials** in `docs/services.md` - vendor, plan, cost,
  currency, cycle, dates, owner, and a payment-method *label* only. Nothing from
  `.env`.
- **Never sign up, start a trial, enter payment details, or cancel a service.**
  Recommend it in the doc; Simon acts.
- Out of scope: **BOM hardware** for hardware-design projects (motors, boards,
  electronics) is project BOM, not fleet. **Fiso-provided** hardware and
  services are excluded entirely.

## Harvestry research vault

This project consumes curated research from Harvestry via the `harvestry` MCP server. Context: `personal`. Harvestry project name: `openai-job-monitor`. Harvestry curates, this repo consumes: read tools only, plus the one write tool `mark_item_actioned`, never for an action not actually taken. Session start: `list_collection_queue` (captures tagged here with no verdict yet), assess what the session can, record a verdict for each item read, say how many proposals await approval. Scoping or ideation prompts check `get_project_brief` first. Full boundary and workflow: `~/.claude/templates/harvestry-consumer-claude-snippet.md`; proactive surfacing: the global `surface-innovation` skill.

## Harvest ingest (portfolio standard, 2026-09-07)

`Harvest approval:` at the top of this file governs Harvestry-sourced changes (`gated`: proposals wait for Simon to set `status: approved`; `autonomous`: this project implements them itself, one per run). The daily `daily-harvest-ingest` task runs the global `harvest-ingest` skill here: it works this project's Harvestry queue, records every verdict in the vault and in `docs/harvest/YYYY-MM-DD-harvest.md`, and writes an implementation proposal per adoptable capture into `docs/harvest/proposals/`. `TASKS.md` carries "Harvest proposals awaiting approval: N" and sessions say that number at start. Procedure: `~/.claude/skills/harvest-ingest/SKILL.md`.
