# Roadmap

This roadmap keeps the next meaningful improvements visible without turning the repo into a
long backlog. It is intentionally short and focused on product-facing work.

## Current focus

- Improve provider reliability and make fallback reasons visible in CLI output.
- Tighten the terminal experience with clearer demos, examples, and actionable reports.
- Keep analysis grounded in the actual diff and the repo's local commit conventions.

## Next

- Generate actionable rewrite plans for weak commits, including reword-ready sequences.
- Add a lightweight pre-commit mode for grading pending commit messages before they land.
- Improve machine-readable reporting so CI and automation can consume results more easily.

## Later

- Support richer remote analysis paths for hosted repositories.
- Add optional HTML export for sharing results outside the terminal.
- Improve cost reporting beyond raw token counts.

## Non-goals

- No TUI or web UI.
- No plugin architecture for many providers.
- No heavy config or dotfile system beyond flags and environment variables.
