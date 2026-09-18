# v0.7.0 commit guides

These guides reproduce **v0.7.0 — Alerts & Notifications** as 21 incremental commits.
They start from authoritative `origin/main@ed0c79d81e81fa4f9ca1bed1bb2ec5f8d7638e90`.

Each guide contains:

- the purpose and reference implementation commit;
- every file changed by that step as a **complete ready-to-save post-commit file**;
- focused verification commands;
- exact staging and commit commands.

Apply the files in numerical order. Do not copy only an isolated excerpt: each fenced block is the complete file for that step.
The generated commit SHA will differ when author, timestamp, or commit metadata differs; the tree content is authoritative.

## Sequence

1. [`1dfe4bbc` — feat: add alert domain types and pure evaluators](01-alert-domain.md)
2. [`f13756b5` — feat: persist alert rules and events](02-alert-persistence.md)
3. [`40049011` — test: cover alert schema migration and relationships](03-alert-schema-tests.md)
4. [`54134ca3` — feat: add alert rule and event storage operations](04-alert-storage.md)
5. [`d41a08f1` — feat: evaluate star milestone alerts](05-star-milestones.md)
6. [`800a32ed` — feat: evaluate velocity threshold crossings](06-velocity-crossings.md)
7. [`1a0d1727` — feat: evaluate newly detected burst alerts](07-burst-alerts.md)
8. [`f1debc2e` — test: cover alert evaluation and deduplication regressions](08-alert-regressions.md)
9. [`89065675` — feat: configure optional alert webhook delivery](09-webhook-contract.md)
10. [`b3308c80` — feat: deliver new alert events to a generic webhook](10-webhook-delivery.md)
11. [`36487f0d` — feat: evaluate alerts after snapshot collection](11-snapshot-orchestration.md)
12. [`358c4552` — test: cover snapshot and webhook alert integration](12-snapshot-webhook-tests.md)
13. [`6609d5ed` — feat: expose alert rule CRUD API](13-rule-api.md)
14. [`4faf2176` — feat: expose alert event inbox API](14-inbox-api.md)
15. [`a2fdf2c1` — test: cover alert API contracts and validation](15-alert-api-tests.md)
16. [`5121422f` — feat: add alert management commands to the CLI](16-rule-cli.md)
17. [`2828cbce` — feat: add alert inbox commands to the CLI](17-inbox-cli.md)
18. [`a45101ed` — feat: add the alert inbox to the dashboard](18-dashboard-inbox.md)
19. [`9a7ddcfe` — feat: add alert rule management to the dashboard](19-dashboard-rule-editor.md)
20. [`a57b94fe` — test: cover dashboard alert contracts and regressions](20-frontend-regressions.md)
21. [`2c49a794` — chore: release version 0.7.0](21-release-0.7.0.md)

## Final validation

```bash
pytest -q
ruff check src tests conftest.py alembic
python -m compileall -q src tests alembic
node --check web/app.js
node --check web/charts.js
```

Expected test result for this release: **233 passed**.

Existing installations must apply the schema migration before starting v0.7.0:

```bash
alembic upgrade head
```
