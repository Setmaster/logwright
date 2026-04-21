from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from logwright.cache import CacheStore, cache_key
from logwright.gittools import (
    CONVENTIONAL_RE,
    GitError,
    cloned_remote_repo,
    detect_repo_style,
    ensure_git_repo,
    git_comment_char,
    get_commit_record,
    get_recent_commit_shas,
    infer_repo_id,
    keywords_from_diff,
    pending_commit_parent_count,
    staged_change_summary,
    text_keywords,
)
from logwright.models import (
    AnalysisReport,
    AnalysisResult,
    ChangeSummary,
    CommitCheckReport,
    CommitRecord,
    RepoStyle,
    SuggestionVariant,
    UsageStats,
)
from logwright.providers import BaseProvider, ProviderError, resolve_provider


PLACEHOLDER_SUBJECTS = {
    "wip",
    "fix",
    "fixed",
    "update",
    "updates",
    "misc",
    "changes",
    "stuff",
    "bugfix",
    "tmp",
}
GENERIC_SUBJECT_WORDS = {
    "fix",
    "fixed",
    "bug",
    "bugs",
    "update",
    "updated",
    "change",
    "changes",
    "misc",
    "stuff",
    "cleanup",
}
SCISSORS_RE = re.compile(r"^-+\s*>8\s*-+\s*$")


def detect_low_signal_subject(subject: str) -> bool:
    lowered = subject.strip().lower()
    simplified = re.sub(r"[^a-z]+", " ", lowered).strip()
    words = [word for word in simplified.split() if word]
    if simplified in PLACEHOLDER_SUBJECTS or len(words) <= 1:
        return True
    return all(word in GENERIC_SUBJECT_WORDS for word in words)


def classify_special_commit(commit: CommitRecord) -> str | None:
    if commit.is_merge:
        return "merge"
    if commit.is_revert:
        return "revert"
    if commit.is_fixup:
        return "fixup"
    if commit.is_bot:
        return "bot"
    return None


def _message_keyword_overlap(subject: str, body: str, diff_keywords: list[str]) -> int:
    message_tokens = Counter(text_keywords(f"{subject} {body}"))
    overlap = sum(1 for keyword in diff_keywords if message_tokens.get(keyword))
    return overlap


def _style_fit(subject: str, style: RepoStyle) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 6
    matches_conventional = bool(CONVENTIONAL_RE.match(subject))
    if style.conventional_commits and matches_conventional:
        score += 2
        reasons.append("matches detected conventional style")
    elif style.conventional_commits and not matches_conventional:
        score -= 2
        reasons.append("misses detected conventional style")
    if style.scoped_commits and re.match(r"^[a-z]+\(.*\):\s+\S", subject):
        score += 1
        reasons.append("uses scope like the repo")
    elif style.scoped_commits and matches_conventional:
        score -= 1
        reasons.append("omits scope used by the repo")
    return max(1, min(score, 10)), reasons


def _determine_kind(files: list[str], keywords: list[str]) -> str:
    lowered_files = [file.lower() for file in files]
    if lowered_files and all(file.endswith((".md", ".rst", ".txt")) for file in lowered_files):
        return "docs"
    if any(file.startswith(".github/workflows/") for file in lowered_files):
        return "ci"
    if any(
        file.endswith(("package-lock.json", "poetry.lock", "pnpm-lock.yaml", "uv.lock"))
        for file in lowered_files
    ):
        return "build"
    if lowered_files and all("/test" in file or file.startswith("tests/") or file.endswith("_test.py") for file in lowered_files):
        return "test"
    if any(keyword in {"add", "create", "new"} for keyword in keywords):
        return "feat"
    if any(keyword in {"refactor", "rename", "cleanup"} for keyword in keywords):
        return "refactor"
    return "fix"


def _determine_scope(files: list[str], keywords: list[str]) -> str:
    for file_path in files:
        parts = [part for part in file_path.split("/") if part and part not in {".github"}]
        if len(parts) >= 2:
            candidate = re.sub(r"[^a-z0-9_-]+", "", parts[0].lower())
            if candidate and candidate not in {"src", "lib", "app"}:
                return candidate[:20]
    if keywords:
        return re.sub(r"[^a-z0-9_-]+", "", keywords[0].lower())[:20] or "core"
    return "core"


def _subject_fragment(kind: str, scope: str, keywords: list[str]) -> str:
    keyword = keywords[0] if keywords else scope
    if kind == "docs":
        if keyword in {"readme", "roadmap", "docs", "documentation"}:
            return f"update {keyword}"
        return f"document {keyword}"
    if kind == "ci":
        return f"update {scope} workflow"
    if kind == "build":
        return f"update {scope} dependencies"
    if kind == "test":
        return f"cover {keyword} behavior"
    if kind == "feat":
        return f"add {keyword} support"
    if kind == "refactor":
        return f"refactor {keyword} flow"
    return f"improve {keyword} handling"


def heuristic_commit_message(
    *,
    files: list[str],
    keywords: list[str],
    style: RepoStyle,
    detail_level: str,
) -> str:
    kind = _determine_kind(files, keywords)
    scope = _determine_scope(files, keywords)
    fragment = _subject_fragment(kind, scope, keywords)
    if style.conventional_commits:
        if style.scoped_commits:
            subject = f"{kind}({scope}): {fragment}"
        else:
            subject = f"{kind}: {fragment}"
    else:
        subject = fragment[0].upper() + fragment[1:]

    if detail_level == "terse":
        return subject

    bullets = []
    for file_path in files[:3]:
        label = file_path.replace("\\", "/")
        lowered = label.lower()
        if lowered.startswith("tests/") or "/test" in lowered or lowered.endswith("_test.py"):
            bullets.append(f"- add or update coverage in {label}")
        elif lowered.endswith((".md", ".rst", ".txt")):
            bullets.append(f"- update documentation in {label}")
        else:
            bullets.append(f"- update {label}")
    if detail_level == "detailed":
        for keyword in keywords[:2]:
            bullets.append(f"- address {keyword}-related changes")
    return "\n".join([subject, "", *bullets]).strip()


def heuristic_analysis(commit: CommitRecord, style: RepoStyle) -> AnalysisResult:
    special_case = classify_special_commit(commit)
    if special_case:
        return AnalysisResult(
            sha=commit.sha,
            subject=commit.subject,
            score=None,
            confidence="high",
            style_fit=None,
            diff_alignment=None,
            classification="special",
            summary=f"Handled as a {special_case} commit instead of grading it like a normal authored change.",
            strengths=[],
            issues=[],
            reason_codes=[f"special_{special_case}"],
            better_message=commit.subject,
            needs_human_review=False,
            special_case=special_case,
            source="heuristic",
        )

    issues: list[str] = []
    strengths: list[str] = []
    reason_codes: list[str] = []
    score = 5

    subject = commit.subject.strip()
    body = commit.body.strip()
    subject_length = len(subject)
    diff_keywords = keywords_from_diff(commit.files, commit.patch_excerpt)
    overlap = _message_keyword_overlap(subject, body, diff_keywords)
    style_fit, style_reasons = _style_fit(subject, style)

    if detect_low_signal_subject(subject):
        issues.append("Subject is too generic to explain what changed.")
        reason_codes.append("generic_subject")
        score -= 3
    else:
        strengths.append("Subject contains more than a placeholder label.")
        reason_codes.append("subject_has_specificity")
        score += 1

    if subject_length < 12:
        issues.append("Subject is very short and likely under-explains the change.")
        reason_codes.append("short_subject")
        score -= 1
    elif subject_length <= 72:
        strengths.append("Subject length is readable in git log output.")
        reason_codes.append("subject_length_good")
        score += 1
    else:
        issues.append("Subject is long enough to get hard to scan in git tooling.")
        reason_codes.append("subject_too_long")
        score -= 1

    if body:
        strengths.append("Commit body adds extra context beyond the subject.")
        reason_codes.append("body_present")
        score += 1
    elif len(commit.files) >= 4:
        issues.append("Large multi-file change has no body to explain intent or scope.")
        reason_codes.append("body_missing")
        score -= 1

    if overlap >= 2:
        strengths.append("Message language overlaps with the changed files or identifiers.")
        reason_codes.append("diff_keywords_overlap")
        score += 2
        diff_alignment = 8
    elif overlap == 1:
        strengths.append("Message references at least one changed area.")
        reason_codes.append("partial_diff_alignment")
        score += 1
        diff_alignment = 6
    else:
        issues.append("Message does not clearly line up with the changed files or diff keywords.")
        reason_codes.append("weak_diff_alignment")
        score -= 2
        diff_alignment = 3

    score = max(1, min(score, 10))
    if score >= 8:
        classification = "good"
    elif score <= 4:
        classification = "needs_work"
    else:
        classification = "mixed"

    if score >= 7 and strengths:
        preferred = next(
            (
                item
                for item in strengths
                if any(
                    marker in item.lower()
                    for marker in ("diff", "changed", "repo", "scope", "overlap")
                )
            ),
            None,
        )
        summary = preferred or strengths[0]
    elif issues:
        summary = issues[0]
    elif strengths:
        summary = strengths[0]
    else:
        summary = "Message is serviceable but not especially informative."

    better_message = heuristic_commit_message(
        files=commit.files,
        keywords=diff_keywords,
        style=style,
        detail_level="standard",
    )

    confidence = "high" if abs(score - 5) >= 3 else "medium"
    if not diff_keywords:
        confidence = "low"

    for reason in style_reasons:
        if "misses" in reason:
            issues.append(reason[0].upper() + reason[1:] + ".")
        else:
            strengths.append(reason[0].upper() + reason[1:] + ".")

    return AnalysisResult(
        sha=commit.sha,
        subject=commit.subject,
        score=score,
        confidence=confidence,
        style_fit=style_fit,
        diff_alignment=diff_alignment,
        classification=classification,
        summary=summary,
        strengths=strengths[:4],
        issues=issues[:4],
        reason_codes=sorted(set(reason_codes)),
        better_message=better_message,
        needs_human_review=score in {4, 5, 6},
        source="heuristic",
    )


ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "style_fit": {"type": "integer", "minimum": 1, "maximum": 10},
        "diff_alignment": {"type": "integer", "minimum": 1, "maximum": 10},
        "classification": {"type": "string", "enum": ["good", "mixed", "needs_work"]},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "issues": {"type": "array", "items": {"type": "string"}},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "better_message": {"type": "string"},
        "needs_human_review": {"type": "boolean"},
    },
    "required": [
        "score",
        "confidence",
        "style_fit",
        "diff_alignment",
        "classification",
        "summary",
        "strengths",
        "issues",
        "reason_codes",
        "better_message",
        "needs_human_review",
    ],
}


SUGGESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "variants": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {
                        "type": "string",
                        "enum": ["terse", "standard", "detailed"],
                    },
                    "message": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["label", "message", "why"],
            },
        }
    },
    "required": ["variants"],
}


def _analysis_prompts(
    commit: CommitRecord,
    style: RepoStyle,
    heuristic: AnalysisResult,
) -> tuple[str, str]:
    system_prompt = (
        "You are grading git commit messages for working developers. "
        "Judge the message against the actual diff, not against a universal house style. "
        "Prefer concrete, evidence-backed critique. "
        "Return compact JSON only."
    )
    user_prompt = f"""
Repo style:
- Description: {style.description}
- Conventional commits: {style.conventional_commits}
- Scoped commits: {style.scoped_commits}
- Body rate: {style.body_rate:.2f}

Commit:
- SHA: {commit.sha}
- Subject: {commit.subject}
- Body:
{commit.body or "(no body)"}

Changed files:
{chr(10).join(f"- {item}" for item in commit.files[:12]) or "- (none)"}

Stats:
{commit.stats_text or "(none)"}

Patch excerpt:
{commit.patch_excerpt or "(none)"}

Deterministic lint signals:
- Heuristic score: {heuristic.score}
- Heuristic summary: {heuristic.summary}
- Heuristic issues: {heuristic.issues}
- Heuristic strengths: {heuristic.strengths}

Task:
Return a commit-quality critique with a 1-10 score. A good response should explain whether the
message describes the diff faithfully, whether it matches repo conventions enough, and how to
rewrite the commit message if needed.
""".strip()
    return system_prompt, user_prompt


def _suggestion_prompts(changes: ChangeSummary, style: RepoStyle) -> tuple[str, str]:
    system_prompt = (
        "You write practical git commit messages for developers. "
        "Match the repository style when sensible, but optimize for clarity and fidelity to the diff. "
        "Return JSON only."
    )
    user_prompt = f"""
Repo style:
- Description: {style.description}
- Conventional commits: {style.conventional_commits}
- Scoped commits: {style.scoped_commits}

Staged files:
{chr(10).join(f"- {item}" for item in changes.files[:12])}

Diff stats:
{changes.stats_text}

Patch excerpt:
{changes.patch_excerpt}

Keywords:
{", ".join(changes.keywords) or "(none)"}

Task:
Generate exactly three commit message variants:
- terse
- standard
- detailed

Each message should be ready to use in git commit. The detailed version may include a body.
""".strip()
    return system_prompt, user_prompt


def _merge_results(heuristic: AnalysisResult, payload: dict[str, Any]) -> AnalysisResult:
    score = int(round((heuristic.score or 5) * 0.4 + int(payload["score"]) * 0.6))
    score = max(1, min(score, 10))
    classification = payload["classification"]
    if score >= 8:
        classification = "good"
    elif score <= 4:
        classification = "needs_work"
    elif classification not in {"mixed", "good", "needs_work"}:
        classification = "mixed"

    strengths = list(dict.fromkeys(heuristic.strengths + list(payload["strengths"])))[:5]
    issues = list(dict.fromkeys(heuristic.issues + list(payload["issues"])))[:5]
    reason_codes = sorted(set(heuristic.reason_codes + list(payload["reason_codes"])))

    return AnalysisResult(
        sha=heuristic.sha,
        subject=heuristic.subject,
        score=score,
        confidence=str(payload["confidence"]),
        style_fit=int(payload["style_fit"]),
        diff_alignment=int(payload["diff_alignment"]),
        classification=classification,
        summary=str(payload["summary"]),
        strengths=strengths,
        issues=issues,
        reason_codes=reason_codes,
        better_message=str(payload["better_message"]).strip() or heuristic.better_message,
        needs_human_review=bool(payload["needs_human_review"]),
        source="llm",
    )


def _validate_analysis_payload(payload: dict[str, Any]) -> None:
    required = ANALYSIS_SCHEMA["required"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ProviderError(f"missing analysis fields: {', '.join(missing)}")


def _validate_suggestions_payload(payload: dict[str, Any]) -> list[SuggestionVariant]:
    variants = payload.get("variants")
    if not isinstance(variants, list) or len(variants) < 3:
        raise ProviderError("suggestion payload must contain three variants")
    parsed: list[SuggestionVariant] = []
    for item in variants[:3]:
        if not isinstance(item, dict):
            raise ProviderError("invalid suggestion variant")
        parsed.append(
            SuggestionVariant(
                label=str(item["label"]),
                message=str(item["message"]).strip(),
                why=str(item["why"]).strip(),
            )
        )
    return parsed


def analyze_repo(
    *,
    repo_path: Path,
    provider_name: str,
    model: str | None,
    limit: int,
    use_cache: bool,
) -> AnalysisReport:
    repo = ensure_git_repo(repo_path)
    repo_id = infer_repo_id(repo)
    style = detect_repo_style(repo)
    provider = resolve_provider(provider_name, model)
    usage = UsageStats(
        provider=provider.name if provider else "heuristic",
        model=provider.model if provider else "heuristic",
    )
    cache = CacheStore()
    shas = get_recent_commit_shas(repo, limit)
    results: list[AnalysisResult] = []
    commit_parent_counts: dict[str, int] = {}
    for sha in shas:
        commit = get_commit_record(repo, sha)
        commit_parent_counts[sha] = commit.parent_count
        heuristic = heuristic_analysis(commit, style)
        key = cache_key(
            repo_id=repo_id,
            sha=sha,
            provider=usage.provider,
            model=usage.model,
            style_signature=style.signature(),
        )
        cached = cache.load("analysis", key) if use_cache else None
        if cached:
            usage.cache_hits += 1
            results.append(AnalysisResult(**cached))
            continue
        usage.cache_misses += 1
        final = analyze_commit_record(commit=commit, style=style, provider=provider, usage=usage)
        if use_cache:
            cache.save("analysis", key, final.to_dict())
        results.append(final)

    reword_plan = build_reword_plan(results, commit_parent_counts)
    return AnalysisReport(
        repo_id=repo_id,
        repo_path=str(repo),
        style=style,
        results=results,
        usage=usage,
        scanned_commits=len(shas),
        reword_plan=reword_plan,
    )


def analyze_commit_record(
    *,
    commit: CommitRecord,
    style: RepoStyle,
    provider: BaseProvider | None,
    usage: UsageStats,
) -> AnalysisResult:
    heuristic = heuristic_analysis(commit, style)
    if not provider or heuristic.special_case is not None:
        return heuristic

    system_prompt, user_prompt = _analysis_prompts(commit, style, heuristic)
    try:
        response = provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name="commit_analysis",
            schema=ANALYSIS_SCHEMA,
        )
        _validate_analysis_payload(response.data)
        usage.add_tokens(response.input_tokens, response.output_tokens)
        return _merge_results(heuristic, response.data)
    except ProviderError as exc:
        usage.fallbacks += 1
        usage.add_fallback_reason(str(exc))
        return heuristic


def analyze_local_or_remote(
    *,
    repo_path: Path,
    url: str | None,
    provider_name: str,
    model: str | None,
    limit: int,
    use_cache: bool,
) -> AnalysisReport:
    if not url:
        return analyze_repo(
            repo_path=repo_path,
            provider_name=provider_name,
            model=model,
            limit=limit,
            use_cache=use_cache,
        )
    clone_depth = max(limit + 10, 80)
    with cloned_remote_repo(url, clone_depth) as cloned:
        return analyze_repo(
            repo_path=cloned,
            provider_name=provider_name,
            model=model,
            limit=limit,
            use_cache=use_cache,
        )


def suggestion_variants(
    *,
    changes: ChangeSummary,
    style: RepoStyle,
    provider: BaseProvider | None,
    usage: UsageStats,
) -> list[SuggestionVariant]:
    base = [
        SuggestionVariant(
            label="terse",
            message=heuristic_commit_message(
                files=changes.files,
                keywords=changes.keywords,
                style=style,
                detail_level="terse",
            ),
            why="Shortest option that still names the main change.",
        ),
        SuggestionVariant(
            label="standard",
            message=heuristic_commit_message(
                files=changes.files,
                keywords=changes.keywords,
                style=style,
                detail_level="standard",
            ),
            why="Balanced subject plus compact body for multi-file changes.",
        ),
        SuggestionVariant(
            label="detailed",
            message=heuristic_commit_message(
                files=changes.files,
                keywords=changes.keywords,
                style=style,
                detail_level="detailed",
            ),
            why="Most explicit option for later archaeology.",
        ),
    ]
    if not provider:
        return base

    system_prompt, user_prompt = _suggestion_prompts(changes, style)
    try:
        response = provider.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name="commit_suggestions",
            schema=SUGGESTION_SCHEMA,
        )
        usage.add_tokens(response.input_tokens, response.output_tokens)
        return _validate_suggestions_payload(response.data)
    except ProviderError as exc:
        usage.fallbacks += 1
        usage.add_fallback_reason(str(exc))
        return base


def choose_default_variant(variants: list[SuggestionVariant]) -> SuggestionVariant:
    for variant in variants:
        if variant.label == "standard":
            return variant
    return variants[0]


def open_in_editor(initial_text: str) -> str:
    editor = os.environ.get("GIT_EDITOR") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".commitmsg", delete=False) as handle:
        handle.write(initial_text)
        handle.flush()
        temp_path = Path(handle.name)
    try:
        subprocess.run(shlex.split(editor) + [str(temp_path)], check=True)
        return temp_path.read_text(encoding="utf-8").strip()
    finally:
        temp_path.unlink(missing_ok=True)


def run_commit(repo_path: Path, message: str) -> None:
    with tempfile.NamedTemporaryFile("w+", suffix=".commitmsg", delete=False) as handle:
        handle.write(message)
        handle.flush()
        temp_path = Path(handle.name)
    try:
        subprocess.run(
            ["git", "commit", "-F", str(temp_path)],
            cwd=repo_path,
            check=True,
        )
    finally:
        temp_path.unlink(missing_ok=True)


def write_mode(
    *,
    repo_path: Path,
    provider_name: str,
    model: str | None,
    print_only: bool,
    commit_now: bool,
) -> tuple[ChangeSummary, RepoStyle, list[SuggestionVariant], str | None]:
    changes, style, variants, _, repo = prepare_write_mode(
        repo_path=repo_path,
        provider_name=provider_name,
        model=model,
    )
    if print_only:
        return changes, style, variants, choose_default_variant(variants).message

    final_message = interactive_write_selection(
        repo_path=repo,
        variants=variants,
        commit_now=commit_now,
    )
    return changes, style, variants, final_message


def prepare_write_mode(
    *,
    repo_path: Path,
    provider_name: str,
    model: str | None,
) -> tuple[ChangeSummary, RepoStyle, list[SuggestionVariant], UsageStats, Path]:
    repo = ensure_git_repo(repo_path)
    style = detect_repo_style(repo)
    changes = staged_change_summary(repo)
    provider = resolve_provider(provider_name, model)
    usage = UsageStats(
        provider=provider.name if provider else "heuristic",
        model=provider.model if provider else "heuristic",
    )
    variants = suggestion_variants(changes=changes, style=style, provider=provider, usage=usage)
    return changes, style, variants, usage, repo


def check_pending_commit_message(
    *,
    repo_path: Path,
    message_file: Path,
    provider_name: str,
    model: str | None,
    min_score: int,
) -> CommitCheckReport:
    repo = ensure_git_repo(repo_path)
    style = detect_repo_style(repo)
    provider = resolve_provider(provider_name, model)
    usage = UsageStats(
        provider=provider.name if provider else "heuristic",
        model=provider.model if provider else "heuristic",
    )
    commit = pending_commit_record(repo, message_file.read_text(encoding="utf-8"))
    result = analyze_commit_record(commit=commit, style=style, provider=provider, usage=usage)
    passed = result.score is None or (result.score or 0) >= min_score
    return CommitCheckReport(
        repo_id=infer_repo_id(repo),
        repo_path=str(repo),
        style=style,
        result=result,
        usage=usage,
        min_score=min_score,
        passed=passed,
    )


def pending_commit_record(repo: Path, message_text: str) -> CommitRecord:
    normalized = _sanitize_commit_message(message_text, git_comment_char(repo))
    lines = normalized.splitlines()
    subject = lines[0].strip() if lines else ""
    body = "\n".join(line.rstrip() for line in lines[1:]).strip()
    try:
        changes = staged_change_summary(repo)
        parent_count = pending_commit_parent_count(repo)
        files = changes.files
        stats_text = changes.stats_text
        patch_excerpt = changes.patch_excerpt
    except GitError as exc:
        if "no staged changes found" not in str(exc):
            raise
        head_commit = get_commit_record(repo, "HEAD")
        parent_count = head_commit.parent_count
        files = head_commit.files
        stats_text = head_commit.stats_text
        patch_excerpt = head_commit.patch_excerpt

    return CommitRecord(
        sha="STAGED",
        subject=subject,
        body=body,
        author_name="",
        author_email="",
        parent_count=parent_count,
        files=files,
        stats_text=stats_text,
        patch_excerpt=patch_excerpt,
    )


def interactive_write_selection(
    *,
    repo_path: Path,
    variants: list[SuggestionVariant],
    commit_now: bool,
) -> str | None:
    default = choose_default_variant(variants)
    selection = input(
        "Choose [1-3], press Enter for standard, `e` to edit standard, or `q` to quit [2]: "
    ).strip()
    final_message: str | None
    if selection == "":
        final_message = default.message
    elif selection in {"1", "2", "3"}:
        final_message = variants[int(selection) - 1].message
    elif selection.lower() == "e":
        final_message = open_in_editor(default.message)
    elif selection.lower() == "q":
        return None
    else:
        final_message = open_in_editor(selection)

    if final_message is None or not final_message.strip():
        return None

    if commit_now:
        run_commit(repo_path, final_message)
        return final_message

    followup = input("Commit with this message now? [y/N/e]: ").strip().lower()
    if followup == "e":
        final_message = open_in_editor(final_message)
        if final_message:
            run_commit(repo_path, final_message)
    elif followup == "y":
        run_commit(repo_path, final_message)

    return final_message


def render_analysis_report(report: AnalysisReport) -> str:
    bad = [item for item in report.results if (item.score or 0) <= 4]
    good = [item for item in report.results if (item.score or 0) >= 8]
    mixed = [
        item for item in report.results if item.score is None or 4 < (item.score or 0) < 8
    ]
    vague = [item for item in report.scored_results() if "generic_subject" in item.reason_codes]
    one_word = [item for item in report.scored_results() if "short_subject" in item.reason_codes]

    lines = [
        f"Analyzed {report.scanned_commits} commits in {report.repo_id}",
        f"Detected style: {report.style.description}",
        f"Provider: {report.usage.provider} ({report.usage.model})",
        "",
        "COMMITS THAT NEED WORK",
    ]
    if bad:
        for item in bad[:8]:
            lines.extend([f'- {item.sha[:7]} "{item.subject}"', f"  Score: {item.score}/10"])
            lines.extend(_format_prefixed_block("  Issue: ", item.summary, "         "))
            lines.extend(_format_prefixed_block("  Better: ", item.better_message, "          "))
            lines.append("")
    else:
        lines.append("No commits landed in the lowest bucket.")
        lines.append("")

    lines.append("WELL-WRITTEN COMMITS")
    if good:
        for item in good[:5]:
            lines.extend(
                [
                    f'- {item.sha[:7]} "{item.subject}"',
                    f"  Score: {item.score}/10",
                    f"  Why: {item.summary}",
                    "",
                ]
            )
    else:
        lines.append("No commits landed in the strongest bucket yet.")
        lines.append("")

    special = [item for item in mixed if item.special_case]
    if special:
        lines.append("SPECIAL CASES")
        for item in special[:6]:
            lines.extend(
                [
                    f'- {item.sha[:7]} "{item.subject}"',
                    f"  Note: {item.summary}",
                    "",
                ]
            )

    if report.reword_plan:
        lines.append("REWORD PLAN")
        lines.extend(render_reword_plan(report.reword_plan))
        lines.append("")

    lines.extend(
        [
            "YOUR STATS",
            f"Average score: {report.average_score():.1f}/10",
            f"Vague commits: {len(vague)}",
            f"Very short commits: {len(one_word)}",
            f"Cache hits: {report.usage.cache_hits}",
            f"Cache misses: {report.usage.cache_misses}",
        ]
    )
    lines.extend(_render_usage_lines(report.usage))
    return "\n".join(lines)


def render_write_preview(
    changes: ChangeSummary,
    style: RepoStyle,
    variants: list[SuggestionVariant],
    usage: UsageStats,
) -> str:
    lines = [
        (
            "Analyzing staged changes... "
            f"({changes.file_count} files changed, +{changes.additions} -{changes.deletions})"
        ),
        f"Detected style: {style.description}",
        f"Provider: {usage.provider} ({usage.model})",
        "",
        "Changed files:",
    ]
    lines.extend(f"- {path}" for path in changes.files[:8])
    if len(changes.files) > 8:
        lines.append(f"- ... ({len(changes.files) - 8} more)")
    lines.append("")
    lines.append("Suggested commit messages:")
    for index, variant in enumerate(variants, start=1):
        lines.extend(
            [
                f"{index}. {variant.label}",
                variant.message,
                f"Why: {variant.why}",
                "",
            ]
        )
    lines.extend(_render_usage_lines(usage))
    return "\n".join(lines).strip()


def report_to_json(report: AnalysisReport) -> str:
    return json.dumps(report.to_dict(), indent=2)


def render_commit_check_report(report: CommitCheckReport) -> str:
    lines = [
        f"Checked pending commit message in {report.repo_id}",
        f"Detected style: {report.style.description}",
        f"Provider: {report.usage.provider} ({report.usage.model})",
        f"Subject: {report.result.subject or '(empty subject)'}",
        "",
    ]
    if report.result.score is not None:
        lines.append(
            f"Result: {'pass' if report.passed else 'fail'} "
            f"({report.result.score}/10, threshold {report.min_score})"
        )
    else:
        lines.append(f"Result: {'pass' if report.passed else 'fail'}")
    lines.extend(_format_prefixed_block("Summary: ", report.result.summary, "         "))
    if report.result.issues:
        lines.extend(_format_prefixed_block("Main issue: ", report.result.issues[0], "            "))
    lines.extend(_format_prefixed_block("Suggested message: ", report.result.better_message, "                   "))
    lines.append("")
    lines.extend(_render_usage_lines(report.usage))
    return "\n".join(lines)


def commit_check_to_json(report: CommitCheckReport) -> str:
    return json.dumps(report.to_dict(), indent=2)


def build_reword_plan(
    results: list[AnalysisResult],
    commit_parent_counts: dict[str, int],
) -> dict[str, Any] | None:
    targets = [
        item
        for item in results
        if item.score is not None and (item.score or 0) <= 4 and item.special_case is None
    ]
    if not targets:
        return None

    ordered = list(reversed(targets))
    oldest = ordered[0]
    use_root = commit_parent_counts.get(oldest.sha, 1) == 0
    return {
        "base_sha": oldest.sha,
        "use_root": use_root,
        "preserve_merges": any(count > 1 for count in commit_parent_counts.values()),
        "commits": [
            {
                "sha": item.sha,
                "subject": item.subject,
                "better_message": item.better_message,
            }
            for item in ordered
        ],
    }


def render_reword_plan(plan: dict[str, Any]) -> list[str]:
    commits = plan.get("commits") or []
    if not commits:
        return ["No weak commits were selected for rewording."]

    base_parts = ["git", "rebase", "-i"]
    if plan.get("preserve_merges"):
        base_parts.append("--rebase-merges")
    if plan.get("use_root"):
        base_parts.append("--root")
    else:
        base_parts.append(f"{plan['base_sha'][:7]}^")

    lines = [f"Start with: {' '.join(base_parts)}"]
    if plan.get("preserve_merges"):
        lines.append("Merge commits were detected in the analyzed range, so preserve topology.")
    lines.append("Mark these commits as `reword` in the interactive list:")
    for item in commits:
        lines.append(f"- reword {item['sha'][:7]} {item['subject']}")
    lines.append("Suggested replacements:")
    for item in commits:
        lines.extend(
            _format_prefixed_block(
                f"- {item['sha'][:7]} -> ",
                item["better_message"],
                "  ",
            )
        )
    return lines


def _format_prefixed_block(prefix: str, text: str, continuation_indent: str) -> list[str]:
    lines = text.splitlines() or [""]
    formatted = [f"{prefix}{lines[0]}"]
    for line in lines[1:]:
        formatted.append("" if not line else f"{continuation_indent}{line}")
    return formatted


def _render_usage_lines(usage: UsageStats) -> list[str]:
    return [
        f"Provider fallbacks: {usage.fallbacks}",
        (
            "Fallback reasons: " + "; ".join(usage.fallback_reasons[:3])
            if usage.fallback_reasons
            else "Fallback reasons: none"
        ),
        f"Model tokens: in={usage.input_tokens}, out={usage.output_tokens}",
    ]


def _sanitize_commit_message(message_text: str, comment_char: str) -> str:
    kept_lines: list[str] = []
    for raw_line in message_text.splitlines():
        line = raw_line.rstrip()
        if _is_scissors_line(line, comment_char):
            break
        if comment_char and line.lstrip().startswith(comment_char):
            continue
        kept_lines.append(line)

    while kept_lines and not kept_lines[0].strip():
        kept_lines.pop(0)
    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()
    return "\n".join(kept_lines)


def _is_scissors_line(line: str, comment_char: str) -> bool:
    candidate = line.strip()
    if not candidate:
        return False
    if comment_char and candidate.startswith(comment_char):
        candidate = candidate[len(comment_char) :].strip()
    return bool(SCISSORS_RE.match(candidate))
