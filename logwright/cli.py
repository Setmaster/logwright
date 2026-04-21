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
from logwright.gittools import GitError
from logwright.providers import ProviderError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="logwright",
        description="Critique git commit messages against their diffs and help write better ones.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print the installed logwright version and exit",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
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

    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "anthropic", "openai", "gemini", "heuristic"],
        help=(
            "LLM provider to use. auto falls back to heuristics if no API key is set. "
            "Hook install defaults to heuristic unless --provider is passed explicitly."
        ),
    )
    parser.add_argument("--model", help="Override the provider model name")
    parser.add_argument("--limit", type=int, default=50, help="Number of commits to inspect")
    parser.add_argument("--url", help="Analyze a remote git repository URL")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument(
        "--no-cache", action="store_true", help="Disable local analysis caching"
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="For write mode, print suggestions without interactive prompts",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="For write mode, create the commit immediately with the chosen message",
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository path for local analysis, write mode, or commit-msg checks",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=5,
        help="Minimum passing score for --commit-msg-file and hook-install modes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-logwright commit-msg hook after creating a backup",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(raw_args)
    repo_path = Path(args.repo).resolve()
    load_env_file(repo_path / ".env")

    try:
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

        changes, style, variants, usage, repo = prepare_write_mode(
            repo_path=repo_path,
            provider_name=args.provider,
            model=args.model,
        )
        print(render_write_preview(changes, style, variants, usage))
        final_message = None
        if not args.print_only:
            final_message = interactive_write_selection(
                repo_path=repo,
                variants=variants,
                commit_now=args.commit,
            )
        if final_message:
            print("\nChosen message:\n")
            print(final_message)
        return 0
    except (GitError, ProviderError, ValueError) as exc:
        parser.exit(2, f"logwright: {exc}\n")


def _flag_was_provided(argv: list[str] | None, flag: str) -> bool:
    if argv is None:
        return False
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in argv)


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


if __name__ == "__main__":
    raise SystemExit(main())
