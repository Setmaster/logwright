# logwright

`logwright` is a CLI tool for grading git commit messages against their actual diffs and helping write better ones from staged changes.

## What it does

- Analyze recent commits in the current repository or a remote git URL.
- Score commit messages against the change itself, not just the subject line in isolation.
- Detect local repo conventions such as Conventional Commits and scoped subjects.
- Generate commit message suggestions from `git diff --cached`.
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

Use heuristic mode only:

```bash
logwright --analyze --provider heuristic
```

## Providers

`logwright` supports:

- `anthropic`
- `openai`
- `auto`
- `heuristic`

`auto` prefers Anthropic when `ANTHROPIC_API_KEY` is present, then OpenAI when `OPENAI_API_KEY` is present, and finally falls back to heuristics.

Environment variables:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
```

Optional model overrides:

```bash
export LOGWRIGHT_ANTHROPIC_MODEL=claude-3-7-sonnet-latest
export LOGWRIGHT_OPENAI_MODEL=gpt-4o-mini
```

Or pass a model explicitly:

```bash
logwright --analyze --provider openai --model gpt-4o-mini
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
Model tokens: in=0, out=0
```

## Design Decisions

- Diff-aware grading first. A message is only useful relative to what actually changed.
- Hybrid scoring. Deterministic lint catches obvious low-signal subjects cheaply; LLM judgment handles fidelity and rewrite quality.
- Repo-style calibration. Conventional Commit usage is detected instead of imposed globally.
- Provider fallback. If no model key is available or a provider call fails, analysis still runs.
- Local caching. Results are cached under `~/.cache/logwright` by commit SHA, repo identity, style signature, provider, and model.
- Remote support via shallow clone. It is simple, portable, and preserves access to full git metadata without special-casing GitHub.

## Limitations

- Anthropic currently uses JSON-only prompting plus local validation rather than tool calling.
- Remote analysis uses shallow cloning rather than the GitHub API.
- The heuristic write suggestions are intentionally conservative and can read generic without an LLM provider.
- HTML export, hook integration, and rebase-plan generation are not implemented yet.
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
