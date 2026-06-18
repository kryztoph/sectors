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
