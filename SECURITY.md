# Security policy

## Supported scope

The maintained desktop target is macOS. Windows and Linux are not supported
release targets at this time.

## Reporting a vulnerability

Please do not publish credentials, proof-of-concept exploit code, private
documents or reproducible attack details in a public issue. Use GitHub's
private security-advisory reporting for the repository when it is enabled. If
that channel is unavailable, open a minimal issue requesting a private contact
channel and include no sensitive details.

Include the affected version or commit, macOS version, reproduction steps,
impact, and whether any local data, credential or network boundary is involved.

## Project expectations

- Do not submit real keys, cookies, databases, screenshots, user reports or
  imported content.
- Keep local API write routes bound to the desktop instance token.
- Treat externally sourced pages, OCR, subtitles and comments as untrusted
  input.
- Report dependency vulnerabilities with the package name and advisory link.
