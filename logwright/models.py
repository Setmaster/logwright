from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RepoStyle:
    description: str
    conventional_commits: bool
    scoped_commits: bool
    body_rate: float
    sample_size: int
    dominant_types: list[str] = field(default_factory=list)

    def signature(self) -> str:
        scope_flag = "scoped" if self.scoped_commits else "plain"
        cc_flag = "cc" if self.conventional_commits else "freeform"
        return (
            f"{cc_flag}:{scope_flag}:"
            f"{int(self.body_rate * 100)}:{','.join(self.dominant_types)}"
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommitRecord:
    sha: str
    subject: str
    body: str
    author_name: str
    author_email: str
    parent_count: int
    files: list[str]
    stats_text: str
    patch_excerpt: str

    @property
    def is_merge(self) -> bool:
        return self.parent_count > 1

    @property
    def is_revert(self) -> bool:
        return self.subject.lower().startswith("revert")

    @property
    def is_fixup(self) -> bool:
        lowered = self.subject.lower()
        return lowered.startswith("fixup!") or lowered.startswith("squash!")

    @property
    def is_bot(self) -> bool:
        lowered = f"{self.author_name} {self.author_email} {self.subject}".lower()
        markers = ("dependabot", "renovate", "release-please", "[bot]", "github actions")
        return any(marker in lowered for marker in markers)


@dataclass
class UsageStats:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    fallbacks: int = 0
    fallback_reasons: list[str] = field(default_factory=list)

    def add_tokens(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)

    def add_fallback_reason(self, reason: str) -> None:
        cleaned = reason.strip()
        if not cleaned:
            return
        if cleaned not in self.fallback_reasons:
            self.fallback_reasons.append(cleaned)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisResult:
    sha: str
    subject: str
    score: int | None
    confidence: str
    style_fit: int | None
    diff_alignment: int | None
    classification: str
    summary: str
    strengths: list[str]
    issues: list[str]
    reason_codes: list[str]
    better_message: str
    needs_human_review: bool
    special_case: str | None = None
    source: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeSummary:
    files: list[str]
    file_count: int
    additions: int
    deletions: int
    stats_text: str
    patch_excerpt: str
    keywords: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SuggestionVariant:
    label: str
    message: str
    why: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisReport:
    repo_id: str
    repo_path: str
    style: RepoStyle
    results: list[AnalysisResult]
    usage: UsageStats
    scanned_commits: int
    reword_plan: dict[str, Any] | None = None

    def scored_results(self) -> list[AnalysisResult]:
        return [result for result in self.results if result.score is not None]

    def average_score(self) -> float:
        scored = self.scored_results()
        if not scored:
            return 0.0
        return sum(result.score or 0 for result in scored) / len(scored)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_path": self.repo_path,
            "style": self.style.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "usage": self.usage.to_dict(),
            "scanned_commits": self.scanned_commits,
            "average_score": round(self.average_score(), 2),
            "reword_plan": self.reword_plan,
        }


@dataclass
class CommitCheckReport:
    repo_id: str
    repo_path: str
    style: RepoStyle
    result: AnalysisResult
    usage: UsageStats
    min_score: int
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_path": self.repo_path,
            "style": self.style.to_dict(),
            "result": self.result.to_dict(),
            "usage": self.usage.to_dict(),
            "min_score": self.min_score,
            "passed": self.passed,
        }
