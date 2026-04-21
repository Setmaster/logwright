import unittest

from logwright.app import detect_low_signal_subject, heuristic_analysis, heuristic_commit_message
from logwright.models import CommitRecord, RepoStyle


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


if __name__ == "__main__":
    unittest.main()
