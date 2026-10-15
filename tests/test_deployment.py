import copy
import io
import json
import sqlite3
import tarfile

import deploy_remote
import pytest
import yaml
from deploy_common import deployment_config, package_project, write_atomic


def test_preset_preserves_installed_settings_and_inputs():
    existing = {
        "search": {
            "models": [{"model": "GSX-8R"}],
            "sources": {"trademe": {"search_urls": ["custom checked URL"]}},
        },
        "mqtt": {"host": "my-broker", "enabled": True},
        "database": {"path": "/var/lib/custom.db"},
        "web": {"port": 9000},
    }
    before = copy.deepcopy(existing)
    preset = {
        "search": {
            "models": [{"model": "Ninja 650", "min_year": None}],
            "max_price_nzd": None,
            "max_odometer_km": 9999,
            "allowed_locations": ["Wellington"],
            "sources": {"trademe": {"search_urls": ["different URL"]}},
        }
    }
    result = deployment_config(existing, preset, "abc123")
    assert existing == before
    assert result["search"]["max_price_nzd"] is None
    assert result["search"]["models"][0]["model"] == "Ninja 650"
    for key in ["mqtt", "database"]:
        assert result[key] == existing[key]
    assert result["web"]["port"] == 9000
    assert result["web"]["deployment_id"] == "abc123"
    assert result["search"]["sources"] == existing["search"]["sources"]
    assert deployment_config(existing, None, "next")["search"] == existing["search"]


def test_archive_excludes_runtime_data_and_contains_web_and_installer(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for name in [
        "pyproject.toml",
        "src/motorcycle_monitor/web_assets/index.html",
        "src/motorcycle_monitor/web_assets/dashboard.js",
        "src/motorcycle_monitor/__pycache__/cached.pyc",
        "src/monitor.egg-info/metadata",
        "scripts/deploy_remote.py",
        "scripts/tokens.txt",
        "src/nested/search-token.txt",
        "deploy/.env",
        ".env",
        ".venv/secret",
        "data/listings.db",
        "custom.yaml",
    ]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    archive = tmp_path / "app.tar.gz"
    revision = package_project(root, archive, "custom.yaml")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert len(revision) == 12
    assert "scripts/deploy_remote.py" in names
    assert "src/motorcycle_monitor/web_assets/index.html" in names
    assert "custom.yaml" in names
    assert not any(
        "token" in name
        or name.endswith("/.env")
        or "__pycache__" in name
        or ".egg-info" in name
        or name.startswith((".env", ".venv", "data/"))
        for name in names
    )
    second = tmp_path / "second.tar.gz"
    assert package_project(root, second, "custom.yaml") == revision


def test_config_write_preserves_permissions(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("old")
    path.chmod(0o640)
    write_atomic(path, "new")
    assert path.read_text() == "new"
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.fixture
def remote_fixture(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    units = tmp_path / "units"
    units.mkdir()
    python = app / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch()
    for root in [app, staging]:
        (root / "src").mkdir()
        (root / "deploy").mkdir()
        (root / "pyproject.toml").write_text("old" if root == app else "new")
        (root / "src/module.py").write_text("old" if root == app else "new")
        for name in deploy_remote.UNITS:
            (root / "deploy" / name).write_text(
                "old unit" if root == app else "new unit"
            )
    config = tmp_path / "config.yaml"
    database = tmp_path / "listings.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE marker(value TEXT)")
        db.execute("INSERT INTO marker VALUES ('history kept')")
    original = {
        "search": {
            "max_price_nzd": 12500,
            "max_odometer_km": 10000,
            "models": [{"make": "Kawasaki", "model": "Ninja 650", "min_year": 2020}],
        },
        "mqtt": {"host": "broker", "enabled": True},
        "database": {"path": str(database)},
        "web": {"port": 8765},
        "collector": {"enable_browser_fallback": False},
    }
    config.write_text(yaml.safe_dump(original))
    (staging / "config.wellington-ninja.yaml").write_text(
        yaml.safe_dump({"search": {"max_price_nzd": None, "max_odometer_km": 9999}})
    )
    for name, value in [
        ("APP", app),
        ("CONFIG", config),
        ("PYTHON", python),
        ("UNIT_DIR", units),
        ("BACKUP_ROOT", tmp_path / "backups"),
    ]:
        monkeypatch.setattr(deploy_remote, name, value)
    monkeypatch.setattr(deploy_remote.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        deploy_remote, "yaml_read", lambda path: yaml.safe_load(path.read_text())
    )
    monkeypatch.setattr(deploy_remote, "yaml_text", lambda data: yaml.safe_dump(data))
    commands = []

    def fake_run(command, capture=False, check=True):
        commands.append(command)
        if command[:2] == ["systemctl", "is-enabled"]:
            return "enabled"
        if command[:2] == ["systemctl", "show"]:
            return "inactive"
        return ""

    monkeypatch.setattr(deploy_remote, "run", fake_run)
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(
            json.dumps(
                {
                    "deployment_id": "revision",
                    "criteria": {
                        "max_odometer_km": 9999,
                        "max_price_nzd": None,
                        "models": original["search"]["models"],
                    },
                    "area": "Nationwide",
                    "listings": [],
                }
            ).encode()
        ),
    )
    return app, staging, config, database, original, commands, fake_run


def test_remote_pipeline_backs_up_preserves_data_and_scans(remote_fixture):
    app, staging, config, database, original, commands, _ = remote_fixture
    deploy_remote.deploy(staging, "config.wellington-ninja.yaml", "revision")
    updated = yaml.safe_load(config.read_text())
    assert updated["mqtt"] == original["mqtt"]
    assert updated["database"] == original["database"]
    assert updated["search"]["max_price_nzd"] is None
    assert ["systemctl", "start", "motorcycle-monitor.service"] in commands
    assert ["systemctl", "restart", "motorcycle-monitor-web.service"] in commands
    assert ["systemctl", "enable", "--now", "motorcycle-monitor.timer"] in commands
    assert (app / "src/module.py").read_text() == "new"
    backups = list(deploy_remote.BACKUP_ROOT.glob("*/listings.db"))
    assert len(backups) == 1
    for path in [database, backups[0]]:
        with sqlite3.connect(path) as db:
            assert (
                db.execute("SELECT value FROM marker").fetchone()[0] == "history kept"
            )


@pytest.mark.parametrize("interrupted", [False, True])
def test_install_failure_restores_old_configuration(
    remote_fixture, monkeypatch, interrupted
):
    app, staging, config, _, original, commands, normal = remote_fixture

    def fail(command, capture=False, check=True):
        if any(str(staging) + "[browser]" == argument for argument in command):
            if interrupted:
                deploy_remote.interrupted(deploy_remote.signal.SIGHUP, None)
            raise deploy_remote.subprocess.CalledProcessError(1, command)
        return normal(command, capture, check)

    monkeypatch.setattr(deploy_remote, "run", fail)
    with pytest.raises(
        RuntimeError if interrupted else deploy_remote.subprocess.CalledProcessError
    ):
        deploy_remote.deploy(staging, "config.wellington-ninja.yaml", "revision")
    assert yaml.safe_load(config.read_text()) == original
    assert (app / "src/module.py").read_text() == "old"
    assert ["systemctl", "start", "motorcycle-monitor.timer"] in commands
