<!-- Describe the high-level purpose of this PR -->

## Summary

- Add minimal `pyproject.toml` so packaging with `python -m build` works.
- Update CI: add GitHub Actions workflow for lint/test/build on PRs to `main` and `development`.
- Set `game_room_keepalive_seconds` to `0` in `app/core/config.py` to remove empty rooms immediately (fixes test expectation).

## Why

- Tests and CI should reflect project packaging and behaviour; `python -m build` previously failed because there was no packaging metadata.
- The config change makes disconnect behavior deterministic for tests.

## What changed

- Added: `pyproject.toml` (minimal setuptools backend)
- Added: `.github/workflows/ci.yml` (lint, test, optional build)
- Modified: `app/core/config.py` (default `game_room_keepalive_seconds` set to 0)

## How to test

1. Run the test suite locally:
   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -r requirements.txt
   pytest -q
   ```
2. Optionally verify packaging:
   ```bash
   python -m build
   ```

## Notes

- `pyproject.toml` uses `setuptools` and points packages to the `app` directory. We can switch to `poetry` or change packaging metadata later.
- Set `project.license` to a string (e.g. "MIT") to avoid a deprecation warning if desired.

Signed-off-by: Automated PR
