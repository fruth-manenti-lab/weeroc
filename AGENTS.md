# RADIOROC development

- Read `IMPLEMENTATION_STATUS.md` for the current delivery and evidence, and
  `CROSS_PLATFORM_REBUILD_PLAN.md` for architecture and feature scope.
- Keep each task bounded with acceptance checks. Preserve old CLI entry points
  and shared behavior while extracting modules. Do not put device logic in UI code.
- Use `.conda-radioroc/bin/python` for existing lab tools. Use a separate `.venv`
  or `.venv-foundation` for package development; see `DEVELOPMENT.md`.
- Run `python tools/check_development.py` for relevant source changes and verify
  an installed wheel after packaging changes. Never run hardware scans as CI tests.
- Only one designated operator accesses the board. Agent workers use offline
  tests, fake transports or saved data. Do not run the environment diagnostic
  script as an offline check: it enumerates hardware through D2XX.
- Local experiment folders and `radioroc_runs` must remain uncommitted, not deleted.
  Preserve user changes and measured data. Stage explicit paths; no blanket cleanup.
- Keep vendor artifacts local. Never commit environments or generated build files.
- Use separate worktrees or non-overlapping files for delegated tasks; one editor
  owns shared API contracts at a time. The lead reviews and integrates.
- Record completed checks, limitations, and the next task in the status document.
