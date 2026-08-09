"""Update README release download examples for a GitHub Release tag."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


RELEASE_TAG_PATTERN = r"v[0-9][0-9A-Za-z._-]*"
README_PATH = Path("README.md")


def replace_required(pattern: str, replacement: str, text: str) -> str:
    updated, count = re.subn(pattern, replacement, text)
    if count == 0:
        raise SystemExit(f"README release-version pattern not found: {pattern}")
    return updated


def update_readme(release_tag: str, readme_path: Path = README_PATH) -> bool:
    if not re.fullmatch(RELEASE_TAG_PATTERN, release_tag):
        raise SystemExit(
            "Release tag must look like v1.2.3 or v1.2.3-rc.1 so it can be "
            "used safely in release asset filenames."
        )

    original = readme_path.read_text(encoding="utf-8")
    updated = original

    updated = replace_required(
        rf"VERSION={RELEASE_TAG_PATTERN}",
        f"VERSION={release_tag}",
        updated,
    )
    updated = replace_required(
        rf"google-finance-mcp-{RELEASE_TAG_PATTERN}-linux-x86_64\.tar\.gz",
        f"google-finance-mcp-{release_tag}-linux-x86_64.tar.gz",
        updated,
    )
    updated = replace_required(
        r"google_finance_mcp-[0-9][0-9A-Za-z._-]*-py3-none-any\.whl",
        f"google_finance_mcp-{release_tag[1:]}-py3-none-any.whl",
        updated,
    )
    updated = replace_required(
        rf"releases/download/{RELEASE_TAG_PATTERN}/google-finance-mcp-{RELEASE_TAG_PATTERN}-macos-arm64\.pkg",
        f"releases/download/{release_tag}/google-finance-mcp-{release_tag}-macos-arm64.pkg",
        updated,
    )

    if updated == original:
        return False

    readme_path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update README release download examples for a release tag."
    )
    parser.add_argument("release_tag", help="GitHub Release tag, for example v0.1.0")
    args = parser.parse_args()

    changed = update_readme(args.release_tag)
    if changed:
        print(f"Updated README release examples to {args.release_tag}.")
    else:
        print(f"README release examples already use {args.release_tag}.")


if __name__ == "__main__":
    main()
