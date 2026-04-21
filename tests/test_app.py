import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from logwright import __version__
from logwright.app import (
    build_reword_plan,
    check_pending_commit_message,
    detect_low_signal_subject,
    heuristic_analysis,
    heuristic_commit_message,
    pending_commit_record,
    render_analysis_report,
    render_commit_check_report,
    render_reword_plan,
    render_write_preview,
)
from logwright.cli import build_parser
from logwright.env import load_env_file
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
from logwright.providers import (
    GeminiProvider,
    default_anthropic_model,
    default_openai_model,
    resolve_provider,
)


def build_style() -> RepoStyle:
    return RepoStyle(
        description="Conventional Commits with scopes",
        conventional_commits=True,
        scoped_commits=True,
        body_rate=0.6,
        sample_size=20,
        dominant_types=["fix", "feat"],
    )


class LogwrightHeuristicTests(unittest.TestCase):
    def test_detect_low_signal_subject(self) -> None:
        self.assertTrue(detect_low_signal_subject("wip"))
        self.assertTrue(detect_low_signal_subject("fix"))
        self.assertFalse(detect_low_signal_subject("fix(auth): refresh expired token"))

    def test_heuristic_analysis_flags_generic_subject(self) -> None:
        commit = CommitRecord(
            sha="abc123",
            subject="fixed bug",
            body="",
            author_name="Victor",
            author_email="victor@example.com",
            parent_count=1,
            files=["src/auth/session.py", "tests/test_session.py"],
            stats_text="2 files changed, 10 insertions(+), 4 deletions(-)",
            patch_excerpt=(
                "diff --git a/src/auth/session.py b/src/auth/session.py\n"
                "@@ -1,2 +1,3 @@\n"
                "-raise TokenError\n"
                "+raise RefreshTokenExpired\n"
                "diff --git a/tests/test_session.py b/tests/test_session.py\n"
                "+def test_refresh_token_expired(): pass\n"
            ),
        )
        result = heuristic_analysis(commit, build_style())
        self.assertIsNotNone(result.score)
        self.assertLessEqual(result.score or 0, 4)
        self.assertIn("generic_subject", result.reason_codes)

    def test_heuristic_commit_message_matches_style(self) -> None:
        message = heuristic_commit_message(
            files=["src/auth/session.py", "tests/test_session.py"],
            keywords=["auth", "refresh", "token"],
            style=build_style(),
            detail_level="terse",
        )
        self.assertTrue(message.startswith("fix("))

    def test_heuristic_commit_message_omits_scope_when_repo_style_is_unscoped(self) -> None:
        style = RepoStyle(
            description="Conventional Commits",
            conventional_commits=True,
            scoped_commits=False,
            body_rate=0.4,
            sample_size=10,
            dominant_types=["feat", "fix"],
        )
        message = heuristic_commit_message(
            files=["README.md"],
            keywords=["roadmap"],
            style=style,
            detail_level="terse",
        )
        self.assertTrue(message.startswith("docs:"))
        self.assertNotIn("(", message.split(":", 1)[0])


class LogwrightEnvTests(unittest.TestCase):
    def test_default_models_match_documented_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual("claude-sonnet-4-6", default_anthropic_model())
            self.assertEqual("gpt-5.4-mini", default_openai_model())

    def test_load_env_file_sets_missing_values_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                'ANTHROPIC_API_KEY=anthropic-test\n'
                'export GEMINI_API_KEY="gemini-test"\n'
                "OPENAI_API_KEY=openai-from-file\n",
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "already-set"},
                clear=False,
            ):
                loaded = load_env_file(env_path)
                self.assertTrue(loaded)
                self.assertEqual("anthropic-test", os.environ["ANTHROPIC_API_KEY"])
                self.assertEqual("gemini-test", os.environ["GEMINI_API_KEY"])
                self.assertEqual("already-set", os.environ["OPENAI_API_KEY"])

    def test_auto_provider_uses_gemini_when_only_gemini_key_exists(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "gemini-test",
                "LOGWRIGHT_GEMINI_MODEL": "gemini-2.5-flash",
            },
            clear=True,
        ):
            provider = resolve_provider("auto")
            self.assertIsInstance(provider, GeminiProvider)
            self.assertEqual("gemini-2.5-flash", provider.model)


class LogwrightCliTests(unittest.TestCase):
    def test_version_flag_reports_package_version(self) -> None:
        parser = build_parser()
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as context:
                parser.parse_args(["--version"])
        self.assertEqual(0, context.exception.code)
        self.assertEqual(f"logwright {__version__}\n", output.getvalue())


class LogwrightReportTests(unittest.TestCase):
    def test_build_reword_plan_orders_commits_oldest_first(self) -> None:
        results = [
            AnalysisResult(
                sha="newer123",
                subject="feat: vague change",
                score=4,
                confidence="medium",
                style_fit=7,
                diff_alignment=4,
                classification="needs_work",
                summary="Too vague.",
                strengths=[],
                issues=["Too vague."],
                reason_codes=["generic_subject"],
                better_message="feat: clarify newer change",
                needs_human_review=True,
            ),
            AnalysisResult(
                sha="older123",
                subject="fix: old vague change",
                score=3,
                confidence="medium",
                style_fit=7,
                diff_alignment=3,
                classification="needs_work",
                summary="Too vague.",
                strengths=[],
                issues=["Too vague."],
                reason_codes=["generic_subject"],
                better_message="fix: clarify older change",
                needs_human_review=True,
            ),
        ]
        plan = build_reword_plan(results, {"newer123": 1, "older123": 1})
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual("older123", plan["base_sha"])
        self.assertEqual(["older123", "newer123"], [item["sha"] for item in plan["commits"]])

    def test_render_reword_plan_preserves_merges_when_present(self) -> None:
        plan = build_reword_plan(
            [
                AnalysisResult(
                    sha="abc1234",
                    subject="fix: vague message",
                    score=4,
                    confidence="medium",
                    style_fit=6,
                    diff_alignment=4,
                    classification="needs_work",
                    summary="Too vague.",
                    strengths=[],
                    issues=["Too vague."],
                    reason_codes=["generic_subject"],
                    better_message="fix: clarify auth refresh handling",
                    needs_human_review=True,
                )
            ],
            {"abc1234": 1, "merge123": 2},
        )
        assert plan is not None
        rendered = "\n".join(render_reword_plan(plan))
        self.assertIn("--rebase-merges", rendered)
        self.assertIn("preserve topology", rendered)

    def test_render_analysis_report_includes_fallback_reason(self) -> None:
        usage = UsageStats(provider="gemini", model="gemini-2.5-flash", fallbacks=1)
        usage.add_fallback_reason("provider did not return valid JSON")
        report = AnalysisReport(
            repo_id="https://example.com/repo.git",
            repo_path="/tmp/repo",
            style=build_style(),
            results=[
                AnalysisResult(
                    sha="abc1234",
                    subject="fixed bug",
                    score=3,
                    confidence="medium",
                    style_fit=5,
                    diff_alignment=3,
                    classification="needs_work",
                    summary="Too vague.",
                    strengths=[],
                    issues=["Too vague."],
                    reason_codes=["generic_subject"],
                    better_message="fix: clarify auth refresh handling",
                    needs_human_review=True,
                )
            ],
            usage=usage,
            scanned_commits=1,
            reword_plan={
                "base_sha": "abc1234",
                "use_root": False,
                "commits": [
                    {
                        "sha": "abc1234",
                        "subject": "fixed bug",
                        "better_message": "fix: clarify auth refresh handling",
                    }
                ],
            },
        )
        rendered = render_analysis_report(report)
        self.assertIn("Fallback reasons: provider did not return valid JSON", rendered)
        self.assertIn("REWORD PLAN", rendered)


class LogwrightPreCommitTests(unittest.TestCase):
    def test_pending_commit_record_parses_subject_and_body(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(
                repo,
                (
                    "docs: update readme\n\n"
                    "Add installation note.\n"
                    "# Please enter the commit message for your changes.\n"
                ),
            )
            self.assertEqual("docs: update readme", record.subject)
            self.assertEqual("Add installation note.", record.body)
            self.assertEqual(["README.md"], record.files)
            self.assertEqual(0, record.parent_count)

    def test_pending_commit_record_detects_merge_parent_count(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "docs: add readme"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("hello\nworld\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / ".git" / "MERGE_HEAD").write_text("1234567890abcdef1234567890abcdef12345678\n", encoding="utf-8")
            record = pending_commit_record(repo, "merge docs\n")
            self.assertEqual(2, record.parent_count)

    def test_check_pending_commit_message_uses_heuristics_without_provider(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            message_file = repo / "COMMIT_EDITMSG"
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            message_file.write_text("docs: update readme\n", encoding="utf-8")
            report = check_pending_commit_message(
                repo_path=repo,
                message_file=message_file,
                provider_name="heuristic",
                model=None,
                min_score=5,
            )
            self.assertTrue(report.passed)
            self.assertEqual("heuristic", report.usage.provider)

    def test_check_pending_commit_message_uses_head_context_for_message_only_amend(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            message_file = repo / "COMMIT_EDITMSG"
            subprocess = __import__("subprocess")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "docs: add readme"], cwd=repo, check=True, capture_output=True, text=True)
            message_file.write_text("docs: add readme\n", encoding="utf-8")
            report = check_pending_commit_message(
                repo_path=repo,
                message_file=message_file,
                provider_name="heuristic",
                model=None,
                min_score=5,
            )
            self.assertTrue(report.passed)
            self.assertEqual("docs: add readme", report.result.subject)
            self.assertIn("README", report.result.better_message)

    def test_render_commit_check_report_keeps_blank_lines_clean(self) -> None:
        report = CommitCheckReport(
            repo_id="/tmp/repo",
            repo_path="/tmp/repo",
            style=build_style(),
            result=AnalysisResult(
                sha="STAGED",
                subject="wip",
                score=2,
                confidence="high",
                style_fit=4,
                diff_alignment=2,
                classification="needs_work",
                summary="Too vague.",
                strengths=[],
                issues=["Subject is too generic to explain what changed."],
                reason_codes=["generic_subject"],
                better_message="docs: update readme\n\n- update README.md",
                needs_human_review=False,
            ),
            usage=UsageStats(provider="heuristic", model="heuristic"),
            min_score=5,
            passed=False,
        )
        rendered = render_commit_check_report(report)
        self.assertIn("Suggested message: docs: update readme", rendered)
        self.assertIn("\n\n                   - update README.md", rendered)
        self.assertNotIn("\n                   \n", rendered)

    def test_render_write_preview_includes_usage_details(self) -> None:
        usage = UsageStats(provider="openai", model="gpt-5.4-mini", fallbacks=1)
        usage.add_fallback_reason("HTTP 503: upstream overloaded")
        preview = render_write_preview(
            ChangeSummary(
                files=["README.md"],
                file_count=1,
                additions=2,
                deletions=0,
                stats_text=" README.md | 2 ++",
                patch_excerpt="+hello\n+world\n",
                keywords=["readme"],
            ),
            RepoStyle(
                description="No repo history yet",
                conventional_commits=False,
                scoped_commits=False,
                body_rate=0.0,
                sample_size=0,
                dominant_types=[],
            ),
            [
                SuggestionVariant(label="terse", message="Update readme", why="Short."),
                SuggestionVariant(label="standard", message="Update readme", why="Balanced."),
                SuggestionVariant(label="detailed", message="Update readme\n\n- update README.md", why="Most detail."),
            ],
            usage,
        )
        self.assertIn("Provider: openai (gpt-5.4-mini)", preview)
        self.assertIn("Provider fallbacks: 1", preview)
        self.assertIn("Fallback reasons: HTTP 503: upstream overloaded", preview)


if __name__ == "__main__":
    unittest.main()
