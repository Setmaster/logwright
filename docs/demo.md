# Demo Transcript

These are real terminal transcripts captured from the current implementation. Output varies by
provider, model, and repo contents, but the flows below reflect the shipped behavior.

## Focused README demo

This is the same narrow companion flow shown in the README GIF: analyze a vague commit against its
diff with the default provider, then surface a reword plan. Daily use usually starts with
`--write --print-only` or the commit-msg hook.

```text
$ logwright --analyze --repo /tmp/logwright-gif-demo --limit 2 --no-cache
Analyzed 2 commits in /tmp/logwright-gif-demo
Detected style: Short-form free-form subjects
Provider: anthropic (claude-sonnet-4-6)

COMMITS THAT NEED WORK
- 80a8eb0 "fixed bug"
  Score: 2/10
  Issue: The message 'fixed bug' is maximally vague and does not describe what was actually done: a new auth module with a token validation function was created. This isn't even a bug fix — it's new code (file is created, not modified). The message misleads reviewers about both the nature and content of the change.
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

## Hook install

```text
$ python3 -m logwright --install-commit-msg-hook --repo /tmp/logwright-doc-hook
Installed commit-msg hook in /tmp/logwright-doc-hook
Hook path: /tmp/logwright-doc-hook/.git/hooks/commit-msg
Provider: heuristic
Minimum score: 5/10
Configured local core.hooksPath: /tmp/logwright-doc-hook/.git/hooks
Runs: logwright --commit-msg-file "$1" --provider heuristic --min-score 5 --repo /tmp/logwright-doc-hook
Created new hook.
```

## Analyze mode

```text
$ python3 -m logwright --analyze --provider openai --repo /tmp/logwright-doc-analyze --limit 4 --no-cache
Analyzed 4 commits in /tmp/logwright-doc-analyze
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
  Why: The message matches the diff well: it documents adding a new top-level README with initial local setup steps, and it follows Conventional Commits with a clear docs prefix. The only mild mismatch is that the body says "Document the first-run local setup commands" while the README content is more of a brief setup guide than explicit commands, but that's minor.

COMMITS IN THE MIDDLE
- bd1ea2d "test: cover expired token normalization"
  Score: 7/10
  Note: The message is mostly good and matches the repo's Conventional Commits style, but it is a bit broader than the actual diff. The patch adds a specific test for normalize_token('expired'), while the message refers to an 'expired token normalization' regression more generally, which is close but not exact.

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

## Gemini analyze smoke

```text
$ python3 -m logwright --analyze --provider gemini --repo /tmp/logwright-doc-analyze --limit 4 --no-cache
Analyzed 4 commits in /tmp/logwright-doc-analyze
Detected style: Conventional Commits
Provider: gemini (gemini-2.5-flash)

COMMITS THAT NEED WORK
- 6ee8851 "fixed bug"
  Score: 2/10
  Issue: The commit message 'fixed bug' is too generic and does not adhere to the Conventional Commits style required by the repository. While it broadly indicates a fix, it fails to describe the specific bug or the nature of the fix, which is to handle 'expired' tokens by returning an empty string.
  Better: fix: Handle 'expired' token by returning empty string

          Previously, an 'expired' token would be normalized to 'expired'. This change ensures that if the cleaned token is 'expired', an empty string is returned instead, preventing potential issues with downstream logic expecting a valid token.

WELL-WRITTEN COMMITS
- 1342605 "docs: add README setup steps"
  Score: 9/10
  Why: The commit message accurately describes the changes, adheres to Conventional Commits, and provides useful context. The subject is concise and the body elaborates effectively.

COMMITS IN THE MIDDLE
- bd1ea2d "test: cover expired token normalization"
  Score: 7/10
  Note: The commit message accurately describes the change as a test for expired token normalization and adheres to Conventional Commits style. The body provides good context.

- 4a176ab "refactor: normalize auth tokens"
  Score: 7/10
  Note: The commit message adheres to Conventional Commits style and accurately reflects the creation of a new function for normalizing auth tokens. However, the lack of a body misses an opportunity to explain the 'why' behind this new utility.

REWORD PLAN
Start with: git rebase -i 6ee8851^
Mark these commits as `reword` in the interactive list:
- reword 6ee8851 fixed bug
Suggested replacements:
- 6ee8851 -> fix: Handle 'expired' token by returning empty string

  Previously, an 'expired' token would be normalized to 'expired'. This change ensures that if the cleaned token is 'expired', an empty string is returned instead, preventing potential issues with downstream logic expecting a valid token.

YOUR STATS
Average score: 6.2/10
Vague commits: 1
Very short commits: 1
Cache hits: 0
Cache misses: 4
Model tokens: in=1780, out=1210
Estimated API cost: $0.0064 (standard text-token pricing for gemini-2.5-flash)
```

## Write mode

```text
$ python3 -m logwright --write --print-only --provider openai --repo /tmp/logwright-doc-write-history
Analyzing staged changes... (1 files changed, +1 -0)
Detected style: Conventional Commits
Provider: openai (gpt-5.4-mini)

Changed files:
- docs/setup.md

Suggested commit messages:
1. terse
docs: add setup guide
Why: Short Conventional Commit that matches the new documentation file and setup keyword.

2. standard
docs: add setup documentation
Why: Clear, conventional summary of the added setup doc without extra detail.

3. detailed
docs: add setup documentation

Add an initial setup page with install steps for getting started.
Why: Includes a concise body that reflects the single-line documentation addition.

Model tokens: in=253, out=112
Estimated API cost: $0.0007 (standard text-token pricing for gpt-5.4-mini)
```

## Anthropic write smoke

```text
$ python3 -m logwright --write --print-only --provider anthropic --repo /tmp/logwright-doc-write
Analyzing staged changes... (1 files changed, +1 -0)
Detected style: No repo history yet
Provider: anthropic (claude-sonnet-4-6)

Changed files:
- docs/setup.md

Suggested commit messages:
1. terse
Add setup docs
Why: Minimal description of the new file's purpose.

2. standard
Add initial setup documentation
Why: Clear, concise summary that describes what was added and its intent.

3. detailed
Add setup documentation with install steps

Create docs/setup.md as the initial setup guide. Currently contains
install steps as a placeholder, to be expanded with full instructions.
Why: Includes the file path, current content, and context that it's a starting point for further documentation.

Model tokens: in=368, out=188
Estimated API cost: $0.0039 (standard text-token pricing for claude-sonnet-4-6)
```

## Gemini write smoke

```text
$ python3 -m logwright --write --print-only --provider gemini --repo /tmp/logwright-doc-write
Analyzing staged changes... (1 files changed, +1 -0)
Detected style: No repo history yet
Provider: gemini (gemini-2.5-flash)

Changed files:
- docs/setup.md

Suggested commit messages:
1. terse
Add setup docs
Why: This is a terse commit message, suitable for a quick commit where the changes are self-explanatory or part of a larger series.

2. standard
Add initial setup documentation
Why: This is a standard commit message, providing a clear and concise summary of the change.

3. detailed
Add initial setup documentation

This commit introduces the basic setup documentation file. It outlines the initial steps required to get the project running.
Why: This is a detailed commit message, including a body to provide more context and explanation for the change, which is useful for new files or significant additions.

Model tokens: in=226, out=158
Estimated API cost: $0.0008 (standard text-token pricing for gemini-2.5-flash)
```

## Commit-msg validation

```text
$ python3 -m logwright --commit-msg-file /tmp/logwright-doc-commitmsg/COMMIT_EDITMSG --provider heuristic --repo /tmp/logwright-doc-commitmsg
Checked pending commit message in /tmp/logwright-doc-commitmsg
Detected style: No repo history yet
Provider: heuristic (heuristic)
Subject: wip

Result: fail (1/10, threshold 5)
Summary: Subject is too generic to explain what changed.
Suggested message: Update readme

                   - update documentation in README.md

Model tokens: in=0, out=0
Estimated API cost: $0.0000 (heuristic mode)
```
