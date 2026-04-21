from __future__ import annotations

import argparse
import sys
from pathlib import Path

from logwright import __version__
from logwright.app import (
    analyze_local_or_remote,
    check_pending_commit_message,
    commit_check_to_json,
    hook_install_to_json,
    install_commit_msg_hook,
    interactive_write_selection,
    prepare_write_mode,
    render_commit_check_report,
    render_analysis_report,
    render_hook_install_result,
    render_write_preview,
    report_to_json,
)
from logwright.env import load_env_file
from logwright.gittools import GitError, ensure_git_repo
from logwright.providers import ProviderError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logwright",
        description="Critique git commit messages against their diffs and help write better ones.",
        epilog=_help_epilog(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print the installed logwright version and exit",
    )
    modes = parser.add_argument_group("Modes")
    mode = modes.add_mutually_exclusive_group(required=True)
    mode.add_argument("--analyze", action="store_true", help="Analyze recent commits")
    mode.add_argument("--write", action="store_true", help="Suggest a commit for staged changes")
    mode.add_argument(
        "--commit-msg-file",
        dest="commit_message_file",
        help="Check a pending commit message against staged changes, suitable for commit-msg hooks",
    )
    mode.add_argument(
        "--install-commit-msg-hook",
        action="store_true",
        help="Install a repo-local commit-msg hook that runs logwright",
    )

    shared = parser.add_argument_group("Shared options")
    shared.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "anthropic", "openai", "gemini", "heuristic"],
        help=(
            "LLM provider to use. auto falls back to heuristics if no API key is set. "
            "Hook install defaults to heuristic unless --provider is passed explicitly."
        ),
    )
    shared.add_argument("--model", help="Override the provider model name")
    shared.add_argument(
        "--repo",
        default=".",
        help="Repository path for local analysis, write mode, or commit-msg checks",
    )

    analyze = parser.add_argument_group("Analyze options")
    analyze.add_argument("--limit", type=int, default=50, help="Number of commits to inspect")
    analyze.add_argument("--url", help="Analyze a remote git repository URL")
    analyze.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output for analyze, hook install, or commit-msg checks",
    )
    analyze.add_argument(
        "--no-cache", action="store_true", help="Disable local analysis caching"
    )

    write = parser.add_argument_group("Write options")
    write.add_argument(
        "--print-only",
        action="store_true",
        help="For write mode, print suggestions without interactive prompts",
    )
    write.add_argument(
        "--commit",
        action="store_true",
        help="For write mode, create the commit immediately with the chosen message",
    )

    commit_checks = parser.add_argument_group("Commit-msg and hook options")
    commit_checks.add_argument(
        "--min-score",
        type=int,
        default=5,
        help="Minimum passing score for --commit-msg-file and hook-install modes",
    )
    commit_checks.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-logwright commit-msg hook after creating a backup",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(raw_args)
    _validate_mode_flags(parser, args, raw_args)

    try:
        repo_path = _prepare_repo_path(args, Path(args.repo).resolve())
        if args.analyze:
            report = analyze_local_or_remote(
                repo_path=repo_path,
                url=args.url,
                provider_name=args.provider,
                model=args.model,
                limit=args.limit,
                use_cache=not args.no_cache,
            )
            if args.json:
                print(report_to_json(report))
            else:
                print(render_analysis_report(report))
            return 0

        if args.commit_message_file:
            report = check_pending_commit_message(
                repo_path=repo_path,
                message_file=Path(args.commit_message_file),
                provider_name=args.provider,
                model=args.model,
                min_score=args.min_score,
            )
            if args.json:
                print(commit_check_to_json(report))
            else:
                print(render_commit_check_report(report))
            return 0 if report.passed else 1

        if args.install_commit_msg_hook:
            provider_explicit = _flag_was_provided(raw_args, "--provider")
            model_explicit = _flag_was_provided(raw_args, "--model")
            install_provider, install_model = _resolve_hook_install_provider(
                provider_name=args.provider,
                model=args.model,
                provider_explicit=provider_explicit,
                model_explicit=model_explicit,
            )
            result = install_commit_msg_hook(
                repo_path=repo_path,
                provider_name=install_provider,
                model=install_model,
                min_score=args.min_score,
                force=args.force,
            )
            if args.json:
                print(hook_install_to_json(result))
            else:
                print(render_hook_install_result(result))
            return 0

        if not args.print_only and not sys.stdin.isatty():
            parser.exit(
                2,
                "logwright: --write requires an interactive terminal; use --print-only for non-interactive output\n",
            )
        changes, style, variants, usage, repo = prepare_write_mode(
            repo_path=repo_path,
            provider_name=args.provider,
            model=args.model,
        )
        print(render_write_preview(changes, style, variants, usage))
        final_message = None
        committed = False
        if not args.print_only:
            final_message, committed = interactive_write_selection(
                repo_path=repo,
                variants=variants,
                commit_now=args.commit,
            )
        if final_message:
            print("\nChosen message:\n")
            print(final_message)
            if not committed:
                print("\nCommit not created.")
        return 0
    except (GitError, ProviderError, ValueError) as exc:
        parser.exit(2, f"logwright: {exc}\n")


def _flag_was_provided(argv: list[str] | None, flag: str) -> bool:
    if argv is None:
        return False
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in argv)


def _prepare_repo_path(args: argparse.Namespace, repo_path: Path) -> Path:
    if args.analyze and args.url:
        env_repo = _resolve_env_repo_path(repo_path, allow_non_git=True)
        load_env_file(env_repo / ".env")
        return repo_path
    repo = _resolve_env_repo_path(repo_path, allow_non_git=False)
    load_env_file(repo / ".env")
    return repo


def _resolve_env_repo_path(repo_path: Path, *, allow_non_git: bool) -> Path:
    try:
        return ensure_git_repo(repo_path)
    except GitError:
        if allow_non_git:
            return repo_path
        raise


def _validate_mode_flags(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    raw_args: list[str],
) -> None:
    mode_name = _selected_mode_name(args)
    unsupported_flags = {
        "analyze": {"--print-only", "--commit", "--min-score", "--force"},
        "write": {"--json", "--limit", "--url", "--no-cache", "--min-score", "--force"},
        "commit-msg-file": {"--limit", "--url", "--no-cache", "--print-only", "--commit", "--force"},
        "install-commit-msg-hook": {"--limit", "--url", "--no-cache", "--print-only", "--commit"},
    }
    for flag in sorted(unsupported_flags[mode_name]):
        if _flag_was_provided(raw_args, flag):
            parser.error(f"{flag} is not supported with --{mode_name}")
    if args.write and _flag_was_provided(raw_args, "--print-only") and _flag_was_provided(raw_args, "--commit"):
        parser.error("--commit cannot be used together with --print-only")


def _selected_mode_name(args: argparse.Namespace) -> str:
    if args.analyze:
        return "analyze"
    if args.write:
        return "write"
    if args.commit_message_file:
        return "commit-msg-file"
    return "install-commit-msg-hook"


def _resolve_hook_install_provider(
    *,
    provider_name: str,
    model: str | None,
    provider_explicit: bool,
    model_explicit: bool,
) -> tuple[str, str | None]:
    if model_explicit and provider_name in {"auto", "heuristic"}:
        raise ValueError(
            "--model requires --provider anthropic, openai, or gemini for hook installation"
        )
    if not provider_explicit and provider_name == "auto":
        return "heuristic", None
    return provider_name, model


def _help_epilog() -> str:
    return (
        "Examples:\n"
        "  logwright --write --print-only\n"
        "  logwright --analyze --limit 10\n"
        "  logwright --commit-msg-file .git/COMMIT_EDITMSG --min-score 5\n"
        "  logwright --install-commit-msg-hook --provider openai --min-score 6"
    )


if __name__ == "__main__":
    raise SystemExit(main())
