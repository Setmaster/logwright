# logwright

`logwright` is a CLI tool for grading git commit messages against their actual diffs and helping write better ones from staged changes.

See the [demo transcript](docs/demo.md) for real terminal runs covering analysis mode, write mode, and commit-msg validation.

## What it does

- Analyze recent commits in the current repository or a remote git URL.
- Score commit messages against the change itself, not just the subject line in isolation.
- Detect local repo conventions such as Conventional Commits and scoped subjects.
- Generate commit message suggestions from `git diff --cached`.
- Generate actionable reword plans for weak commits.
- Check pending commit messages before they land, suitable for `commit-msg` hooks and amend/reword flows.
- Surface provider fallback reasons when a live model call fails and heuristics take over.
- Fall back to deterministic heuristics when no LLM key is configured.

## Install

Python 3.11+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

Analyze the current repository:

```bash
logwright --analyze
```

Analyze a remote repository with a shallow temp clone:

```bash
logwright --analyze --url https://github.com/steel-dev/steel-browser --limit 25
```

Print machine-readable output:

```bash
logwright --analyze --json
```

Suggest commit messages from staged changes:

```bash
logwright --write
```

Print suggestions without interactive prompts:

```bash
logwright --write --print-only
```

Check a pending commit message against staged changes:

```bash
logwright --commit-msg-file .git/COMMIT_EDITMSG --min-score 5
```

Use heuristic mode only:

```bash
logwright --analyze --provider heuristic
```

Print the installed version:

```bash
logwright --version
```

## Versioning

`logwright` follows Semantic Versioning. While the project is still in the `0.x` stage,
scoring heuristics, provider-specific output details, and machine-readable payload shape may
still evolve between minor releases. The core CLI surface is intended to remain compact and
predictable: `--analyze`, `--write`, `--commit-msg-file`, `--provider`, `--json`,
and `--version`.

## Providers

`logwright` supports:

- `anthropic`
- `openai`
- `gemini`
- `auto`
- `heuristic`

`auto` prefers Anthropic when `ANTHROPIC_API_KEY` is present, then OpenAI when `OPENAI_API_KEY` is present, then Gemini when `GEMINI_API_KEY` is present, and finally falls back to heuristics.

`logwright` auto-loads a repo-local `.env` file before provider resolution, so you can keep API keys in the project root without exporting them into your shell.

Local smoke-test snapshot in this repo on 2026-04-20

These entries reflect one local live run per provider path on that date. The checked-in demo
transcript below is intentionally smaller and only shows a representative subset.

| Provider | Analyze mode | Write suggestions | Notes |
|---|---|---|---|
| Anthropic | Locally smoke-tested | Locally smoke-tested | Uses JSON prompting with local schema validation |
| OpenAI | Locally smoke-tested | Locally smoke-tested | Uses Responses API structured outputs |
| Gemini | Locally smoke-tested | Locally smoke-tested | Uses structured JSON output with `thinkingBudget: 0` and transient retries |
| Heuristic | Locally smoke-tested | Locally smoke-tested | No API key required |

If a provider call fails at runtime, `logwright` falls back to heuristics and prints the fallback reason in the terminal output.

Environment variables:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GEMINI_API_KEY=...
```

Optional model overrides:

```bash
export LOGWRIGHT_ANTHROPIC_MODEL=claude-sonnet-4-6
export LOGWRIGHT_OPENAI_MODEL=gpt-5.4-mini
export LOGWRIGHT_GEMINI_MODEL=gemini-2.5-flash
```

Or pass a model explicitly:

```bash
logwright --analyze --provider openai --model gpt-5.4-mini
logwright --analyze --provider gemini --model gemini-2.5-flash
```

## Example output

```text
$ logwright --analyze --provider heuristic --url https://github.com/steel-dev/steel-browser --limit 2
Analyzed 2 commits in https://github.com/steel-dev/steel-browser
Detected style: Conventional Commits
Provider: heuristic (heuristic)

COMMITS THAT NEED WORK
No commits landed in the lowest bucket.

WELL-WRITTEN COMMITS
- 9bc3ebb "fix: wrap live session script in IIFE to avoid global scope collisions (#273)"
  Score: 8/10
  Why: Message language overlaps with the changed files or identifiers.

YOUR STATS
Average score: 6.5/10
Vague commits: 0
Very short commits: 0
Cache hits: 0
Cache misses: 2
Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=0, out=0
```

## Hook usage

For a minimal heuristic `commit-msg` hook:

```sh
#!/bin/sh
logwright --commit-msg-file "$1" --provider heuristic --min-score 5
```

If the score falls below the threshold, `logwright` exits nonzero and prints a suggested
replacement message based on the staged diff.

If there is no staged diff, `logwright` falls back to the current `HEAD` commit so
message-only amend and reword flows still work.

If you want model-backed hook checks instead, pass `--provider anthropic`, `--provider openai`,
or `--provider gemini` explicitly so latency and cost are an intentional choice.

## Design Decisions

- Diff-aware grading first. A message is only useful relative to what actually changed.
- Hybrid scoring. Deterministic lint catches obvious low-signal subjects cheaply; LLM judgment handles fidelity and rewrite quality.
- Repo-style calibration. Conventional Commit usage is detected instead of imposed globally.
- Transparent fallback. If no model key is available or a provider call fails, the flow stays usable and reports why.
- Local caching. Results are cached under `~/.cache/logwright` by commit SHA, repo identity, style signature, provider, and model.
- Actionable cleanup. Weak commits produce a reword-ready plan instead of only a report card.
- Hook-friendly validation. Pending commit messages can be checked against the staged diff, or against `HEAD` during message-only amend and reword flows.
- Remote support via shallow clone. It is simple, portable, and preserves access to full git metadata without special-casing GitHub.

## Limitations

- Anthropic currently uses JSON-only prompting plus local validation rather than tool calling.
- Remote analysis uses shallow cloning rather than the GitHub API.
- The heuristic write suggestions are intentionally conservative and can read generic without an LLM provider.
- HTML export is not implemented yet.
- The `commit-msg` hook path is implemented, but there is not yet a packaged installer for Git hooks.
- Cost calculation is not included yet; token usage is reported when available.

## Development

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Run directly from source:

```bash
python3 -m logwright --help
```
