# Repository instructions

## Repository guide

- This is an established Python project. Inspect the implementation and nearby tests before editing.
- Preserve compatibility with the checked-out version and keep unrelated behavior unchanged.
- Prefer a small root-cause correction over an issue-specific workaround.
- Do not commit, rewrite history, update dependencies, or perform broad formatting changes.

## Test guide

- Use the repository test runner under `bin/` for the narrowest relevant test first.
- Add or update a focused regression test when it materially improves confidence.
- If a host dependency is unavailable, report it precisely and continue with static checks.
- Run `git diff --check`, inspect the final diff, and leave only the intended change.

