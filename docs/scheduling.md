# Running genplis on a schedule

Use a **systemd user timer** on Linux for journal logging and catch-up runs,
or **cron** if that's what your system provides. Choose one, not both.
The examples run as your user and use your genplis configuration and cache.

## Before scheduling

1. Install genplis using the [Quickstart](index.md#quickstart).
2. Set your [collection path](config.md#path) in the configuration file,
   then run `genplis` without a path to check that it generates your playlists.
   Both schedules below rely on this setting.
3. Find the executable:

   ```bash
   command -v genplis
   ```

The examples assume `~/.local/bin/genplis`; substitute the path printed by
that command if it differs. Scheduled jobs don't normally inherit your
shell's `PATH`, so use an absolute path. For a clone, use the executable in
its `.venv/bin/` directory instead.

Make sure your music directory is mounted and writable when the job runs.

## systemd

### Create the units

Create the user-unit directory if needed:

```bash
mkdir -p ~/.config/systemd/user
```

Save this as `~/.config/systemd/user/genplis.service`:

```ini
[Unit]
Description=Generate M3U playlists with genplis

[Service]
Type=oneshot
ExecStart=%h/.local/bin/genplis --quiet
```

`%h` expands to your home directory. The service runs once and exits;
`--quiet` keeps only filter counts and playlist creation messages.

Save this as `~/.config/systemd/user/genplis.timer`:

```ini
[Unit]
Description=Run genplis daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

The timer starts the service with the same base name, daily at midnight.
`Persistent=true` catches up on a missed run when the timer next becomes
active, for example after boot or login.

### Enable and test

Load the units, enable the timer, and check its next run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now genplis.timer
systemctl --user list-timers genplis.timer
```

Test the service without waiting, then inspect its result and output:

```bash
systemctl --user start genplis.service
systemctl --user status genplis.service
journalctl --user -u genplis.service
```

For a successful oneshot service, `inactive (dead)` with `status=0/SUCCESS`
is normal. To stop future scheduled runs, use
`systemctl --user disable --now genplis.timer`.

### Run while logged out

To keep user services running after your last login session ends, enable
lingering:

```bash
loginctl enable-linger "$USER"
```

Without lingering, the timer runs only while your user manager is active;
missed runs are caught up at your next login.

### Change the schedule

For 03:30 each day, replace `OnCalendar=daily` in the timer with
`OnCalendar=*-*-* 03:30:00`. Check the expression before reloading:

```bash
systemd-analyze calendar '*-*-* 03:30:00'
systemctl --user daemon-reload
systemctl --user restart genplis.timer
```

See the [systemd timer examples](https://wiki.archlinux.org/title/Systemd/Timers#Examples)
for other schedules.

## cron

Open your personal crontab with `crontab -e` and add:

```cron
# Run genplis every day at 03:30 and append output to a log.
30 3 * * * mkdir -p "$HOME/.local/state" && "$HOME/.local/bin/genplis" --quiet >> "$HOME/.local/state/genplis.log" 2>&1
```

Check it was saved with `crontab -l`. To stop scheduling, remove the entry
with `crontab -e`.

The five time fields are minute, hour, day of month, month, and day of week;
`30 3 * * *` means 03:30 every day. The command uses `$HOME` so it doesn't
depend on shell expansion of `~`. Both normal output and errors go to
`~/.local/state/genplis.log`; rotate or clear this log occasionally.

Cron runs while you're logged out, provided the cron daemon is running.
Its service name varies by distribution: commonly `cron`, `crond`, or
`cronie`. Unlike the persistent systemd timer, cron **doesn't catch up** on
runs missed while the machine was off or asleep.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Executable not found, or `status=203/EXEC` | Recheck `command -v genplis` and the executable path in the job. |
| systemd timer doesn't run | Check `systemctl --user list-timers --all`; enable lingering if it must run while logged out. |
| Cron job doesn't run | Check that the cron daemon is running, then inspect its system log and `~/.local/state/genplis.log`. |
| Playlists don't change | Check the job's output and access to the music directory. No matches leave existing playlists untouched; see [Generated playlists](usage.md#generated-playlists). |

For more diagnostic output, replace `--quiet` with `--verbose`; see
[Output controls](usage.md#control-output-and-get-help).

### Custom config and cache locations

Jobs may not inherit `XDG_CONFIG_HOME` or `XDG_CACHE_HOME` set in your shell.
If you use custom locations, declare the same **absolute paths** in the job:

- **systemd:** add `Environment=` lines under `[Service]`, for example
  `Environment=XDG_CONFIG_HOME=/home/you/.config`.
- **cron:** add assignments above the schedule line, for example
  `XDG_CONFIG_HOME=/home/you/.config`.

Set `XDG_CACHE_HOME` the same way if needed. For genplis defaults and explicit
config-file options, see [Configuration](config.md#location-and-loading).

## See also

- [Usage guide](usage.md)
- [Configuration reference](config.md)
- [systemd.timer manual](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [crontab(5) manual](https://man7.org/linux/man-pages/man5/crontab.5.html)
