# Security Policy

Thank you for helping keep this project and its users safe.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security problems.

Use one of the following private channels instead:

- GitHub **Private vulnerability reporting** (preferred): open the repository's
  *Security* tab → *Report a vulnerability*.
- Or email the maintainer listed on the repository profile and mark the subject
  with `[SECURITY]`.

When reporting, please include:

- A clear description of the issue and impact.
- Reproduction steps or a minimal proof of concept.
- Affected version / commit hash if known.
- Any suggested mitigation.

We aim to acknowledge new reports within **5 business days** and to provide a
remediation plan within **30 days** when the report is confirmed.

## Supported Versions

This project tracks the latest commit on `main`. Older tags/commits do not
receive backported fixes unless explicitly noted in a release.

## Secret & Credential Hygiene

This repository is **public**. Operators are responsible for keeping all real
credentials, recipient lists and production endpoints out of the codebase.

- Never commit `.env`, `config/config.yaml`, `secrets/`, mailbox passwords,
  Azure OpenAI keys, ACS connection strings, SMTP passwords, or real recipient
  addresses. The `.gitignore` shipped in this repo blocks these by default.
- Use **GitHub Encrypted Secrets** for runtime credentials and **GitHub
  Environments** with required reviewers for production sends. The schedule
  workflow in this repository is prepared for an environment named
  `production-send` (the `environment:` line is left commented so the current
  cron continues to work; uncomment after you create the environment).
- CI on pull requests must remain credential-free and must not attempt real
  email delivery — it only runs lint, syntax, import and dry-run smoke checks.
- If you suspect a secret was committed, **rotate it immediately**, then
  remove the value from history (e.g. `git filter-repo` or BFG) and force-push
  on a private branch only after coordination with the maintainer.

## Forks & Pull Requests

External contributors should:

1. Fork the repository.
2. Create a feature branch from `main`.
3. Run the CI workflow locally or via the fork's Actions tab before opening a
   PR. PR CI does not have access to upstream secrets and must remain green.
4. Avoid touching `Generate-and-Send-Daily-AI-Newsletter.yaml` unless the
   change is explicitly requested by the maintainer; production cron behaviour
   is sensitive.

## Out-of-scope

- Vulnerabilities in third-party services (Azure, GitHub, mail providers) —
  please report them upstream.
- Issues that require physical access to a maintainer's machine.
