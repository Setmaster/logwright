# Demo Transcript

These are real terminal transcripts captured from the current implementation. Output varies by
provider, model, and repo contents, but the flows below reflect the shipped behavior.

## Analyze mode

```text
$ python3 -m logwright --analyze --provider openai --limit 5 --no-cache
Analyzed 5 commits in https://github.com/Setmaster/logwright.git
Detected style: Conventional Commits
Provider: openai (gpt-5.4-mini)

COMMITS THAT NEED WORK
- c699c0b "feat: add diff-aware commit critic CLI"
  Score: 4/10
  Issue: The subject follows Conventional Commits and is readable, but it only partially describes a very large implementation change. The diff adds a full CLI application, git/diff tooling, caching, provider/model abstractions, tests, and documentation, not just a commit critic CLI. With no body, the message leaves the main scope and functionality under-described.
  Better: feat: add diff-aware commit analysis CLI

          Add a CLI for scoring commit messages against staged or committed diffs, generating message suggestions, detecting repository commit style, and caching provider results. Include git helpers, provider/model abstractions, tests, and packaging updates.

WELL-WRITTEN COMMITS
- 31ffd42 "feat: add version flag and roadmap"
  Score: 8/10
  Why: The subject fits the repo's Conventional Commits style and accurately captures the main user-visible change: adding a --version flag. It is slightly incomplete because the diff also adds a new ROADMAP.md and updates README/tests, which the message doesn't mention, but that omission is acceptable for a concise feat commit.

REWORD PLAN
Start with: git rebase -i c699c0b^
Mark these commits as `reword` in the interactive list:
- reword c699c0b feat: add diff-aware commit critic CLI
Suggested replacements:
- c699c0b -> feat: add diff-aware commit analysis CLI

  Add a CLI for scoring commit messages against staged or committed diffs, generating message suggestions, detecting repository commit style, and caching provider results. Include git helpers, provider/model abstractions, tests, and packaging updates.

YOUR STATS
Average score: 5.4/10
Vague commits: 1
Very short commits: 0
Cache hits: 0
Cache misses: 5
Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=6690, out=1306
```

## Write mode

```text
$ python3 -m logwright --write --print-only --provider anthropic --repo /tmp/demo-repo
Analyzing staged changes... (1 files changed, +2 -0)
Detected style: No repo history yet
Provider: anthropic (claude-sonnet-4-6)

Changed files:
- app.py

Suggested commit messages:
1. terse
Add app.py
Why: Minimal message noting the new file was added.

2. standard
Initialize app.py with alpha and beta entries
Why: Concise description of what was added and its initial content.

3. detailed
Add initial app.py with placeholder content

Create app.py as the application entry point containing two initial
lines: 'alpha' and 'beta'. This establishes the base file for further
development.
Why: Explains the purpose of the file and describes its initial content in context.

Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=361, out=197
```

## Commit-msg validation

```text
$ python3 -m logwright --commit-msg-file /tmp/demo-repo/COMMIT_EDITMSG --provider heuristic --repo /tmp/demo-repo
Checked pending commit message in /tmp/demo-repo
Detected style: No repo history yet
Provider: heuristic (heuristic)
Subject: wip

Result: fail (1/10, threshold 5)
Summary: Subject is too generic to explain what changed.
Main issue: Subject is too generic to explain what changed.
Suggested message: Update readme

                   - update documentation in README.md

Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=0, out=0
```
