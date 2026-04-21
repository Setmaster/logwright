import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from logwright.app import detect_low_signal_subject, heuristic_analysis, heuristic_commit_message
from logwright.env import load_env_file
from logwright.models import CommitRecord, RepoStyle
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


if __name__ == "__main__":
    unittest.main()
