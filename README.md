# Storage Controller — Home Assistant App Repository

HACCP-oriented monitoring and reporting for cold rooms, refrigerators and
freezers, packaged as a standalone **Home Assistant App** (add-on). Storage
Controller runs in its own container, talks to Home Assistant Core through the
Supervisor proxy, and exposes a sidebar UI via Ingress — independently of the
Home Assistant Recorder.

> **Status:** Phase 1 + 2 (running App, Ingress UI, HA connection, entity
> browser, storage-unit configuration with types & monitoring profiles).
> Independent sample recording, incidents and reports follow in later phases.

## Apps in this repository

| App                                            | Description                                        |
| ---------------------------------------------- | -------------------------------------------------- |
| [Storage Controller](./storage-controller/)    | HACCP-oriented cold-storage monitoring & reporting |

---

## Installation

### A. Local add-on (recommended for testing / private use)

Works without any GitHub access — you copy the App onto the HA host.

1. Install the **Samba share** or **Advanced SSH & Web Terminal** add-on.
2. Get the App folder onto the host, either by:
   - copying the `storage-controller/` folder into the HA **`/addons/`** share, or
   - downloading a release package and extracting it:
     ```bash
     tar xzf storage-controller-<version>.tar.gz -C /addons
     ```
3. **Settings → Add-ons → Add-on Store → ⋮ → Check for updates**.
4. **Storage Controller** appears under **Local add-ons** → **Install** →
   **Start**.

Full step-by-step guide, verification checklist, expected logs and failure
signatures: **[storage-controller/INSTALL.md](./storage-controller/INSTALL.md)**.

You can build the local package yourself:

```bash
./scripts/package-local.sh   # → storage-controller-<version>.tar.gz
```

### B. Custom App repository (public URL)

Once this repository is **public**, add it as a custom App repository:

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Paste the repository URL → **Add**.
3. Install **Storage Controller** from the store.

> **Private repositories:** Home Assistant cannot install directly from a
> **private** GitHub repository through the Add-on Store, because the Store has
> no officially supported authentication mechanism for private Git sources. For
> private development, use the **local add-on** method (A) or a release package.
> To distribute via the Store, publish a **sanitized public** release repository.

---

## Requirements

- Home Assistant **OS** or **Supervised** (Supervisor + Add-on Store)
- Architecture: **amd64** or **aarch64** (64-bit only)
- Permissions used: `homeassistant_api` only (no host network / privileged)

---

## Repository layout & branches

```
.
├── repository.yaml          # custom-repository manifest (for method B)
├── README.md                # this file
├── Claude.md                # full product specification
├── report_mockup.png        # visual reference for the Phase 5 monthly report
├── scripts/package-local.sh # build a sanitized local install package
├── .github/workflows/       # CI, secret-scan, release
└── storage-controller/      # the App (config.yaml, Dockerfile, backend, frontend, …)
```

- **`main`** — stable development. Always installable.
- **`next`** *(optional)* — test installations / pre-release validation before
  promotion to `main`.

Releases are tagged `vX.Y.Z`; the release workflow runs the test suite, builds a
sanitized local install package and attaches it to a GitHub Release.

---

## Security & privacy

- The Supervisor token is **never** stored, logged or exposed to the frontend
  (logs are redacted).
- All persistent state lives under `/data` and is **never** committed
  (databases, reports, uploaded logos, SMTP credentials, tokens, local config
  are git-ignored).
- Secret scanning (gitleaks) runs in CI on every push and pull request.
- **Demo data is disabled by default**; production starts with zero storage
  units. Demo seeding is opt-in only (see `storage-controller/INSTALL.md` §9).

---

## Development

See **[storage-controller/DOCS.md](./storage-controller/DOCS.md)** for the
architecture and local development workflow (backend `pytest`, frontend
`vitest` + `vite build`, container build).
