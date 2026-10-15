#!/usr/bin/env python3
"""Run on the existing LXC by redeploy.py; preserves persistent service data."""

import argparse
import fcntl
import grp
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from deploy_common import deployment_config, write_atomic

APP = Path("/opt/motorcycle-monitor")
CONFIG = Path("/etc/motorcycle-monitor/config.yaml")
PYTHON = APP / ".venv/bin/python"
UNIT_DIR = Path("/etc/systemd/system")
BACKUP_ROOT = Path("/var/lib/motorcycle-monitor/deploy-backups")
UNITS = (
    "motorcycle-monitor.service",
    "motorcycle-monitor.timer",
    "motorcycle-monitor-web.service",
)


def interrupted(signum: int, frame: object) -> None:
    raise RuntimeError(f"Deployment interrupted by signal {signum}")


def run(command: list[str], capture: bool = False, check: bool = True) -> str:
    result = subprocess.run(
        command, check=check, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout.strip() if capture else ""


def yaml_read(path: Path) -> dict:
    code = "import json,sys,yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1])) or {}))"
    return json.loads(run([str(PYTHON), "-c", code, str(path)], capture=True))


def yaml_text(config: dict) -> str:
    result = subprocess.run(
        [
            str(PYTHON),
            "-c",
            'import json,sys,yaml; print(yaml.safe_dump(json.load(sys.stdin),sort_keys=False),end="")',
        ],
        input=json.dumps(config),
        text=True,
        check=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def wait_scan() -> None:
    deadline = time.monotonic() + 2100
    while run(
        [
            "systemctl",
            "show",
            "motorcycle-monitor.service",
            "--property=ActiveState",
            "--value",
        ],
        capture=True,
    ) in {"activating", "active", "deactivating"}:
        if time.monotonic() > deadline:
            raise RuntimeError(
                "Existing scan has not finished after 35 minutes; redeployment was not started"
            )
        print("Waiting for the existing scan to finish…", flush=True)
        time.sleep(15)


def restore_sources(backup: Path) -> None:
    for name in ("pyproject.toml", "src", "deploy", "README.md"):
        source = backup / "application" / name
        target = APP / name
        if not source.exists():
            continue
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def deploy(staging: Path, preset_name: str, revision: str) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Redeploy over SSH as root on the LXC")
    if not PYTHON.exists() or not CONFIG.exists():
        raise RuntimeError(
            "The existing /opt/motorcycle-monitor virtualenv and installed config are required; complete first-time setup first"
        )
    existing = yaml_read(CONFIG)
    if preset_name != "none" and Path(preset_name).name != preset_name:
        raise ValueError("Invalid preset filename")
    preset = yaml_read(staging / preset_name) if preset_name != "none" else None
    revised = deployment_config(existing, preset, revision)
    database = Path(existing["database"]["path"])
    if not database.is_absolute():
        database = APP / database
    timer_active = (
        run(
            ["systemctl", "is-enabled", "motorcycle-monitor.timer"],
            capture=True,
            check=False,
        )
        == "enabled"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_ROOT / (stamp + "-" + revision)
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    print(f"Backup directory: {backup}", flush=True)
    run(["systemctl", "stop", "motorcycle-monitor.timer"])
    install_attempted = False
    web_stopped = False
    try:
        wait_scan()
        database.parent.mkdir(parents=True, exist_ok=True)
        with Path(str(database) + ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            shutil.copy2(CONFIG, backup / "config.yaml")
            (backup / "application").mkdir()
            for name in ("pyproject.toml", "src", "deploy", "README.md"):
                source = APP / name
                if source.is_dir():
                    shutil.copytree(
                        source,
                        backup / "application" / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
                    )
                elif source.exists():
                    shutil.copy2(source, backup / "application" / name)
            if database.exists():
                with (
                    sqlite3.connect(f"file:{database}?mode=ro", uri=True) as original,
                    sqlite3.connect(backup / "listings.db") as copy,
                ):
                    original.backup(copy)
            for name in UNITS:
                current = UNIT_DIR / name
                if current.exists():
                    shutil.copy2(current, backup / name)
            run(["systemctl", "stop", "motorcycle-monitor-web.service"], check=False)
            web_stopped = True
            print(
                "Installing the updated application and packaged dashboard…", flush=True
            )
            # Build from clean staging so deleted/stale files cannot enter the wheel.
            install_attempted = True
            run(
                [
                    str(PYTHON),
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    str(staging) + "[browser]",
                ]
            )
            if (
                revised.get("llm", {}).get("enabled")
                and (staging / "deepseek.token").exists()
            ):
                credential = Path(revised["llm"]["api_key_file"])
                credential.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(staging / "deepseek.token", credential)
                os.chmod(credential, 0o640)
                os.chown(credential, 0, grp.getgrnam("motorcycle-monitor").gr_gid)
            if revised.get("collector", {}).get(
                "enable_browser_fallback"
            ) and not revised.get("collector", {}).get("browser_executable"):
                browser_environment = {
                    **os.environ,
                    "PLAYWRIGHT_BROWSERS_PATH": str(APP / "browsers"),
                }
                subprocess.run(
                    [str(PYTHON), "-m", "playwright", "install", "chromium"],
                    env=browser_environment,
                    check=True,
                )
            write_atomic(CONFIG, yaml_text(revised))
            run(
                [
                    str(APP / ".venv/bin/motorcycle-monitor"),
                    "--config",
                    str(CONFIG),
                    "validate-config",
                ]
            )
            for name in (
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
            ):
                source = staging / name
                if source.is_dir():
                    destination = APP / name
                    if destination.exists():
                        shutil.rmtree(destination)
                    shutil.copytree(source, destination)
                elif source.exists():
                    shutil.copy2(source, APP / name)
            for name in UNITS:
                shutil.copy2(staging / "deploy" / name, UNIT_DIR / name)
            run(["systemctl", "daemon-reload"])
        print("Restarting dashboard with the updated search criteria…", flush=True)
        run(
            [
                "systemctl",
                "reset-failed",
                "motorcycle-monitor.service",
                "motorcycle-monitor-web.service",
            ],
            check=False,
        )
        run(["systemctl", "enable", "--now", "motorcycle-monitor-web.service"])
        run(["systemctl", "restart", "motorcycle-monitor-web.service"])
        run(["systemctl", "enable", "--now", "motorcycle-monitor.timer"])
    except Exception:
        print(
            "Deployment failed; restoring previous application/configuration where possible.",
            file=sys.stderr,
            flush=True,
        )
        if (backup / "config.yaml").exists():
            shutil.copy2(backup / "config.yaml", CONFIG)
        if install_attempted and (backup / "application/pyproject.toml").exists():
            restore_sources(backup)
            run(
                [str(PYTHON), "-m", "pip", "install", str(backup / "application")],
                check=False,
            )
        for name in UNITS:
            if (backup / name).exists():
                shutil.copy2(backup / name, UNIT_DIR / name)
        run(["systemctl", "daemon-reload"], check=False)
        if web_stopped:
            run(["systemctl", "start", "motorcycle-monitor-web.service"], check=False)
        if timer_active:
            run(["systemctl", "start", "motorcycle-monitor.timer"], check=False)
        raise
    print(
        "Starting fresh scan; waiting for completion (normally several minutes)…",
        flush=True,
    )
    try:
        run(["systemctl", "start", "motorcycle-monitor.service"])
    except subprocess.CalledProcessError:
        run(
            [
                "journalctl",
                "-u",
                "motorcycle-monitor.service",
                "-n",
                "60",
                "--no-pager",
            ],
            check=False,
        )
        raise RuntimeError(
            "Application and criteria deployed, but the fresh scan failed; see collection health/journal. The timer and dashboard remain enabled."
        ) from None
    # Verify the web service is serving the applied criteria after the scan.
    import urllib.request

    port = revised.get("web", {}).get("port", 8765)
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/results", timeout=20
    ) as response:
        result = json.load(response)
    if result.get("deployment_id") != revision:
        raise RuntimeError("Dashboard is not serving the expected deployment ID")
    expected_criteria = {
        key: revised["search"][key]
        for key in ("models", "max_price_nzd", "max_odometer_km")
    }
    if result.get("criteria") != expected_criteria or result.get("area") != revised[
        "search"
    ].get("area_label", "Nationwide"):
        raise RuntimeError("Dashboard search criteria did not update")
    if revised["search"].get("mode") == "all_models" and any(
        result.get(key) != revised["search"].get(key)
        for key in ("requirements", "preferences", "min_year")
    ):
        raise RuntimeError("Dashboard requirements/preferences did not update")
    matches = sum(
        item["classification"] == "ACCEPTED" and item["listing_status"] == "ACTIVE"
        for item in result["listings"]
    )
    reviews = sum(
        item["classification"] == "REVIEW" and item["listing_status"] == "ACTIVE"
        for item in result["listings"]
    )
    print(
        f"Verified dashboard: {matches} available matches, {reviews} needing review. Deployment {revision}.",
        flush=True,
    )


if __name__ == "__main__":
    for deployment_signal in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(deployment_signal, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        with Path("/var/lock/motorcycle-monitor-deploy.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            deploy(args.staging, args.preset, args.revision)
    except Exception as error:
        print(f"Remote redeployment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
