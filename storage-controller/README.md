# Refrigeration Logbook

HACCP-oriented cold-storage monitoring and reporting as a standalone
**Home Assistant App**.

Refrigeration Logbook runs in its own container alongside Home Assistant Core and
provides a dedicated sidebar interface (via Ingress) to monitor cold rooms,
refrigerators and freezers — independently of the Home Assistant Recorder.

## Features (current — Phase 1 + 2)

- Dedicated Home Assistant sidebar entry through Ingress
- Live Home Assistant connection status
- Searchable browser of all Home Assistant entities
- Free, role-based assignment of entities to cold-storage units
- Per-unit temperature limits and timing configuration
- Independent SQLite datastore with migrations

Planned: independent long-term temperature recording, incident detection,
PDF/CSV/JSON HACCP reports, scheduling and email delivery.

## Installation

1. Add this repository to your Home Assistant App store.
2. Install **Refrigeration Logbook**.
3. Start the App — it boots automatically and appears in the sidebar.

The App needs the Home Assistant Core API (`homeassistant_api: true`). It does
**not** require host network, privileged mode or any administrative host access.

## Configuration

No YAML options are required. Everything is configured in the web UI:

- **Storage units** — create units, assign entities by role, set limits.
- **Settings** — application preferences.

All persistent data is stored below `/data` and is included in Home Assistant
App backups.

## Development

See [DOCS.md](DOCS.md) for the architecture and local development workflow.
