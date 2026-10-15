"""Small, independently testable deployment helpers (no host dependencies)."""

import copy
import hashlib
import json
import os
import tarfile
import tempfile
from pathlib import Path

SEARCH_KEYS = (
    "max_price_nzd",
    "max_odometer_km",
    "coverage",
    "area_label",
    "models",
    "allowed_locations",
    "preferred_regions",
    "mode",
    "min_year",
    "requirements",
    "preferences",
)
PAYLOAD_ITEMS = (
    "pyproject.toml",
    "src",
    "deploy",
    "scripts",
    "docs",
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "config.example.yaml",
    "config.wellington-ninja.yaml",
    "config.bike-search.yaml",
)


def deployment_config(existing: dict, preset: dict | None, revision: str) -> dict:
    result = copy.deepcopy(existing)
    if preset is not None:
        search = result.setdefault("search", {})
        for key in SEARCH_KEYS:
            if key in preset.get("search", {}):
                search[key] = copy.deepcopy(preset["search"][key])
        # An empty location list deliberately removes a previous regional constraint.
        if "allowed_locations" not in preset.get("search", {}):
            search["allowed_locations"] = []
        if preset["search"].get("mode") == "all_models":
            # Broad discovery must replace old Ninja-only URLs as part of this preset.
            search["sources"] = copy.deepcopy(preset["search"]["sources"])
            result["llm"] = copy.deepcopy(preset.get("llm", {"enabled": False}))
            result.setdefault("collector", {}).update(
                copy.deepcopy(preset.get("collector", {}))
            )
        elif preset["search"].get("mode", "models") == "models":
            search["mode"] = "models"
    result.setdefault("web", {})["deployment_id"] = revision
    return result


def write_atomic(path: Path, contents: str) -> None:
    metadata = path.stat()
    handle = tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=".monitor-deploy-", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, metadata.st_mode & 0o777)
        os.chown(temporary, metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def package_project(root: Path, archive: Path, extra_file: str | None = None) -> str:
    digest = hashlib.sha256()
    with tarfile.open(archive, "w:gz") as tar:
        for name in (
            *PAYLOAD_ITEMS,
            *([extra_file] if extra_file and extra_file not in PAYLOAD_ITEMS else []),
        ):
            item = root / name
            candidates = sorted(item.rglob("*")) if item.is_dir() else [item]
            for path in candidates:
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(root)
                if (
                    any(
                        part == "__pycache__" or part.endswith(".egg-info")
                        for part in relative.parts
                    )
                    or path.suffix in {".pyc", ".token", ".key", ".pem"}
                    or ("token" in path.name.lower() and path.suffix == ".txt")
                    or path.name
                    in {
                        "token.txt",
                        "search-token.txt",
                        "brave-token.txt",
                        "tavily-token.txt",
                    }
                    or (path.name.startswith(".env") and path.name != ".env.example")
                ):
                    continue
                digest.update(str(relative).encode())
                digest.update(path.read_bytes())
                tar.add(path, arcname=str(relative), recursive=False)
    return digest.hexdigest()[:12]


def save_profile(path: Path, target: str, preset: str) -> None:
    path.write_text(json.dumps({"target": target, "preset": preset}, indent=2) + "\n")
    path.chmod(0o600)
