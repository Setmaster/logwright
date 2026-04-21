from __future__ import annotations

import argparse
from pathlib import Path

from logwright import __version__
from logwright.app import (
    analyze_local_or_remote,
    interactive_write_selection,
    prepare_write_mode,
    render_analysis_report,
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

    parser.add_argument(
        "--provider",
        default="auto",
        choices=["auto", "anthropic", "openai", "gemini", "heuristic"],
        help="LLM provider to use. auto falls back to heuristics if no API key is set.",
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
        help="Repository path for local analysis or write mode",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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

        changes, style, variants, repo = prepare_write_mode(
            repo_path=repo_path,
            provider_name=args.provider,
            model=args.model,
        )
        print(render_write_preview(changes, style, variants))
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


if __name__ == "__main__":
    raise SystemExit(main())
