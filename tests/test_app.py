import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
    install_commit_msg_hook,
    interactive_write_selection,
    pending_commit_record,
    render_analysis_report,
    render_commit_check_report,
    render_hook_install_result,
    render_reword_plan,
    render_write_preview,
)
from logwright.cli import _resolve_env_repo_path, build_parser, main
from logwright.env import load_env_file
from logwright.gittools import GitError, git_dir, git_path, run_git
from logwright.models import (
    AnalysisReport,
    AnalysisResult,
    ChangeSummary,
    CommitCheckReport,
    CommitRecord,
    HookInstallResult,
    RepoStyle,
    SuggestionVariant,
    UsageStats,
)
from logwright.pricing import estimate_usage_cost
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


def init_test_repo(repo: Path, *, configure_user: bool = False) -> None:
    subprocess = __import__("subprocess")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "core.hooksPath", ".git/hooks"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    if configure_user:
        subprocess.run(
            ["git", "config", "user.name", "Tester"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "tester@example.com"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
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

    def test_write_mode_rejects_json_flag(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                main(["--write", "--json"])
        self.assertEqual(2, context.exception.code)
        self.assertIn("--json is not supported with --write", stderr.getvalue())

    def test_write_mode_rejects_commit_with_print_only(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as context:
                main(["--write", "--print-only", "--commit"])
        self.assertEqual(2, context.exception.code)
        self.assertIn("--commit cannot be used together with --print-only", stderr.getvalue())

    def test_resolve_env_repo_path_uses_repo_root_for_nested_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            nested = repo / "nested" / "child"
            init_test_repo(repo)
            nested.mkdir(parents=True)
            self.assertEqual(repo, _resolve_env_repo_path(nested, allow_non_git=False))

    def test_help_groups_mode_specific_flags(self) -> None:
        help_text = build_parser().format_help()
        self.assertIn("Modes:", help_text)
        self.assertIn("Analyze options:", help_text)
        self.assertIn("Write options:", help_text)
        self.assertIn("Commit-msg and hook options:", help_text)
        self.assertIn("Examples:", help_text)

    def test_write_mode_requires_interactive_terminal_without_print_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            __import__("subprocess").run(
                ["git", "add", "README.md"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            stderr = io.StringIO()
            with patch("sys.stdin.isatty", return_value=False), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as context:
                    main(["--write", "--repo", str(repo)])
        self.assertEqual(2, context.exception.code)
        self.assertIn("--write requires an interactive terminal", stderr.getvalue())


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

    def test_render_analysis_report_omits_empty_fallback_block(self) -> None:
        report = AnalysisReport(
            repo_id="https://example.com/repo.git",
            repo_path="/tmp/repo",
            style=build_style(),
            results=[
                AnalysisResult(
                    sha="abc1234",
                    subject="docs: update readme",
                    score=8,
                    confidence="high",
                    style_fit=8,
                    diff_alignment=8,
                    classification="good",
                    summary="Specific and aligned.",
                    strengths=["Specific."],
                    issues=[],
                    reason_codes=[],
                    better_message="docs: update readme",
                    needs_human_review=False,
                )
            ],
            usage=UsageStats(provider="anthropic", model="claude-sonnet-4-6"),
            scanned_commits=1,
        )
        rendered = render_analysis_report(report)
        self.assertNotIn("Provider fallbacks:", rendered)
        self.assertNotIn("Fallback reasons:", rendered)
        self.assertIn("Model tokens: in=0, out=0", rendered)

    def test_render_analysis_report_shows_middle_bucket(self) -> None:
        report = AnalysisReport(
            repo_id="https://example.com/repo.git",
            repo_path="/tmp/repo",
            style=build_style(),
            results=[
                AnalysisResult(
                    sha="abc1234",
                    subject="docs: update readme",
                    score=6,
                    confidence="medium",
                    style_fit=7,
                    diff_alignment=6,
                    classification="mixed",
                    summary="Message references at least one changed area.",
                    strengths=["Readable."],
                    issues=[],
                    reason_codes=["partial_diff_alignment"],
                    better_message="docs: update readme",
                    needs_human_review=True,
                )
            ],
            usage=UsageStats(provider="anthropic", model="claude-sonnet-4-6"),
            scanned_commits=1,
        )
        rendered = render_analysis_report(report)
        self.assertIn("COMMITS IN THE MIDDLE", rendered)
        self.assertIn('abc1234 "docs: update readme"', rendered)

    def test_render_analysis_report_provider_line_shows_fallback(self) -> None:
        usage = UsageStats(provider="openai", model="gpt-5.4-mini", fallbacks=1)
        usage.add_fallback_reason("HTTP 503: overloaded")
        report = AnalysisReport(
            repo_id="https://example.com/repo.git",
            repo_path="/tmp/repo",
            style=build_style(),
            results=[],
            usage=usage,
            scanned_commits=0,
        )
        rendered = render_analysis_report(report)
        self.assertIn("Provider: openai (gpt-5.4-mini), fell back to heuristic", rendered)

    def test_render_analysis_report_keeps_special_cases_out_of_bad_bucket(self) -> None:
        report = AnalysisReport(
            repo_id="https://example.com/repo.git",
            repo_path="/tmp/repo",
            style=build_style(),
            results=[
                AnalysisResult(
                    sha="merge123",
                    subject="Merge branch 'main'",
                    score=None,
                    confidence="high",
                    style_fit=None,
                    diff_alignment=None,
                    classification="special_case",
                    summary="Merge commits are reported separately.",
                    strengths=[],
                    issues=[],
                    reason_codes=[],
                    better_message="",
                    needs_human_review=False,
                    special_case="merge",
                )
            ],
            usage=UsageStats(provider="heuristic", model="heuristic"),
            scanned_commits=1,
        )
        rendered = render_analysis_report(report)
        self.assertIn("SPECIAL CASES", rendered)
        self.assertNotIn("Score: None/10", rendered)

    def test_usage_stats_to_dict_includes_estimated_cost(self) -> None:
        usage = UsageStats(provider="openai", model="gpt-5.4-mini")
        usage.add_tokens(1_000, 2_000)
        payload = usage.to_dict()
        self.assertEqual(0.00975, payload["estimated_cost_usd"])
        self.assertIn("standard text-token pricing", payload["cost_note"])

    def test_estimate_usage_cost_handles_heuristic_mode(self) -> None:
        payload = estimate_usage_cost(
            provider="heuristic",
            model="heuristic",
            input_tokens=0,
            output_tokens=0,
        )
        self.assertEqual(0.0, payload["estimated_cost_usd"])
        self.assertEqual("heuristic mode", payload["cost_note"])

    def test_estimate_usage_cost_handles_snapshot_aliases(self) -> None:
        anthropic = estimate_usage_cost(
            provider="anthropic",
            model="claude-sonnet-4-6-20250420",
            input_tokens=1_000,
            output_tokens=2_000,
        )
        gemini = estimate_usage_cost(
            provider="gemini",
            model="gemini-2.5-flash-preview-04-17",
            input_tokens=1_000,
            output_tokens=2_000,
        )
        self.assertIsNotNone(anthropic["estimated_cost_usd"])
        self.assertIsNotNone(gemini["estimated_cost_usd"])


class LogwrightPreCommitTests(unittest.TestCase):
    def test_pending_commit_record_parses_subject_and_body(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
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
            init_test_repo(repo, configure_user=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "docs: add readme"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / "README.md").write_text("hello\nworld\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            (repo / ".git" / "MERGE_HEAD").write_text("1234567890abcdef1234567890abcdef12345678\n", encoding="utf-8")
            record = pending_commit_record(repo, "merge docs\n")
            self.assertEqual(2, record.parent_count)

    def test_pending_commit_record_stops_at_scissors_marker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(
                repo,
                (
                    "wip\n\n"
                    "# ------------------------ >8 ------------------------\n"
                    "diff --git a/README.md b/README.md\n"
                    "+hello\n"
                ),
            )
            self.assertEqual("wip", record.subject)
            self.assertEqual("", record.body)

    def test_pending_commit_record_resolves_auto_comment_char_from_message(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
            subprocess.run(
                ["git", "config", "core.commentChar", "auto"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(
                repo,
                (
                    "#123 keep hash subject\n\n"
                    "Body line.\n"
                    "; Please enter the commit message for your changes.\n"
                    "; On branch main\n"
                ),
            )
            self.assertEqual("#123 keep hash subject", record.subject)
            self.assertEqual("Body line.", record.body)

    def test_pending_commit_record_detects_auto_comment_suffix_block_without_english_hints(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
            subprocess.run(
                ["git", "config", "core.commentChar", "auto"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(
                repo,
                (
                    "#123 keep hash subject\n\n"
                    "Body line.\n"
                    ";\n"
                    ";\tmodified: README.md\n"
                    ";\tmodified: notes.txt\n"
                ),
            )
            self.assertEqual("#123 keep hash subject", record.subject)
            self.assertEqual("Body line.", record.body)

    def test_pending_commit_record_ignores_user_hint_like_body_before_auto_comment_block(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
            subprocess.run(
                ["git", "config", "core.commentChar", "auto"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(
                repo,
                (
                    "#123 keep hash subject\n\n"
                    "# Date: 2026-04-21 release marker\n"
                    "Body line.\n"
                    "; Please enter the commit message for your changes.\n"
                    "; On branch main\n"
                ),
            )
            self.assertEqual("#123 keep hash subject", record.subject)
            self.assertEqual("# Date: 2026-04-21 release marker\nBody line.", record.body)

    def test_pending_commit_record_handles_empty_initial_commit_without_head(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            record = pending_commit_record(repo, "chore: bootstrap repo\n")
            self.assertEqual("chore: bootstrap repo", record.subject)
            self.assertEqual(0, record.parent_count)
            self.assertEqual([], record.files)
            self.assertEqual("", record.patch_excerpt)

    def test_pending_commit_record_uses_empty_context_for_allow_empty_commit_with_history(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo, configure_user=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "docs: add readme"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(repo, "chore: record release marker\n")
            self.assertEqual("chore: record release marker", record.subject)
            self.assertEqual(1, record.parent_count)
            self.assertEqual([], record.files)
            self.assertEqual("", record.patch_excerpt)

    def test_pending_commit_record_uses_head_context_for_amend_buffer(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo, configure_user=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "docs: add readme"], cwd=repo, check=True, capture_output=True, text=True)
            record = pending_commit_record(
                repo,
                (
                    "docs: revise readme\n\n"
                    "# Data: Tue Apr 21 09:46:17 2026 -0400\n"
                    "# Em branch main\n"
                ),
            )
            self.assertEqual("docs: revise readme", record.subject)
            self.assertEqual(1, record.parent_count)
            self.assertEqual(["README.md"], record.files)
            self.assertIn("README", record.patch_excerpt)

    def test_check_pending_commit_message_uses_heuristics_without_provider(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            message_file = repo / "COMMIT_EDITMSG"
            subprocess = __import__("subprocess")
            init_test_repo(repo, configure_user=True)
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
            init_test_repo(repo, configure_user=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "docs: add readme"], cwd=repo, check=True, capture_output=True, text=True)
            message_file.write_text(
                "docs: add readme\n\n# Date: Tue Apr 21 09:46:17 2026 -0400\n# On branch main\n",
                encoding="utf-8",
            )
            report = check_pending_commit_message(
                repo_path=repo,
                message_file=message_file,
                provider_name="heuristic",
                model=None,
                min_score=5,
            )
            self.assertTrue(report.passed)
            self.assertEqual("docs: add readme", report.result.subject)

    def test_check_pending_commit_message_does_not_reuse_head_diff_for_same_message_empty_commit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            message_file = repo / "COMMIT_EDITMSG"
            subprocess = __import__("subprocess")
            init_test_repo(repo, configure_user=True)
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
            self.assertEqual("docs: add readme", report.result.subject)
            self.assertNotIn("README", report.result.better_message)

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

    def test_render_commit_check_report_uses_first_distinct_main_issue(self) -> None:
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
                summary="Subject is too generic to explain what changed.",
                strengths=[],
                issues=[
                    "Subject is too generic to explain what changed.",
                    "Subject is too short to be helpful.",
                ],
                reason_codes=["generic_subject"],
                better_message="docs: update readme",
                needs_human_review=False,
            ),
            usage=UsageStats(provider="heuristic", model="heuristic"),
            min_score=5,
            passed=False,
        )
        rendered = render_commit_check_report(report)
        self.assertIn("Summary: Subject is too generic to explain what changed.", rendered)
        self.assertIn("Main issue: Subject is too short to be helpful.", rendered)

    def test_render_commit_check_report_omits_suggested_message_on_pass(self) -> None:
        report = CommitCheckReport(
            repo_id="/tmp/repo",
            repo_path="/tmp/repo",
            style=build_style(),
            result=AnalysisResult(
                sha="STAGED",
                subject="docs: add readme",
                score=8,
                confidence="high",
                style_fit=8,
                diff_alignment=8,
                classification="well_written",
                summary="Clear and specific.",
                strengths=["Specific subject"],
                issues=[],
                reason_codes=[],
                better_message="docs: update readme",
                needs_human_review=False,
            ),
            usage=UsageStats(provider="heuristic", model="heuristic"),
            min_score=5,
            passed=True,
        )
        rendered = render_commit_check_report(report)
        self.assertIn("Result: pass (8/10, threshold 5)", rendered)
        self.assertNotIn("Suggested message:", rendered)

    def test_render_write_preview_includes_usage_details(self) -> None:
        usage = UsageStats(provider="openai", model="gpt-5.4-mini", fallbacks=1)
        usage.add_fallback_reason("HTTP 503: upstream overloaded")
        usage.add_tokens(1_000, 2_000)
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
        self.assertIn("Estimated API cost: $0.0097", preview)

    def test_render_write_preview_omits_empty_fallback_block(self) -> None:
        usage = UsageStats(provider="openai", model="gpt-5.4-mini")
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
        self.assertNotIn("Provider fallbacks:", preview)
        self.assertNotIn("Fallback reasons:", preview)
        self.assertIn("Model tokens: in=0, out=0", preview)

    def test_interactive_write_selection_uses_explicit_custom_path(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=["c", "seed text", "n"]), patch(
            "logwright.app.open_in_editor",
            return_value="docs: custom",
        ) as open_editor:
            result = interactive_write_selection(
                repo_path=Path("/tmp/repo"),
                variants=variants,
                commit_now=False,
            )
        self.assertEqual(("docs: custom", False), result)
        open_editor.assert_called_once_with("seed text")

    def test_interactive_write_selection_reprompts_on_invalid_choice(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=["bogus", "q"]), patch(
            "logwright.app.open_in_editor",
        ) as open_editor, redirect_stdout(io.StringIO()):
            result = interactive_write_selection(
                repo_path=Path("/tmp/repo"),
                variants=variants,
                commit_now=False,
            )
        self.assertEqual((None, False), result)
        open_editor.assert_not_called()

    def test_interactive_write_selection_marks_commit_as_skipped(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=["", "n"]):
            result = interactive_write_selection(
                repo_path=Path("/tmp/repo"),
                variants=variants,
                commit_now=False,
            )
        self.assertEqual(("docs: standard", False), result)

    def test_interactive_write_selection_edits_before_reconfirming(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=["1", "e", "n"]), patch(
            "logwright.app.open_in_editor",
            return_value="docs: edited",
        ) as open_editor, patch("logwright.app.run_commit") as run_commit:
            result = interactive_write_selection(
                repo_path=Path("/tmp/repo"),
                variants=variants,
                commit_now=False,
            )
        self.assertEqual(("docs: edited", False), result)
        open_editor.assert_called_once_with("docs: terse")
        run_commit.assert_not_called()

    def test_interactive_write_selection_reports_eof_cleanly(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaisesRegex(
                GitError,
                "interactive write mode requires a terminal",
            ):
                interactive_write_selection(
                    repo_path=Path("/tmp/repo"),
                    variants=variants,
                    commit_now=False,
                )

    def test_interactive_write_selection_reports_custom_seed_eof_cleanly(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=["c", EOFError]):
            with self.assertRaisesRegex(
                GitError,
                "interactive write mode requires a terminal",
            ):
                interactive_write_selection(
                    repo_path=Path("/tmp/repo"),
                    variants=variants,
                    commit_now=False,
                )

    def test_interactive_write_selection_reports_keyboard_interrupt_cleanly(self) -> None:
        variants = [
            SuggestionVariant(label="terse", message="docs: terse", why="Short."),
            SuggestionVariant(label="standard", message="docs: standard", why="Balanced."),
            SuggestionVariant(label="detailed", message="docs: detailed", why="Long."),
        ]
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with self.assertRaisesRegex(GitError, "interactive write mode cancelled"):
                interactive_write_selection(
                    repo_path=Path("/tmp/repo"),
                    variants=variants,
                    commit_now=False,
                )

    def test_main_reports_editor_failure_cleanly(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            stderr = io.StringIO()
            with patch("builtins.input", side_effect=["e"]), patch(
                "sys.stdin.isatty",
                return_value=True,
            ), patch.dict("os.environ", {"EDITOR": "false"}, clear=False), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as context:
                    main(["--write", "--repo", str(repo)])
        self.assertEqual(2, context.exception.code)
        self.assertIn("editor exited with status 1: false", stderr.getvalue())

    def test_main_reports_commit_failure_cleanly(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            subprocess = __import__("subprocess")
            init_test_repo(repo)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
            stderr = io.StringIO()
            with patch("builtins.input", side_effect=["", "y"]), patch(
                "sys.stdin.isatty",
                return_value=True,
            ), patch(
                "logwright.app.run_commit",
                side_effect=GitError("git commit failed with status 1"),
            ), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as context:
                    main(["--write", "--repo", str(repo)])
        self.assertEqual(2, context.exception.code)
        self.assertIn("git commit failed with status 1", stderr.getvalue())


class LogwrightHookInstallTests(unittest.TestCase):
    def test_install_commit_msg_hook_creates_heuristic_hook(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            result = install_commit_msg_hook(
                repo_path=repo,
                provider_name="heuristic",
                model=None,
                min_score=5,
                force=False,
            )
            hook_path = git_path(repo, "hooks/commit-msg")
            content = hook_path.read_text(encoding="utf-8")
            self.assertTrue(hook_path.exists())
            self.assertEqual("heuristic", result.provider)
            self.assertIn(sys.executable, content)
            self.assertIn("export PYTHONPATH=", content)
            self.assertIn('--commit-msg-file "$1"', content)
            self.assertIn("--provider heuristic", content)
            self.assertIn("--min-score 5", content)

    def test_install_commit_msg_hook_rehomes_shared_hooks_path_to_repo_local(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repo"
            repo.mkdir()
            init_test_repo(repo)
            shared_hooks = root / "shared-hooks"
            run_git(repo, "config", "core.hooksPath", str(shared_hooks))

            result = install_commit_msg_hook(
                repo_path=repo,
                provider_name="heuristic",
                model=None,
                min_score=5,
                force=False,
            )

            repo_hook_dir = git_dir(repo) / "hooks"
            self.assertEqual(str(repo_hook_dir), result.configured_hooks_path)
            self.assertEqual(str(repo_hook_dir), run_git(repo, "config", "--local", "--get", "core.hooksPath").strip())
            self.assertEqual(repo_hook_dir / "commit-msg", Path(result.hook_path))

    def test_install_commit_msg_hook_requires_force_for_foreign_hook(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            hook_path = git_path(repo, "hooks/commit-msg")
            hook_path.parent.mkdir(parents=True, exist_ok=True)
            hook_path.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "refusing to overwrite existing commit-msg hook"):
                install_commit_msg_hook(
                    repo_path=repo,
                    provider_name="auto",
                    model=None,
                    min_score=5,
                    force=False,
                )

    def test_install_commit_msg_hook_backs_up_foreign_hook_with_force(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            hook_path = git_path(repo, "hooks/commit-msg")
            hook_path.parent.mkdir(parents=True, exist_ok=True)
            hook_path.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
            result = install_commit_msg_hook(
                repo_path=repo,
                provider_name="openai",
                model="gpt-5.4-mini",
                min_score=6,
                force=True,
            )
            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            backup_path = Path(result.backup_path)
            self.assertTrue(backup_path.exists())
            self.assertIn("echo existing", backup_path.read_text(encoding="utf-8"))
            self.assertIn("--provider openai", hook_path.read_text(encoding="utf-8"))

    def test_render_hook_install_result_mentions_backup_when_present(self) -> None:
        rendered = render_hook_install_result(
            HookInstallResult(
                repo_path="/tmp/repo",
                hook_path="/tmp/repo/.git/hooks/commit-msg",
                provider="heuristic",
                model=None,
                min_score=5,
                command="python -m logwright --commit-msg-file \"$1\"",
                configured_hooks_path="/tmp/repo/.git/hooks",
                backup_path="/tmp/repo/.git/hooks/commit-msg.before-logwright",
                updated_existing=True,
            )
        )
        self.assertIn("Installed commit-msg hook", rendered)
        self.assertIn("Configured local core.hooksPath: /tmp/repo/.git/hooks", rendered)
        self.assertIn("Backup: /tmp/repo/.git/hooks/commit-msg.before-logwright", rendered)

    def test_render_hook_install_result_shows_actual_written_command(self) -> None:
        rendered = render_hook_install_result(
            HookInstallResult(
                repo_path="/tmp/repo",
                hook_path="/tmp/repo/.git/hooks/commit-msg",
                provider="heuristic",
                model=None,
                min_score=5,
                command='export PYTHONPATH=/tmp/src"${PYTHONPATH:+:$PYTHONPATH}"\nexec /usr/bin/python3 -m logwright --commit-msg-file "$1" --provider heuristic --min-score 5 --repo /tmp/repo',
            )
        )
        self.assertIn("export PYTHONPATH=/tmp/src", rendered)
        self.assertIn('exec /usr/bin/python3 -m logwright --commit-msg-file "$1"', rendered)

    def test_cli_install_hook_defaults_to_heuristic_provider(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    ["--install-commit-msg-hook", "--repo", str(repo), "--json"]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("heuristic", payload["provider"])
            self.assertIsNone(payload["model"])

    def test_cli_install_hook_preserves_explicit_auto_provider(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--install-commit-msg-hook",
                        "--repo",
                        str(repo),
                        "--provider",
                        "auto",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual("auto", payload["provider"])
            self.assertIsNone(payload["model"])
            self.assertIn("--provider auto", Path(payload["hook_path"]).read_text(encoding="utf-8"))

    def test_cli_install_hook_rejects_model_without_explicit_provider(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            init_test_repo(repo)
            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as exc:
                main(
                    [
                        "--install-commit-msg-hook",
                        "--repo",
                        str(repo),
                        "--model",
                        "gpt-5.4-mini",
                    ]
                )
            self.assertEqual(2, exc.exception.code)
            self.assertIn("--model requires --provider anthropic, openai, or gemini", stderr.getvalue())

    def test_cli_install_hook_missing_repo_reports_clean_error(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as exc:
            main(
                [
                    "--install-commit-msg-hook",
                    "--repo",
                    "/tmp/nonexistent-logwright-test-repo",
                    "--json",
                ]
            )
        self.assertEqual(2, exc.exception.code)
        self.assertIn("repository path does not exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
