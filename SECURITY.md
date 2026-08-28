# Security Policy

## Supported Scope

Security fixes target the current `v0.4` SQLite local release. Public multi-user hosting,
multiple backend processes and arbitrary ATS automation are outside the supported scope.

The default `AUTH_MODE=local` configuration is for local development only. Staging and
production configurations must use OIDC or a trusted identity gateway and must keep
`ALLOW_INSECURE_USER_HEADER=false`.

## Reporting a Vulnerability

Use the repository's private GitHub Security Advisory form (`Security` ->
`Report a vulnerability`) when available. Do not put API keys, access tokens, resumes,
contact details or other private candidate data in a public issue.

Include the affected version, reproduction steps, expected impact and the smallest
sanitized example needed to reproduce the problem.

## Operational Boundaries

- Treat all job pages and ATS content as untrusted input.
- Do not expose the local development server directly to the public internet.
- Keep `.env`, SQLite databases, generated evaluation artifacts and candidate materials
  outside version control.
- Do not bypass login, CAPTCHA, 2FA, anti-automation controls or human approval gates.
- Rotate any credential immediately if it may have appeared in logs, screenshots or Git
  history.

