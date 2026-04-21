# logwright

`logwright` is a terminal commit-message critic and writer. It reviews commit history against the
actual diffs, suggests stronger messages from staged changes, and can block weak pending commits
through a repo-local `commit-msg` hook.

The core idea is simple: commit messages should be judged against the change itself, not in
isolation. Daily use usually starts with `--write --print-only` or the hook. The focused demo
below shows the companion analyze-and-reword flow.

![logwright terminal demo](https://raw.githubusercontent.com/Setmaster/logwright/v0.1.1/docs/logwright-demo.gif)

[Demo Transcript](https://github.com/Setmaster/logwright/blob/v0.1.1/docs/demo.md) · [Roadmap](https://github.com/Setmaster/logwright/blob/v0.1.1/ROADMAP.md) · [License](https://github.com/Setmaster/logwright/blob/v0.1.1/LICENSE)

## Highlights

- Grade commit messages against the diff, not just the subject line in isolation.
- Detect repo conventions such as Conventional Commits and scoped subjects, then score against that local style.
- Generate commit message suggestions directly from `git diff --cached`.
- Produce reword-ready cleanup plans for weak commits instead of only reporting a score.
- Check pending commit messages before they land, including amend and reword flows.
- Install a repo-local `commit-msg` hook instead of leaving setup as manual shell glue.
- Surface provider fallback reasons and estimated API cost in the terminal output.
- Stay usable in deterministic heuristic mode when no LLM key is configured.

## Install

Python 3.11+ and `git` are required.

Install directly from GitHub:

```bash
pip install git+https://github.com/Setmaster/logwright.git@v0.1.1
```

Or install from a local checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1`.

For local development:

```bash
pip install -e .
```

## Quickstart

Generate a commit message from staged changes:

```bash
logwright --write --print-only
```

Review recent history:

```bash
logwright --analyze --limit 10
```

Install a repo-local hook for future commits:

```bash
logwright --install-commit-msg-hook
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

Install a repo-local `commit-msg` hook (defaults to heuristic mode):

```bash
logwright --install-commit-msg-hook
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
`--install-commit-msg-hook`, and `--version`.

## Providers

`logwright` supports:

- `anthropic`
- `openai`
- `gemini`
- `auto`
- `heuristic`

`auto` prefers Anthropic when `ANTHROPIC_API_KEY` is present, then OpenAI when `OPENAI_API_KEY` is present, then Gemini when `GEMINI_API_KEY` is present, and finally falls back to heuristics.

For `--install-commit-msg-hook`, omitting `--provider` installs a repo-local heuristic hook by
default. Pass `--provider anthropic`, `--provider openai`, `--provider gemini`, or an explicit
`--provider auto` if you want model-backed hook checks.

`logwright` auto-loads a repo-local `.env` file from the target repo root before provider
resolution, so `--repo /path/to/repo` uses `/path/to/repo/.env` rather than the caller's current
working directory. No API key is required for heuristic mode.

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

## Verified provider coverage (2026-04-21)

Representative transcripts live in the [Demo Transcript](https://github.com/Setmaster/logwright/blob/v0.1.1/docs/demo.md). The current build was exercised on these provider paths:

- Anthropic: analyze, write
- OpenAI: analyze, write
- Gemini: analyze, write
- Heuristic: analyze, `--commit-msg-file`, `--install-commit-msg-hook`

If a provider call fails at runtime, `logwright` falls back to heuristics, labels the provider
line accordingly, and prints the fallback reason. When no fallback occurs, those lines are omitted
to keep the report compact.

## Cost estimates

Terminal output includes estimated cost for the default models below, using the current standard
text-token rates as of 2026-04-21:

- `gpt-5.4-mini`: $0.75 / 1M input, $4.50 / 1M output
- `claude-sonnet-4-6`: $3.00 / 1M input, $15.00 / 1M output
- `gemini-2.5-flash`: $0.54 / 1M input, $4.50 / 1M output

## Representative output

```text
$ logwright --analyze --repo /path/to/repo --limit 2 --no-cache
Analyzed 2 commits in /path/to/repo
Detected style: Short-form free-form subjects
Provider: anthropic (claude-sonnet-4-6)

COMMITS THAT NEED WORK
- 80a8eb0 "fixed bug"
  Score: 2/10
  Issue: The message 'fixed bug' is maximally vague and does not describe what was actually done: a new auth module with a token validation function was created. This isn't even a bug fix - it's new code (file is created, not modified). The message misleads reviewers about both the nature and content of the change.
  Better: add token validation to auth module

WELL-WRITTEN COMMITS
No commits landed in the strongest bucket yet.

REWORD PLAN
Start with: git rebase -i 80a8eb0^
Mark these commits as `reword` in the interactive list:
- reword 80a8eb0 fixed bug
Suggested replacements:
- 80a8eb0 -> add token validation to auth module

YOUR STATS
Average score: 4.0/10
Vague commits: 1
Very short commits: 1
Cache hits: 0
Cache misses: 2
Model tokens: in=1456, out=490
Estimated API cost: $0.0117 (standard text-token pricing for claude-sonnet-4-6)
```

See the [Demo Transcript](https://github.com/Setmaster/logwright/blob/v0.1.1/docs/demo.md) for
broader Anthropic, OpenAI, Gemini, hook, and commit-msg flows.

## Hook usage

Install the default heuristic `commit-msg` hook:

```bash
logwright --install-commit-msg-hook
```

That generates the equivalent of:

```sh
#!/bin/sh
logwright --commit-msg-file "$1" --provider heuristic --min-score 5 --repo /path/to/repo
```

Key behaviors:

- The generated hook uses the current Python interpreter path.
- When Logwright is run from a source checkout instead of an installed package, the hook also pins that checkout on `PYTHONPATH`.
- If Git is inheriting a shared hooks directory, Logwright sets a local `core.hooksPath` first so installation stays repo-local.
- If the score falls below the threshold, Logwright exits nonzero and prints a suggested replacement message.
- If there is no staged diff, Logwright falls back to the current `HEAD` commit when Git is reusing the existing message during amend and reword flows.

If you want model-backed hook checks instead, pass `--provider anthropic`, `--provider openai`,
or `--provider gemini` explicitly so latency and cost are an intentional choice:

```bash
logwright --install-commit-msg-hook --provider openai --min-score 6 --force
```

## Automation

Use `--json` when Logwright needs to feed CI, scripts, or another tool:

```bash
logwright --analyze --json > logwright-report.json
```

Current analyze payloads include:

- `repo_id`, `repo_path`, `style`, `scanned_commits`, and `average_score`
- `results[]` entries with `sha`, `subject`, `score`, `summary`, `better_message`, and `reason_codes`
- `usage` with provider, model, token counts, fallback details, and estimated cost when pricing is known

Schema excerpt from a representative run:

```json
{
  "repo_id": "/path/to/repo",
  "scanned_commits": 4,
  "average_score": 6.0,
  "results": [
    {
      "sha": "6ee88512a90d02df896b2a8f2648c563ade548f1",
      "subject": "fixed bug",
      "score": 2,
      "summary": "The message is too generic and does not describe the actual change in `src/auth.py`, which adds special handling for expired tokens by returning an empty string. It also misses the repo’s Conventional Commits style.",
      "better_message": "fix(auth): return empty string for expired tokens",
      "reason_codes": [
        "conventional_commits_mismatch",
        "generic_subject",
        "low_diff_specificity"
      ]
    }
  ],
  "usage": {
    "provider": "openai",
    "model": "gpt-5.4-mini",
    "estimated_cost_usd": 0.005737
  }
}
```

## Design Decisions

- Diff-aware grading first. A message is only useful relative to what actually changed.
- Hybrid scoring. Deterministic lint catches obvious low-signal subjects cheaply; LLM judgment handles fidelity and rewrite quality.
- Repo-style calibration. Conventional Commit usage is detected instead of imposed globally.
- Transparent fallback. If no model key is available or a provider call fails, the flow stays usable and reports why.
- Explicit hook installation. The tool can install its own `commit-msg` hook instead of leaving setup as manual shell glue.
- Local caching. Results are cached under `~/.cache/logwright` by commit SHA, repo identity, style signature, provider, and model.
- Actionable cleanup. Weak commits produce a reword-ready plan instead of only a report card.
- Hook-friendly validation. Pending commit messages can be checked against the staged diff, or against `HEAD` when Git is reusing the current commit during amend and reword flows.
- Cost visibility. Terminal output includes an estimated API cost based on current standard text-token pricing for the supported default models.
- Remote support via shallow clone. It is simple, portable, and preserves access to full git metadata without special-casing GitHub.

## Limitations

- Anthropic currently uses JSON-only prompting plus local validation rather than tool calling.
- Remote analysis uses shallow cloning rather than the GitHub API.
- The heuristic write suggestions are intentionally conservative and can read generic without an LLM provider.
- Cost estimates cover standard text-token billing only; they do not include provider-side caching, Batch discounts, long-context premiums, grounding, or tool-call fees.
- Cost estimates are only available for the built-in default model set and known snapshot aliases.
- HTML export is not implemented yet.

## Pricing sources

```text
OpenAI API pricing: https://openai.com/api/pricing/
Anthropic Claude pricing: https://platform.claude.com/docs/en/about-claude/pricing
Google Gemini 2.5 Flash: https://ai.google.dev/gemini-api/docs/pricing
```

## Development

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Run directly from source:

```bash
python3 -m logwright --help
```

## License

MIT. See [LICENSE](https://github.com/Setmaster/logwright/blob/v0.1.1/LICENSE).
