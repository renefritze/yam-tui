# yam-tui

Minimal terminal UI for controlling a Yamaha RX-V475 AV receiver on your LAN
(uses the receiver's XML `/YamahaRemoteControl/ctrl` API; no dependencies).

```
uv tool install yam-tui     # or: pipx install yam-tui
yam-tui 192.168.0.94        # or set YAMAHA_HOST
```

| Key | Action |
|---|---|
| `p` | power |
| `↑` / `↓` | volume |
| `m` | mute |
| `0`–`9` | jump to input (`0` AUDIO, `1`–`5` HDMI1–5, `6`–`9` AV1–4) |
| `←` / `→` | previous / next input |
| `s` | next sound program |
| `o` | HDMI out on/off |
| `q` | quit |

## Command line

Pass any of these switches to skip the TUI and just perform the action(s):

```
yam-tui --power on --input HDMI1 --volume=-35
yam-tui --mute toggle
yam-tui --vol-up 4            # 4 steps of 0.5 dB
yam-tui --program "Chamber" --hdmi-out off
yam-tui 192.168.0.94 --status
```

Switches: `-p/--power`, `-v/--volume DB`, `--vol-up [N]`, `--vol-down [N]`,
`-m/--mute`, `-i/--input`, `--next-input`, `--prev-input`, `-s/--program`,
`--next-program`, `-o/--hdmi-out`, `--list-inputs`, `--list-programs`,
`--status`. `on|off|toggle` apply to power, mute and HDMI out. Put the host
before `--vol-up`/`--vol-down`, or use `YAMAHA_HOST`.

Other RX-V models using the same XML protocol will probably work, but only the
RX-V475 is tested.

## Releases

Every merge to `main` bumps the patch version from the latest `v*` git tag
(starting at `v0.1.0`), tags the commit and publishes to PyPI. For a minor/major bump, push the tag
yourself (e.g. `git tag v0.2.0 && git push --tags`) before merging.
