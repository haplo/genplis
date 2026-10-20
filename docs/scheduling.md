# Running genplis on a schedule

Genplis scans the collection, writes the playlists, and exits, which makes it a
good fit for a timer. This page shows how to run it automatically once a day
with systemd or cron. Both examples run genplis as your user, so they read your
config file and write to your cache.

For the options genplis accepts, see
[Usage](https://github.com/haplo/genplis/blob/main/docs/usage.md); for the
collection path, see
[Configuration](https://github.com/haplo/genplis/blob/main/docs/config.md).

## Install genplis for your user

Genplis is not on PyPI yet, so install it from the repository with
[uv](https://github.com/astral-sh/uv):

```bash
uv tool install git+https://github.com/haplo/genplis.git
```

`uv tool` installs the `genplis` executable into `~/.local/bin`:

```bash
command -v genplis
# /home/you/.local/bin/genplis
```

Use that absolute path in the service or crontab below. Scheduled jobs run with
a minimal environment that does not necessarily include `~/.local/bin` in
`PATH`. If you already work from a clone, point at its environment instead:
`%h/Code/genplis/.venv/bin/genplis` for systemd, or
`$HOME/Code/genplis/.venv/bin/genplis` for cron.

## Configure the collection

Both examples run `genplis` without arguments, so set the collection path in the
config file. Edit `~/.config/genplis/config.ini` (or
`$XDG_CONFIG_HOME/genplis/config.ini`):

```ini
[collection]
path = ~/Music
```

Genplis expands `~` itself in config files. Run it once by hand to make sure the
configuration works before scheduling it:

```bash
genplis
```

## systemd

systemd timers are the preferred option on most Linux distributions. They
integrate with the journal, can catch up on runs missed while the machine was
off, and keep running after you log out when lingering is enabled.

### Create the service

Write `~/.config/systemd/user/genplis.service`:

```ini
[Unit]
Description=Generate M3U playlists with genplis

[Service]
Type=oneshot
ExecStart=%h/.local/bin/genplis
```

`Type=oneshot` is correct because the process scans the collection and exits;
there is no daemon to keep running. `%h` expands to your home directory, so you
do not need to hard-code a username. Add `--verbose` to `ExecStart` while
troubleshooting; output goes to the journal either way.

### Create the timer

Write `~/.config/systemd/user/genplis.timer`:

```ini
[Unit]
Description=Run genplis daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

A timer automatically controls the service with the same base name, so
`genplis.timer` starts `genplis.service`. `OnCalendar=daily` means every day at
00:00. `Persistent=true` runs the job after boot or resume when the scheduled
time was missed, so a machine that was asleep at midnight still updates its
playlists afterwards.

### Enable the timer

```bash
systemctl --user daemon-reload
systemctl --user enable --now genplis.timer
```

Check that the timer is scheduled:

```bash
systemctl --user list-timers genplis.timer
```

Run the service once without waiting for the timer:

```bash
systemctl --user start genplis.service
systemctl --user status genplis.service
```

A successful oneshot service reports `inactive (dead)` with
`status=0/SUCCESS`; that is normal. Read its output with:

```bash
journalctl --user -u genplis.service
```

### Run while logged out

User services stop when your last session ends unless lingering is enabled.
For a server, or for a machine you want updated while logged out, enable it:

```bash
loginctl enable-linger "$USER"
```

Check the setting with `loginctl show-user "$USER" --property=Linger`. Without
lingering, the timer only runs while you have a user session, and
`Persistent=true` catches up at your next login.

### Change the schedule

`OnCalendar=` accepts systemd calendar expressions. To run every day at 03:30
instead, use:

```ini
[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
```

Verify an expression, including its next elapse times, with:

```bash
systemd-analyze calendar '*-*-* 03:30:00'
```

The [systemd/Timers examples on the Arch
Wiki](https://wiki.archlinux.org/title/Systemd/Timers#Examples) show hourly,
weekly, monthly, and boot-relative schedules. After editing a unit, reload the
user manager and restart the timer:

```bash
systemctl --user daemon-reload
systemctl --user restart genplis.timer
```

### Troubleshooting

- **`status=203/EXEC` or "No such file or directory"** — the `ExecStart` path
  is wrong. Check it with `command -v genplis` and use the absolute path.
- **The config file is ignored** — services start with a minimal environment.
  If you set `XDG_CONFIG_HOME` or `XDG_CACHE_HOME` in your shell, set the same
  variables in the unit with `Environment=`.
- **Playlists do not change** — run the service manually and read the journal.
  Genplis only writes a playlist when at least one song matches, and leaves an
  existing playlist untouched otherwise.
- **The timer never fires** — check `systemctl --user list-timers --all` and
  make sure lingering is enabled if you are not logged in.

## cron

Cron is available on systems without systemd, or if you prefer it. The example
below adds a job to your personal crontab that runs genplis every day at 03:30.

### Create the crontab entry

Open your crontab:

```bash
crontab -e
```

Add this line, adjusting the time if you like:

```cron
# Run genplis every day at 03:30.
30 3 * * * mkdir -p "$HOME/.local/state" && "$HOME/.local/bin/genplis" >> "$HOME/.local/state/genplis.log" 2>&1
```

The five fields are minute, hour, day of month, month, and day of week, so
`30 3 * * *` means 03:30 every day. Cron runs the command through `/bin/sh`,
which expands `$HOME`; use that instead of `~`, which is not guaranteed to
expand.

Cron only sends output by mail when a mail transport is configured, so the
example appends stdout and stderr to a log instead. The log grows slowly, but
you may want to truncate it or add it to `logrotate`.

Check that the entry was saved with:

```bash
crontab -l
```

### Run while logged out

Cron jobs are started by the cron daemon, not by your login session, so nothing
extra is needed to run them while you are logged out. The daemon itself must be
running; on systemd distributions that usually means enabling the distribution's
cron service, for example:

```bash
sudo systemctl enable --now cronie
```

The service name differs between distributions (`cronie`, `cron`, `crond`).

### Troubleshooting

- **`genplis: not found`** — use the absolute path as in the example. Cron does
  not read your shell's `PATH`.
- **The config file is ignored** — if you set `XDG_CONFIG_HOME` or
  `XDG_CACHE_HOME` in your shell, declare the same values at the top of the
  crontab, one per line:
  ```cron
  XDG_CONFIG_HOME=/home/you/.config
  XDG_CACHE_HOME=/home/you/.cache
  ```
- **Nothing ran** — check that the cron daemon is running and inspect its log
  (`journalctl -u cronie` on many distributions, or `/var/log/cron` /
  `/var/log/syslog` elsewhere). Then check
  `~/.local/state/genplis.log`.
- **A run was skipped** — cron does not catch up on runs missed while the
  machine was off or asleep. Use the systemd timer with `Persistent=true`, or
  [anacron](https://man.archlinux.org/man/anacron.8), if you need that.

## See also

- [Usage guide](https://github.com/haplo/genplis/blob/main/docs/usage.md)
- [Configuration reference](https://github.com/haplo/genplis/blob/main/docs/config.md)
- [systemd/Timers on the Arch Wiki](https://wiki.archlinux.org/title/Systemd/Timers)
- [systemd.timer manual](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [crontab(5) manual](https://man7.org/linux/man-pages/man5/crontab.5.html)
