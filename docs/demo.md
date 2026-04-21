# Demo Transcript

These are real terminal transcripts captured from the current implementation. Output varies by
provider, model, and repo contents, but the flows below reflect the shipped behavior.

## Focused README demo

This is the same narrow flow shown in the README GIF: analyze a vague commit against its diff with
the default provider, then surface a reword plan.

```text
$ logwright --analyze --repo /tmp/logwright-gif-demo --limit 2 --no-cache
Analyzed 2 commits in /tmp/logwright-gif-demo
Detected style: Short-form free-form subjects
Provider: anthropic (claude-sonnet-4-6)

COMMITS THAT NEED WORK
- 8b98e7f "fixed bug"
  Score: 2/10
  Issue: The message 'fixed bug' is completely uninformative and does not describe what was actually done. The diff shows a new file src/auth.py being created with a validate_token function — this is not a bug fix, it's a new feature addition. The message is both factually wrong and too vague.
  Better: add token validation function to auth module

WELL-WRITTEN COMMITS
No commits landed in the strongest bucket yet.

REWORD PLAN
Start with: git rebase -i 8b98e7f^
Mark these commits as `reword` in the interactive list:
- reword 8b98e7f fixed bug
Suggested replacements:
- 8b98e7f -> add token validation function to auth module

YOUR STATS
Average score: 4.0/10
Vague commits: 1
Very short commits: 1
Cache hits: 0
Cache misses: 2
Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=1452, out=469
Estimated API cost: $0.0114 (standard text-token pricing for claude-sonnet-4-6)
```

## Hook install

```text
$ python3 -m logwright --install-commit-msg-hook --repo /tmp/logwright-demo-repo
Installed commit-msg hook in /tmp/logwright-demo-repo
Hook path: /tmp/logwright-demo-repo/.git/hooks/commit-msg
Provider: heuristic
Minimum score: 5/10
Configured local core.hooksPath: /tmp/logwright-demo-repo/.git/hooks
Runs: logwright --commit-msg-file "$1" --provider heuristic --min-score 5 --repo /tmp/logwright-demo-repo
Created new hook.
```

## Analyze mode

```text
$ python3 -m logwright --analyze --provider openai --limit 5 --no-cache
Analyzed 5 commits in https://github.com/Setmaster/logwright.git
Detected style: Conventional Commits
Provider: openai (gpt-5.4-mini)

COMMITS THAT NEED WORK
- c703f15 "feat: add commit-msg validation and reword plans"
  Score: 4/10
  Issue: The subject is conventional and readable, but it under-describes a very large change and only partially matches the diff. The patch adds commit-msg validation plus several related improvements, so the message should mention the hook/validation work and likely split or broaden the second clause.
  Better: feat: add commit-msg validation and reword suggestions

          Add a --commit-msg-file mode for checking pending commit messages against staged changes, including hook-friendly report rendering and JSON output. Rework weak-commit guidance to produce actionable reword plans, and update docs and demos to cover the new flows.

WELL-WRITTEN COMMITS
No commits landed in the strongest bucket yet.

REWORD PLAN
Start with: git rebase -i c703f15^
Mark these commits as `reword` in the interactive list:
- reword c703f15 feat: add commit-msg validation and reword plans
Suggested replacements:
- c703f15 -> feat: add commit-msg validation and reword suggestions

  Add a --commit-msg-file mode for checking pending commit messages against staged changes, including hook-friendly report rendering and JSON output. Rework weak-commit guidance to produce actionable reword plans, and update docs and demos to cover the new flows.

YOUR STATS
Average score: 5.2/10
Vague commits: 0
Very short commits: 0
Cache hits: 0
Cache misses: 5
Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=7643, out=1304
Estimated API cost: $0.0116 (standard text-token pricing for gpt-5.4-mini)
```

## Write mode

```text
$ python3 -m logwright --write --print-only --provider openai --repo /tmp/logwright-write-demo
Analyzing staged changes... (1 files changed, +3 -0)
Detected style: Conventional Commits
Provider: openai (gpt-5.4-mini)

Changed files:
- docs/setup.md

Suggested commit messages:
1. terse
docs: add setup guide
Why: Shortest conventional commit that accurately describes the new documentation file.

2. standard
docs: add setup instructions
Why: Clear conventional commit message matching the added setup documentation content.

3. detailed
docs: add setup guide

Document the initial setup steps in docs/setup.md.

Include a brief note to run the installer.
Why: Provides a fuller summary and body while staying faithful to the small docs-only change.

Provider fallbacks: 0
Fallback reasons: none
Model tokens: in=264, out=121
Estimated API cost: $0.0007 (standard text-token pricing for gpt-5.4-mini)
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
Estimated API cost: $0.0000 (heuristic mode)
```
