# Roadmap

This roadmap keeps the next meaningful improvements visible without turning the repo into a
long backlog. It is intentionally short and focused on product-facing work.

## Current focus

- Improve machine-readable reporting so CI and automation can consume results more easily.
- Continue improving low-friction local onboarding and packaging polish.

## Recently shipped

- Visible provider fallback reasons in terminal and JSON output.
- Actionable reword plans for weak commits.
- Estimated API cost reporting for the default shipping models.
- A packaged `--install-commit-msg-hook` flow for repo-local hook setup.
- A hook-friendly `--commit-msg-file` mode for validating pending commit messages.
- More reliable Gemini-backed analysis and write flows.
- A checked-in demo transcript covering analysis mode, write mode, and commit-msg validation.
- Sharper docs-only heuristic rewrite suggestions in the no-provider path.

## Next

- Continue improving heuristic suggestions for very low-context staged diffs.
- Continue polishing docs and examples as the CLI output evolves.

## Later

- Support richer remote analysis paths for hosted repositories.
- Add optional HTML export for sharing results outside the terminal.

## Non-goals

- No TUI or web UI.
- No plugin architecture for many providers.
- No heavy config or dotfile system beyond flags and environment variables.
