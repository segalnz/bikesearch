# Ubuntu Proxmox LXC deployment

## One-command updates from your desktop

For an already installed LXC, use this for every subsequent code or criteria
change, **from this development project on your desktop**:

```bash
./scripts/redeploy.sh
```

The first run asks for the root SSH target (for example `root@192.168.5.20`) and
saves it locally in ignored `.deploy.local.json`. Normal SSH handles authentication;
one connection is reused for the transfer and deployment. Future runs need no
copy/install/restart commands. You can also use **Ctrl+Shift+B** in VS Code or
run the **Redeploy motorcycle monitor** task.

The command packages only application files, transfers them, waits for any
existing scan, backs up SQLite/configuration, installs the new package and
service units, applies the saved search preset while
preserving broker/database/web settings, restarts the dashboard, and waits for a
fresh scan to finish. It verifies the dashboard's deployment ID and criteria
before printing success and your desktop URL. Scanning may still take several
minutes because requests remain conservatively paced. Rejected/unchanged stock
may mean no new bikes; the criteria banner confirms what is active.

The installation step may pause at `Installing build dependencies` while pip
downloads its build tools. Keep the terminal open until verification finishes.
Once live installation begins, Ctrl+C prints a message and lets deployment
finish safely so the dashboard and timer are restored. Activating the desktop
virtualenv is unnecessary: the script uses the LXC's installed virtualenv.

Edit **config.bike-search.yaml locally** for future broad-search changes, then
run the same command. The preset manages price, mileage, years, models and
location criteria. The broad preset also replaces old model-specific source URLs
and enables bounded DeepSeek reviews. Select it once with
`./scripts/redeploy.sh --preset config.bike-search.yaml`; subsequent runs remember
it. Narrow presets retain manually checked source URLs. See [search criteria](SEARCH.md).
To select another preset or change the target (these choices are saved):

```bash
./scripts/redeploy.sh --target root@LXC_IP
./scripts/redeploy.sh --preset config.example.yaml
./scripts/redeploy.sh --preset none
```

`--preset none` keeps the installed search requirements. Broker credentials and
runtime data are not transferred from the desktop. Backups remain under
`/var/lib/motorcycle-monitor/deploy-backups/`. Installation/validation failures
attempt to restore the previous application and config; a collection failure
keeps the successfully deployed app and reports the error rather than claiming a
successful rescan. The daily timer and dashboard remain enabled after a scan
failure. Live history is not automatically rolled back or deleted.

Open dashboard tabs detect a new deployment on refresh and reload the new
assets. For the first upgrade from a version without this detection, refresh the
page once. Thereafter updates appear automatically within the page's configured
refresh interval. Clicking Refresh results displays committed results immediately.

The detailed steps below are for first-time setup or troubleshooting.

Run these steps **inside the intended existing Ubuntu LXC**. Python 3.11+ is
required; the existing Python 3.11.2 reported by this LXC is supported. All Python
packages live in the application virtualenv; do not use sudo pip against the
system interpreter.

If an earlier installation reported `requires a different Python ... >=3.12`,
copy the updated `pyproject.toml` from the development project into
`/opt/motorcycle-monitor/pyproject.toml`, then retry the pip installation below.
The existing Python 3.11 virtualenv can be reused.

As root, install prerequisites and create the service account/directories:

```bash
apt-get update
apt-get install python3 python3-venv ca-certificates sqlite3 passwd util-linux
/usr/sbin/useradd --system --user-group --home-dir /var/lib/motorcycle-monitor --shell /usr/sbin/nologin motorcycle-monitor
install -d /opt/motorcycle-monitor /etc/motorcycle-monitor
install -d -o motorcycle-monitor -g motorcycle-monitor /var/lib/motorcycle-monitor /var/log/motorcycle-monitor
```

On minimal Ubuntu containers, `useradd` may be missing or `/usr/sbin` may be
absent from PATH. The `passwd` package supplies it; the absolute path above
handles the PATH case. `--user-group` explicitly creates the matching group
required by the service and directory ownership commands. Run account creation
once; if the account already exists, skip that command.

Copy the application files from this development machine into the LXC before
running the installation commands. On this development machine, from the project
root, replace `LXC_IP` with the container's address:

```bash
cd /mnt/molly/development/motoscrape
scp -r pyproject.toml src deploy docs README.md config.example.yaml config.wellington-ninja.yaml .env.example \
  root@LXC_IP:/opt/motorcycle-monitor/
```

The destination directory must already exist from the earlier preparation step.
This copies `pyproject.toml` to `/opt/motorcycle-monitor/pyproject.toml` and the
Python package to `/opt/motorcycle-monitor/src/motorcycle_monitor/`. It also
copies the service units and example configuration used below. The explicit file
list leaves the development virtualenv, local data and real credentials behind.
If root SSH is unavailable, transfer the files using your normal container file
transfer method into the same destination paths.

Now switch back to the **LXC's root shell**. Run the commands below from the
copied project root, which must contain
`pyproject.toml` and `src/motorcycle_monitor/`. Install the application and
Playwright explicitly into the same virtualenv, then verify Playwright is
available before installing its browser dependencies.

```bash
cd /opt/motorcycle-monitor
python3 -m venv .venv
.venv/bin/python -m pip install . 'playwright>=1.48,<2'
.venv/bin/python -m playwright --version
```

Continue only after pip finishes successfully and the version command prints
the installed Playwright version. If installation fails, resolve that error
before running the following commands:

```bash
.venv/bin/python -m playwright install-deps chromium
PLAYWRIGHT_BROWSERS_PATH=/opt/motorcycle-monitor/browsers .venv/bin/python -m playwright install chromium
install -m 640 -o root -g motorcycle-monitor config.example.yaml /etc/motorcycle-monitor/config.yaml
install -m 640 -o root -g motorcycle-monitor .env.example /etc/motorcycle-monitor/monitor.env
```

Set the deployment paths in the installed configuration before starting the
service. The development default `./data/listings.db` cannot be written beneath
`/opt/motorcycle-monitor` under the service's read-only filesystem protection:

```bash
/opt/motorcycle-monitor/.venv/bin/python - <<'PY'
from pathlib import Path
import yaml
path = Path('/etc/motorcycle-monitor/config.yaml')
config = yaml.safe_load(path.read_text())
config.setdefault('database', {})['path'] = '/var/lib/motorcycle-monitor/listings.db'
config.setdefault('logging', {})['path'] = '/var/log/motorcycle-monitor/monitor.log'
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
```

This updates the paths while preserving your other configuration settings.
Configure MQTT and check source URLs. Keep browser_executable null for the installed Playwright
browser. A system Chromium package may be snap based on Ubuntu; prefer Playwright
Chromium inside LXC if snap is unavailable. Never disable browser sandboxing to
work around container configuration; ensure the LXC supports ordinary Chromium
sandboxing or use HTTP dealer sources/manual imports while correcting the host.

Use a separate user with explicit exports for a manual dry-run, or run this test
as the service account (no MQTT publish in dry-run):

```bash
runuser -u motorcycle-monitor -- env PLAYWRIGHT_BROWSERS_PATH=/opt/motorcycle-monitor/browsers \
  /opt/motorcycle-monitor/.venv/bin/motorcycle-monitor --config /etc/motorcycle-monitor/config.yaml scan --dry-run
install -m 644 deploy/motorcycle-monitor.service deploy/motorcycle-monitor.timer /etc/systemd/system/
systemd-analyze calendar '*-*-* 08:00:00 Pacific/Auckland'
systemctl daemon-reload
systemctl start motorcycle-monitor.service
systemctl enable --now motorcycle-monitor.timer
systemctl list-timers motorcycle-monitor.timer
journalctl -u motorcycle-monitor.service
```

The timezone is explicit in OnCalendar, independent of the container's local
zone. Pacific/Auckland observes daylight saving. Persistent=true catches a missed
run when the container comes back online. The scan lock prevents concurrent
manual/timer work. The service is restricted to its state/log directories and
temporary files; browser binaries remain read-only. If this LXC has a stricter
AppArmor/user-namespace policy, test Chromium as the service user before enabling
the timer. The app reports render failure instead of claiming success.

Upgrade: stop the timer, wait for any active service, back up SQLite safely, update
code and reinstall inside the existing .venv. Run the offline tests in a developer
venv or install the test extra, check config and a dry-run, then restart the timer.
Use the old code with the pre-upgrade backup for rollback if a future migration is
not backward-compatible. Do not delete history or pending outbox events to fix a
publisher outage.

## Background monitoring and reading results

Enable the timer inside the LXC:

```bash
systemctl enable --now motorcycle-monitor.timer
systemctl list-timers motorcycle-monitor.timer
```

The timer remains active in the background and starts a scan each day at 08:00
Pacific/Auckland. The scan service is a oneshot: it runs, saves its results and
exits. Seeing the service inactive between scans is normal; the timer must be
active. `Persistent=true` schedules a catch-up scan after downtime. An immediate
scan can be requested with `systemctl start motorcycle-monitor.service`.

Read the saved results at any time:

```bash
/opt/motorcycle-monitor/.venv/bin/motorcycle-monitor --config /etc/motorcycle-monitor/config.yaml listings
/opt/motorcycle-monitor/.venv/bin/motorcycle-monitor --config /etc/motorcycle-monitor/config.yaml listings --review
```

Listings display readable bike details, price, mileage, availability, power
evidence and direct links. `--all` includes rejected bikes; `--json` supplies the
machine-readable output. A dry-run does not save results, so run a normal scan
before inspecting the saved list.

Read-only commands (`listings`, `status`, `history`, `changeover`) can run during
a scan and show committed database results. On an older installed version,
"Another scan or publisher holds the monitor lock" also blocks reads: wait for
the scan to finish, then install the updated code. Check scan progress with
`systemctl status motorcycle-monitor.service --no-pager` or
`journalctl -u motorcycle-monitor.service -f`. Initial results may be incomplete
until the first scan finishes. Scans and publishers still share the write lock.

New bikes are added; existing bikes are updated without losing price/history
observations. Missing bikes are retained and marked **NO LONGER SEEN AVAILABLE**
after two complete successful scans, at least twelve hours apart, with unchanged
search configuration. This is inferred absence, not confirmation of a sale.
Failures reset the absence streak. Partial manual imports and dry-runs cannot
mark other bikes unavailable. A bike still present on another recorded source
stays available. Returning bikes become available again and can issue a
reactivation alert. Availability changes are recorded in history and queued on
the MQTT status topic.

These defaults can be changed in `/etc/motorcycle-monitor/config.yaml`:

```yaml
availability:
  missing_scans: 2
  minimum_hours_between_misses: 12
```

The updated code applies SQLite migration 2 automatically on the next normal
scan. Copy the updated source and pyproject.toml, reinstall the package inside
its existing virtualenv, then run a normal scan. A non-editable pip installation
must be reinstalled for copied source changes to take effect:

```bash
cd /opt/motorcycle-monitor
.venv/bin/python -m pip install . 'playwright>=1.48,<2'
systemctl start motorcycle-monitor.service
```

## Desktop web dashboard

The dashboard serves the saved SQLite results directly from this LXC. It remains
running as a separate systemd service while the daily scan timer updates the
database. No Node.js, Docker, hosted service or additional Python dependency is
needed. The dashboard is a read-only LAN view, with no login or editing controls.

Copy the updated project from the development machine to the LXC using the copy
command above. Then **inside the LXC**, install and enable the dashboard:

```bash
cd /opt/motorcycle-monitor
.venv/bin/python -m pip install . 'playwright>=1.48,<2'
install -m 644 deploy/motorcycle-monitor-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now motorcycle-monitor-web.service
systemctl status motorcycle-monitor-web.service --no-pager
hostname -I
```

On your **desktop**, open `http://LXC_IP:8765/` in your browser, replacing LXC_IP
with the LAN address printed by `hostname -I`. For example, an LXC at
192.168.5.83 would use `http://192.168.5.83:8765/`; this is an example, not a
verified address of your container. If its firewall blocks incoming connections,
allow TCP 8765 from your desktop/LAN. The browser needs network reachability to
the LXC; do not use localhost on the desktop to refer to the container.

The page offers available matches, bikes needing review, unavailable/uncertain
bikes and all tracked records. Each card shows price, mileage, location, power
evidence, trade-in availability, original listing links and saved price/history.
Collection health shows the most recent recorded outcome for each source.
Results refresh every minute; the Refresh results button reads saved data and
does not start an external scan. The first scan must save results before bikes
appear. A failed refresh leaves previously loaded results visible with an error.

Existing configs work without changes. To change the listen address/port or
refresh interval, add this to `/etc/motorcycle-monitor/config.yaml`:

```yaml
web:
  host: 0.0.0.0
  port: 8765
  refresh_seconds: 60
```

Restart the web service after config or application updates:

```bash
systemctl restart motorcycle-monitor-web.service
journalctl -u motorcycle-monitor-web.service -n 50 --no-pager
```

The web service stays running independently of the scan service. Leave
`motorcycle-monitor.timer` enabled for daily inventory updates. Reinstalling the
application includes the packaged HTML/CSS/JavaScript assets; copying source
alone does not update a non-editable installed package.

## Regional full-power Ninja 650 search

`config.wellington-ninja.yaml` provides the requested search preset:

- Kawasaki Ninja 650 only, with positive unrestricted/full-power evidence.
- Strictly under 10,000 km (`max_odometer_km: 9999`).
- Wellington/Hutt and nearby suburbs, Kapiti–Horowhenua through Palmerston North,
  and Wairarapa towns through Masterton.
- All model years and no price ceiling (`min_year: null`, `max_price_nzd: null`).
- Uncertain power, mileage or exact location goes to review. A broad Manawatu or
  Wairarapa label alone does not prove that a bike is inside this area.

The named towns are configurable under `search.allowed_locations`. This is a
location-name filter, not a geocoded distance boundary. Other towns can be added
without changing code. `search.area_label` controls the dashboard's scope label.
An empty allowed_locations list restores nationwide eligibility.

Copy the updated project and `config.wellington-ninja.yaml` to
`/opt/motorcycle-monitor/` inside the LXC. Reinstall the application as usual.
Apply only the preset's search settings to the existing installed configuration,
preserving the broker, database path, web settings and other deployment values:

```bash
cd /opt/motorcycle-monitor
.venv/bin/python -m pip install . 'playwright>=1.48,<2'
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml
path = Path('/etc/motorcycle-monitor/config.yaml')
config = yaml.safe_load(path.read_text())
preset = yaml.safe_load(Path('config.wellington-ninja.yaml').read_text())
search = config.setdefault('search', {})
for key in ('max_price_nzd', 'max_odometer_km', 'coverage', 'area_label', 'models', 'allowed_locations'):
    search[key] = preset['search'][key]
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY
.venv/bin/motorcycle-monitor --config /etc/motorcycle-monitor/config.yaml validate-config
systemctl restart motorcycle-monitor-web.service
systemctl start motorcycle-monitor.service
```

Existing search URLs can remain broad; exact model, mileage, power and location
filtering happen locally. Previously stored records remain in history and All
tracked. The dashboard evaluates saved facts against the current requirements
without rewriting historical observations. A normal scan collects fresh facts.
