# Developing your own fork

Mac Control Dashboard is provided as-is for independent personal and commercial use under the [MIT license](LICENSE). Fork the repository to customize it, develop features and maintain your own installation. No ongoing upstream development, support, security updates or pull request review is promised.

Preserve the copyright and license notices and the [third-party notices](THIRD_PARTY_NOTICES.md) when distributing your fork. Clearly identify your fork and its changes so users can distinguish it from this release.

## Development environment

- Python 3.12 (`python3.12 -m venv apps/api/.venv`)
- Node v22+ (`npm ci` in `apps/web/`)

## Check commands

From the repository root, run these checks before distributing your changes:

```bash
# API checks
(cd apps/api && .venv/bin/python -m pytest -q)

# Web checks
(cd apps/web && npm run type-check && npm test && npm run build)
```

See [Getting started](docs/getting-started.md) for dependency installation and local operation.

## Secret scanning

- Do not commit `.env`, `.key`, `.pem`, tokens, database files or vault files.
- `.gitignore` covers `.env*` (except `.env.example`), `*.db`, `vault.key`, `*.token` and `client_secret_*.json`.
- A `.gitleaks.toml` allowlist exists for synthetic test fixtures (fake `ghp_*` tokens, placeholder `client_secret`).
- A `.pre-commit-config.yaml` runs `gitleaks` automatically.

## Maintaining a fork

- Keep changes focused and document altered behavior and prerequisites.
- Use your own credentials and configuration; exclude local runtime data from releases.
- Review access and credential handling when adding external integrations.
- Establish your own support and security reporting policy if you distribute a maintained fork.
- Do not rely on an upstream pull request being reviewed or merged.
