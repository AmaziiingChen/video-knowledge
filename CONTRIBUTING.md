# Contributing to KnowledgeHub

Thank you for helping improve the macOS knowledge workbench.

1. Discuss significant product or privacy changes in an issue before coding.
2. Keep changes focused; retain existing local data compatibility and avoid
   unrelated formatting or dependency upgrades.
3. Add a focused test for changed behaviour, run the affected backend tests and
   `cd frontend && npm run build` for frontend changes.
4. Never commit `.env` files, tokens, cookies, `data/`, `materials/`, real
   reports, screenshots, downloaded media or personal information.
5. State every external service or new permission your change introduces, and
   update `PRIVACY.md` and `THIRD_PARTY_NOTICES.md` when appropriate.
6. By contributing, you agree that your contribution is licensed under the MIT
   License in this repository.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue with sensitive details.
