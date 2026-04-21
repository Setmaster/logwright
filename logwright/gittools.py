from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from logwright.models import ChangeSummary, CommitRecord, RepoStyle


CONVENTIONAL_TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(?P<scope>\([^)]+\))?(?P<bang>!)?:\s+\S"
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
IGNORED_KEYWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "into",
    "none",
    "not",
    "only",
    "return",
    "that",
    "the",
    "their",
    "then",
    "this",
    "true",
    "use",
    "using",
    "false",
    "with",
}
AUTO_COMMENT_HINTS = (
    "Please enter the commit message",
    "On branch ",
    "Changes to be committed:",
    "Changes not staged for commit:",
    "Untracked files:",
    "Initial commit",
    "No commits yet",
    "nothing to commit",
    "All conflicts fixed but you are still merging.",
    "It looks like you may be committing a merge.",
    "Date:",
)


class GitError(RuntimeError):
    pass


def require_git() -> None:
    if shutil.which("git") is None:
        raise GitError("git is required but was not found in PATH")


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    require_git()
    try:
        process = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError(f"repository path does not exist: {repo}") from exc
    if check and process.returncode != 0:
        stderr = process.stderr.strip() or process.stdout.strip()
        raise GitError(f"git {' '.join(args)} failed: {stderr}")
    return process.stdout


def ensure_git_repo(path: Path) -> Path:
    top_level = run_git(path, "rev-parse", "--show-toplevel").strip()
    return Path(top_level)


def _resolve_git_path(repo: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return repo / path


def git_path(repo: Path, relative_path: str) -> Path:
    raw = run_git(repo, "rev-parse", "--git-path", relative_path).strip()
    return _resolve_git_path(repo, raw)


def git_dir(repo: Path) -> Path:
    raw = run_git(repo, "rev-parse", "--absolute-git-dir").strip()
    return Path(raw)


def infer_repo_id(repo: Path) -> str:
    remote = run_git(repo, "remote", "get-url", "origin", check=False).strip()
    if remote:
        return remote
    return str(repo.resolve())


def head_exists(repo: Path) -> bool:
    return bool(run_git(repo, "rev-parse", "-q", "--verify", "HEAD", check=False).strip())


def head_commit_message(repo: Path) -> str | None:
    if not head_exists(repo):
        return None
    return run_git(repo, "log", "-1", "--format=%s%n%n%b").strip()


@contextmanager
def cloned_remote_repo(url: str, depth: int) -> Iterator[Path]:
    tempdir = Path(tempfile.mkdtemp(prefix="logwright-"))
    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", str(depth), url, str(tempdir)],
            check=True,
            capture_output=True,
            text=True,
        )
        yield tempdir
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip()
        raise GitError(f"git clone failed: {stderr}") from exc
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def get_recent_commit_shas(repo: Path, limit: int) -> list[str]:
    output = run_git(repo, "rev-list", f"--max-count={limit}", "HEAD").strip()
    return [line for line in output.splitlines() if line]


def _truncate_section(lines: list[str], max_lines: int) -> list[str]:
    if len(lines) <= max_lines:
        return lines
    keep = lines[: max_lines - 1]
    keep.append(f"... ({len(lines) - len(keep)} more lines omitted)")
    return keep


def excerpt_patch(patch_text: str, *, max_files: int = 6, max_lines_per_file: int = 28) -> str:
    lines = patch_text.splitlines()
    if not lines:
        return ""
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git ") and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    if not sections:
        return "\n".join(_truncate_section(lines, max_lines_per_file))

    trimmed: list[str] = []
    for section in sections[:max_files]:
        trimmed.extend(_truncate_section(section, max_lines_per_file))
    omitted = len(sections) - min(len(sections), max_files)
    if omitted > 0:
        trimmed.append(f"... ({omitted} more file diffs omitted)")
    return "\n".join(trimmed)


def get_commit_record(repo: Path, sha: str) -> CommitRecord:
    fmt = "%H%x1f%s%x1f%b%x1f%an%x1f%ae%x1f%P"
    raw_meta = run_git(repo, "show", "--quiet", f"--format={fmt}", sha).split("\x1f")
    if len(raw_meta) < 6:
        raise GitError(f"unexpected git show metadata for {sha}")
    _, subject, body, author_name, author_email, parents = raw_meta[:6]
    files_output = run_git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha)
    stats_text = run_git(repo, "show", "--stat", "--format=", "--summary", sha).strip()
    patch = run_git(repo, "show", "--format=", "--unified=2", "--no-ext-diff", sha)
    files = [line for line in files_output.splitlines() if line]
    parent_count = len([part for part in parents.split() if part])
    return CommitRecord(
        sha=sha,
        subject=subject.strip(),
        body=body.strip(),
        author_name=author_name.strip(),
        author_email=author_email.strip(),
        parent_count=parent_count,
        files=files,
        stats_text=stats_text,
        patch_excerpt=excerpt_patch(patch),
    )


def detect_repo_style(repo: Path, sample_size: int = 25) -> RepoStyle:
    raw = run_git(repo, "log", f"--max-count={sample_size}", "--format=%s%x1f%b%x1e", check=False)
    entries = [entry for entry in raw.split("\x1e") if entry.strip()]
    if not entries:
        return RepoStyle(
            description="No repo history yet",
            conventional_commits=False,
            scoped_commits=False,
            body_rate=0.0,
            sample_size=0,
            dominant_types=[],
        )
    conventional = 0
    scoped = 0
    body_count = 0
    type_counter: Counter[str] = Counter()
    subject_lengths: list[int] = []
    for entry in entries:
        parts = entry.split("\x1f", 1)
        subject = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else ""
        if not subject:
            continue
        subject_lengths.append(len(subject))
        match = CONVENTIONAL_RE.match(subject)
        if match:
            conventional += 1
            if match.group("scope"):
                scoped += 1
            type_counter[match.group("type")] += 1
        if body:
            body_count += 1

    sample_count = max(len(subject_lengths), 1)
    conventional_rate = conventional / sample_count
    scoped_rate = scoped / sample_count
    body_rate = body_count / sample_count
    avg_subject_length = sum(subject_lengths) / sample_count if subject_lengths else 0

    if conventional_rate >= 0.7 and scoped_rate >= 0.5:
        description = "Conventional Commits with scopes"
    elif conventional_rate >= 0.7:
        description = "Conventional Commits"
    elif body_rate >= 0.45:
        description = "Free-form subjects with frequent bodies"
    elif avg_subject_length <= 40:
        description = "Short-form free-form subjects"
    else:
        description = "Free-form commit messages"

    dominant_types = [name for name, _ in type_counter.most_common(3)]
    return RepoStyle(
        description=description,
        conventional_commits=conventional_rate >= 0.7,
        scoped_commits=scoped_rate >= 0.5,
        body_rate=body_rate,
        sample_size=sample_count,
        dominant_types=dominant_types,
    )


def git_comment_char(repo: Path, message_text: str | None = None) -> str:
    raw = run_git(repo, "config", "--get", "core.commentChar", check=False).strip()
    if not raw:
        return "#"
    if raw == "auto":
        detected = _detect_comment_char_from_message(message_text or "")
        return detected or "#"
    return raw[0]


def _detect_comment_char_from_message(message_text: str) -> str | None:
    suffix_block = _comment_suffix_block(message_text)
    if suffix_block is None:
        return None
    marker, block = suffix_block
    if any(any(line.startswith(prefix) for prefix in AUTO_COMMENT_HINTS) for line in block):
        return marker
    if any(":" in line for line in block):
        return marker
    if any(not line for line in block):
        return marker
    if any("\t" in line for line in block):
        return marker
    return None


def _comment_suffix_block(message_text: str) -> tuple[str, list[str]] | None:
    marker: str | None = None
    block: list[str] = []
    for raw_line in reversed(message_text.splitlines()):
        if not raw_line.strip():
            if block:
                break
            continue
        stripped = raw_line.lstrip()
        current_marker = stripped[:1]
        if not current_marker:
            if block:
                break
            continue
        marker_char = current_marker[0]
        remainder = stripped[1:]
        if marker_char.isalnum() or marker_char in {"_", "-", "*"}:
            if block:
                break
            continue
        if remainder and not remainder[:1].isspace():
            if block:
                break
            continue
        if marker is None:
            marker = marker_char
        elif marker_char != marker:
            break
        block.append(remainder.lstrip())

    if not marker or len(block) < 2:
        return None
    return marker, list(reversed(block))


def pending_commit_parent_count(repo: Path) -> int:
    merge_head_raw = run_git(repo, "rev-parse", "--git-path", "MERGE_HEAD", check=False).strip()
    merge_parent_count = 0
    if merge_head_raw:
        merge_head_path = _resolve_git_path(repo, merge_head_raw)
        if merge_head_path.exists():
            merge_parent_count = len(
                [line for line in merge_head_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            )
    if merge_parent_count:
        return 1 + merge_parent_count
    return 1 if head_exists(repo) else 0


def _keywords_from_files(files: list[str]) -> list[str]:
    tokens: Counter[str] = Counter()
    ignored = {
        "src",
        "lib",
        "test",
        "tests",
        "spec",
        "specs",
        "main",
        "index",
        "init",
        "logwright",
        "github",
        "workflows",
    }
    for file_path in files:
        for part in re.split(r"[/_.-]+", file_path):
            lowered = part.lower()
            if (
                len(lowered) < 3
                or lowered.isdigit()
                or lowered in ignored
                or lowered in IGNORED_KEYWORDS
            ):
                continue
            tokens[lowered] += 1
    return [token for token, _ in tokens.most_common(8)]


def keywords_from_diff(files: list[str], patch_excerpt: str) -> list[str]:
    tokens = Counter(_keywords_from_files(files))
    patterns = (
        r"^[+\-]\s*(?:def|class|function|const|let|var|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^[+\-]\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::|=|\()",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, patch_excerpt, re.MULTILINE):
            token = match.group(1).lower()
            if len(token) >= 3 and token not in IGNORED_KEYWORDS:
                tokens[token] += 2
    return [token for token, _ in tokens.most_common(10)]


def staged_change_summary(repo: Path) -> ChangeSummary:
    files_output = run_git(repo, "diff", "--cached", "--name-only").strip()
    files = [line for line in files_output.splitlines() if line]
    if not files:
        raise GitError("no staged changes found")

    numstat_output = run_git(repo, "diff", "--cached", "--numstat").strip()
    additions = 0
    deletions = 0
    for line in numstat_output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_raw, del_raw = parts[0], parts[1]
        additions += 0 if add_raw == "-" else int(add_raw)
        deletions += 0 if del_raw == "-" else int(del_raw)

    stats_text = run_git(repo, "diff", "--cached", "--stat").strip()
    patch = run_git(repo, "diff", "--cached", "--unified=2", "--no-ext-diff")
    patch_excerpt = excerpt_patch(patch)
    keywords = keywords_from_diff(files, patch_excerpt)
    return ChangeSummary(
        files=files,
        file_count=len(files),
        additions=additions,
        deletions=deletions,
        stats_text=stats_text,
        patch_excerpt=patch_excerpt,
        keywords=keywords,
    )


def text_keywords(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in WORD_RE.finditer(text))
        if token not in IGNORED_KEYWORDS
    ]
