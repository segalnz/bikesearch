#!/usr/bin/env python3
"""Check the publication allowlist or Git index without printing secret values."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_ITEMS = (
    "src",
    "tests",
    "scripts",
    "docs",
    "deploy",
    ".github",
    ".vscode",
    "README.md",
    "pyproject.toml",
    ".gitignore",
    ".env.example",
    "config.example.yaml",
    "config.wellington-ninja.yaml",
    "config.bike-search.yaml",
    "trademe_motorcycle_monitor_spec.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
)
TOKEN = re.compile(
    rb"(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})"
)


def known_secrets(root: Path) -> list[bytes]:
    found = []
    for path in root.glob("*token*.txt"):
        if path.is_file():
            found.extend(TOKEN.findall(path.read_bytes()))
    return found


def inspect(relative: str, content: bytes, secrets: list[bytes]) -> list[str]:
    path = Path(relative)
    forbidden = (
        (path.name.startswith(".env") and path.name != ".env.example")
        or ("token" in path.name.lower() and path.suffix in {".txt", ".token"})
        or path.suffix in {".db", ".key", ".pem", ".token"}
        or path.name == ".deploy.local.json"
    )
    findings = []
    if forbidden:
        findings.append(relative + ": confidential/runtime file must not be published")
    if (
        TOKEN.search(content)
        or any(secret and secret in content for secret in secrets)
        or re.search(
            rb"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----\s+[A-Za-z0-9+/]{32,}",
            content,
        )
    ):
        findings.append(relative + ": credential material detected (value suppressed)")
    return findings


def check(root: Path, index: bool = False) -> tuple[int, list[str]]:
    secrets = known_secrets(root)
    findings = []
    if index:
        paths = (
            subprocess.run(
                ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
            )
            .stdout.decode()
            .split("\0")
        )
        entries = []
        for relative in filter(None, paths):
            content = subprocess.run(
                ["git", "show", ":" + relative],
                cwd=root,
                check=True,
                capture_output=True,
            ).stdout
            entries.append((relative, content))
    else:
        entries = []
        for item in PUBLIC_ITEMS:
            path = root / item
            candidates = path.rglob("*") if path.is_dir() else [path]
            for candidate in candidates:
                if candidate.is_symlink():
                    findings.append(
                        str(candidate.relative_to(root)) + ": symlink requires review"
                    )
                elif (
                    candidate.is_file()
                    and "__pycache__" not in candidate.parts
                    and candidate.suffix != ".pyc"
                ):
                    entries.append(
                        (str(candidate.relative_to(root)), candidate.read_bytes())
                    )
    for relative, content in entries:
        findings.extend(inspect(relative, content, secrets))
    return len(entries), findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index",
        action="store_true",
        help="Inspect exact staged/index blobs before pushing",
    )
    args = parser.parse_args()
    count, findings = check(ROOT, args.index)
    if findings:
        print("\n".join(findings))
        return 1
    print(
        f"Publication check passed: {count} files; credential values never displayed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
