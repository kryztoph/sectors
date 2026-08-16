# Daily LaunchAgent

This LaunchAgent runs the sector rotation capture once each weekday at 5:30 PM
local time.

Install:

```sh
./scripts/install_daily_launchagent.sh
```

Run immediately after install:

```sh
launchctl kickstart -k "gui/$(id -u)/com.fox.sectors.daily"
```

Uninstall:

```sh
./scripts/uninstall_daily_launchagent.sh
```

Logs:

- `logs/daily.out`
- `logs/daily.err`

The daily runner keeps timestamped JSON snapshots under `state/snapshots/` and
timestamped Markdown reports under `reports/`. It also updates
`state/snapshots/latest.json`.

# Weekly LaunchAgent

This LaunchAgent runs the weekly cotpy commodity capture once each Friday at
5:45 PM local time.

Install:

```sh
./scripts/install_weekly_launchagent.sh
```

Run immediately after install:

```sh
launchctl kickstart -k "gui/$(id -u)/com.fox.sectors.cotpy.weekly"
```

Uninstall:

```sh
./scripts/uninstall_weekly_launchagent.sh
```

Logs:

- `logs/cotpy-weekly.out`
- `logs/cotpy-weekly.err`

The weekly runner regenerates `reports/cotpy/index.html` and one interactive
page per key commodity under `reports/cotpy/charts/`, then publishes the
refreshed `reports/cotpy` tree.
