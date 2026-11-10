# Security Policy

## Reporting a vulnerability

Please report security issues **privately** using GitHub Security Advisories
(**Security → Report a vulnerability**). Do not open a public issue for a
security problem.

## Scope

- This skill is a client for a third-party API. It stores **no credentials**
  and requires **no API key**.
- Never commit secrets, tokens, private text, or private audio to the repo.
- The cache (`~/.cache/speakee-tts`) contains generated audio and text hashes.
  If the source text is private, treat the cache as private too.
- `--base` / `SPEAKEE_BASE` can point at any host; only use hosts you trust.
  Text is sent to that host in plain JSON.

## API abuse and rate limits

This project uses a free community API. Keep the default `--workers 4`, leave
caching enabled, and do not run bulk jobs you do not need. Accidental overload
or abuse can get the endpoint rate-limited or taken down.

## Supported versions

Security fixes target the latest release (see `VERSION`). There is no long-term
support branch.
