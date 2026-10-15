#!/usr/bin/env python3
"""One-command desktop-to-LXC redeployment over the user's normal SSH connection."""

import argparse
import json
import re
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from check_publication import check
from deploy_common import package_project, save_profile

ROOT = Path(__file__).resolve().parent.parent
PROFILE = ROOT / ".deploy.local.json"


def run(command: list[str], capture: bool = False) -> str:
    result = subprocess.run(
        command, check=True, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout.strip() if capture else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", help="Root SSH target, e.g. root@192.168.5.20 (saved for next time)"
    )
    parser.add_argument(
        "--preset",
        help="Criteria YAML filename, or none to preserve installed criteria",
    )
    parser.add_argument(
        "--package-only",
        type=Path,
        help="Create a reviewable deployment archive without contacting the LXC",
    )
    args = parser.parse_args()
    _, findings = check(ROOT)
    if findings:
        raise RuntimeError("Deployment source check failed: " + "; ".join(findings))
    profile = json.loads(PROFILE.read_text()) if PROFILE.exists() else {}
    target = args.target or profile.get("target")
    preset = args.preset or profile.get("preset") or "config.wellington-ninja.yaml"
    if preset != "none" and (
        Path(preset).name != preset
        or Path(preset).suffix not in {".yaml", ".yml"}
        or not (ROOT / preset).is_file()
    ):
        parser.error("Preset must be a YAML filename in the project root, or none")
    if args.package_only:
        revision = package_project(
            ROOT, args.package_only, None if preset == "none" else preset
        )
        print(
            f"Archive: {args.package_only}\nDeployment ID: {revision}\nCriteria preset: {preset}"
        )
        return 0
    if not target:
        target = input("LXC SSH target (e.g. root@192.168.5.20): ").strip()
    if not re.fullmatch(
        r"(?:[a-zA-Z_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.:-]*", target
    ):
        parser.error(
            "Invalid SSH target; use a hostname/IP, optionally prefixed with root@"
        )
    if "@" not in target:
        target = "root@" + target
    save_profile(PROFILE, target, preset)
    with tempfile.TemporaryDirectory(prefix="motorcycle-redeploy-") as work:
        folder = Path(work)
        archive = folder / "application.tar.gz"
        revision = package_project(ROOT, archive, None if preset == "none" else preset)
        control = str(folder / "ssh-control")
        options = [
            "-o",
            "ControlMaster=auto",
            "-o",
            f"ControlPath={control}",
            "-o",
            "ControlPersist=600",
            "-o",
            "ConnectTimeout=15",
        ]
        ssh = ["ssh", *options, target]
        remote = None
        try:
            print(f"Deploying {revision} to {target}; preset {preset}", flush=True)
            remote_path = run(
                [*ssh, "mktemp -d /tmp/motorcycle-redeploy.XXXXXXXX"], capture=True
            )
            if not re.fullmatch(r"/tmp/motorcycle-redeploy\.[A-Za-z0-9]+", remote_path):
                raise RuntimeError("Unexpected remote staging path")
            remote = remote_path
            run(
                ["scp", *options, str(archive), f"{target}:{remote}/application.tar.gz"]
            )
            if preset == "config.bike-search.yaml" and (ROOT / "token.txt").is_file():
                # Extract only the DeepSeek key: the local file may also hold a
                # GitHub credential, which must never be sent to the LXC.
                sys.path.insert(0, str(ROOT / "src"))
                from motorcycle_monitor.secrets import credential

                secret_file = folder / "deepseek.token"
                secret_file.touch(mode=0o600)
                secret_file.write_text(
                    credential("DEEPSEEK_API_KEY", str(ROOT / "token.txt")) + "\n"
                )
                run(
                    [
                        "scp",
                        *options,
                        str(secret_file),
                        f"{target}:{remote}/deepseek.token",
                    ]
                )
                run([*ssh, shlex.join(["chmod", "600", remote + "/deepseek.token"])])
            command = [
                "sh",
                "-c",
                f"tar -xzf {shlex.quote(remote + '/application.tar.gz')} -C {shlex.quote(remote)} && python3 {shlex.quote(remote + '/scripts/deploy_remote.py')} --staging {shlex.quote(remote)} --preset {shlex.quote(preset)} --revision {shlex.quote(revision)}",
            ]
            previous_handler = signal.signal(signal.SIGINT, deployment_interrupt)
            try:
                run([*ssh, shlex.join(command)])
            finally:
                signal.signal(signal.SIGINT, previous_handler)
            hostname = target.split("@")[-1]
            port = run(
                [
                    *ssh,
                    "/opt/motorcycle-monitor/.venv/bin/python -c "
                    + shlex.quote(
                        "import yaml; print(yaml.safe_load(open('/etc/motorcycle-monitor/config.yaml')).get('web',{}).get('port',8765))"
                    ),
                ],
                capture=True,
            )
            if not port.isdigit():
                raise RuntimeError("Dashboard port could not be read")
            print(
                f"\nRedeployment and fresh scan completed.\nOpen http://{hostname}:{port}/\nDeployment ID: {revision}",
                flush=True,
            )
        finally:
            if remote:
                subprocess.run(
                    [*ssh, shlex.join(["rm", "-rf", "--", remote])], check=False
                )
            subprocess.run(
                ["ssh", *options, "-O", "exit", target],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    return 0


def deployment_interrupt(signum: int, frame: object) -> None:
    print(
        "\nDeployment is updating the live service; waiting for it to finish safely. "
        "Keep this terminal open.",
        flush=True,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nRedeployment cancelled before installation.", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Redeployment failed: {error}", file=sys.stderr)
        raise SystemExit(1)
