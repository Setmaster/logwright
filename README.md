# logwright

`logwright` is a CLI tool for turning staged changes into better commit messages and grading existing git history against the actual diffs.

Daily use starts with `--write --print-only` or the commit-msg hook. The focused demo below shows the companion analyze-and-reword flow.

![logwright terminal demo](https://raw.githubusercontent.com/Setmaster/logwright/v0.1.0/docs/logwright-demo.gif)

[Demo Transcript](https://github.com/Setmaster/logwright/blob/v0.1.0/docs/demo.md) · [Roadmap](https://github.com/Setmaster/logwright/blob/v0.1.0/ROADMAP.md) · [License](https://github.com/Setmaster/logwright/blob/v0.1.0/LICENSE)

## Highlights

- Score commit messages against the change itself, not just the subject line in isolation.
- Detect local repo conventions such as Conventional Commits and scoped subjects.
- Generate actionable reword plans for weak commits.
- Check pending commit messages before they land, suitable for `commit-msg` hooks and amend/reword flows.
- Install a repo-local `commit-msg` hook instead of hand-writing the shell script.
- Surface provider fallback reasons when a live model call fails and heuristics take over.
- Estimate provider cost from token usage for the default shipping models.
- Generate commit message suggestions from `git diff --cached`.
- Analyze recent commits in the current repository or a remote git URL.
- Fall back to deterministic heuristics when no LLM key is configured.

## Install

Python 3.11+ and `git` are required.

Install directly from GitHub:

```bash
pip install git+https://github.com/Setmaster/logwright.git@v0.1.0
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

With staged changes ready, the fastest daily-use path is generating a commit message:

```bash
logwright --write --print-only
```

For a focused history pass, start smaller than the default 50-commit scan:

```bash
logwright --analyze --limit 10
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

`logwright` auto-loads a repo-local `.env` file before provider resolution, so you can keep API keys in the project root without exporting them into your shell.

## Local smoke-test snapshot (2026-04-21)

These entries reflect one local live run per provider path on that date. The checked-in demo
transcript is intentionally representative rather than exhaustive, but it now includes Anthropic,
OpenAI, and Gemini analyze runs, Anthropic/OpenAI/Gemini write runs, and heuristic hook /
commit-msg flows.

| Provider | Analyze mode | Write suggestions | Notes |
|---|---|---|---|
| Anthropic | Locally smoke-tested | Locally smoke-tested | Uses JSON prompting with local schema validation |
| OpenAI | Locally smoke-tested | Locally smoke-tested | Uses Responses API structured outputs |
| Gemini | Locally smoke-tested | Locally smoke-tested | Uses structured JSON output with `thinkingBudget: 0` and transient retries |
| Heuristic | Locally smoke-tested | Locally smoke-tested | No API key required |

If a provider call fails at runtime, `logwright` falls back to heuristics, labels the provider line accordingly, and prints the fallback reason in the terminal output. When no fallback occurs, those lines are omitted to keep the report compact.

Estimated API cost uses the current standard text-token rates for the default shipping models as
of 2026-04-21:

- `gpt-5.4-mini`: $0.75 / 1M input, $4.50 / 1M output
- `claude-sonnet-4-6`: $3.00 / 1M input, $15.00 / 1M output
- `gemini-2.5-flash`: $0.54 / 1M input, $4.50 / 1M output

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
$ logwright --analyze --provider openai --repo /path/to/repo --limit 4 --no-cache
Analyzed 4 commits in /path/to/repo
Detected style: Conventional Commits
Provider: openai (gpt-5.4-mini)

COMMITS THAT NEED WORK
- 6ee8851 "fixed bug"
  Score: 1/10
  Issue: The message is too vague for the actual change. The diff adds a special case in token normalization for the literal value 'expired', but 'fixed bug' gives no clue what bug was fixed or where. It also does not follow Conventional Commits style.
  Better: fix(auth): treat 'expired' tokens as invalid in normalize_token

WELL-WRITTEN COMMITS
- 1342605 "docs: add README setup steps"
  Score: 8/10
  Why: The message matches the diff well: it documents adding a new top-level README with initial local setup steps, and it follows Conventional Commits with a clear docs prefix.

COMMITS IN THE MIDDLE
- bd1ea2d "test: cover expired token normalization"
  Score: 7/10
  Note: The message is mostly good and matches the repo's Conventional Commits style, but it is a bit broader than the actual diff.

- 4a176ab "refactor: normalize auth tokens"
  Score: 7/10
  Note: The subject follows Conventional Commits and roughly matches the new auth-token helper, but it is a bit generic for a brand-new file containing only a simple normalization function.

REWORD PLAN
Start with: git rebase -i 6ee8851^
Mark these commits as `reword` in the interactive list:
- reword 6ee8851 fixed bug
Suggested replacements:
- 6ee8851 -> fix(auth): treat 'expired' tokens as invalid in normalize_token

YOUR STATS
Average score: 5.8/10
Vague commits: 1
Very short commits: 1
Cache hits: 0
Cache misses: 4
Model tokens: in=2064, out=973
Estimated API cost: $0.0059 (standard text-token pricing for gpt-5.4-mini)
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

## Hook usage

Install a minimal heuristic `commit-msg` hook:

```bash
logwright --install-commit-msg-hook
```

That generates the equivalent of:

```sh
#!/bin/sh
logwright --commit-msg-file "$1" --provider heuristic --min-score 5 --repo /path/to/repo
```

The generated hook uses the current Python interpreter path. When Logwright is being run from a
source checkout instead of an installed package, it also pins that checkout on `PYTHONPATH` so
the hook keeps working from other repositories.

If Git is currently inheriting a shared hooks directory, Logwright sets a local `core.hooksPath`
for the target repo before writing the hook so the installation stays repo-local.

If the score falls below the threshold, `logwright` exits nonzero and prints a suggested
replacement message based on the staged diff.

If there is no staged diff, `logwright` falls back to the current `HEAD` commit when Git is
reusing the existing commit message for amend and reword flows.

If you want model-backed hook checks instead, pass `--provider anthropic`, `--provider openai`,
or `--provider gemini` explicitly during installation so latency and cost are an intentional
choice:

```bash
logwright --install-commit-msg-hook --provider openai --min-score 6 --force
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

MIT. See [LICENSE](https://github.com/Setmaster/logwright/blob/v0.1.0/LICENSE).
