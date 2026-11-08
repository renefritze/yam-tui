#!/usr/bin/env python3
"""Minimal curses TUI for Yamaha RX-V475 (XML /YamahaRemoteControl/ctrl API).

Usage: yam-tui [receiver-ip] [switches]   (default host: $YAMAHA_HOST or 192.168.0.94)
Without switches the TUI starts; with switches only those actions run (see --help).

Keys:  p power   ↑/↓ volume   m mute   ←/→ or 0-9 input   s sound program
       o HDMI out on/off   r refresh   q quit
"""
import argparse
import curses
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

POLL_MS = 2000
VOL_STEP = 5  # in 0.1 dB units
VOL_MIN, VOL_MAX = -800, 165
# number key -> input; 0 is AUDIO, 1-5 are HDMI1-5, 6-9 are AV1-4
HOTKEYS = {"0": "AUDIO"} | {str(n): f"HDMI{n}" for n in range(1, 6)} | {str(n + 5): f"AV{n}" for n in range(1, 5)}
PROGRAMS = [
    "Hall in Munich", "Hall in Vienna", "Chamber", "Cellar Club",
    "The Roxy Theatre", "The Bottom Line", "Sci-Fi", "Action Game",
    "Roleplaying Game", "Music Video", "Standard", "Spectacle", "Adventure",
    "Drama", "Mono Movie", "Surround Decoder", "2ch Stereo", "7ch Stereo",
]


class Receiver:
    def __init__(self, host):
        self.url = f"http://{host}/YamahaRemoteControl/ctrl"

    def _send(self, cmd, inner):
        body = f'<YAMAHA_AV cmd="{cmd}">{inner}</YAMAHA_AV>'.encode()
        with urllib.request.urlopen(self.url, body, timeout=3) as r:
            root = ET.fromstring(r.read())
        rc = root.get("RC", "0")
        if rc != "0":
            raise ValueError(f"receiver returned RC={rc}")
        return root

    def put(self, inner):
        self._send("PUT", inner)

    def put_main(self, inner):
        self.put(f"<Main_Zone>{inner}</Main_Zone>")

    def status(self):
        r = self._send("GET", "<Main_Zone><Basic_Status>GetParam</Basic_Status></Main_Zone>")
        t = lambda p: (r.findtext(".//" + p) or "").strip()
        return {
            "power": t("Power_Control/Power") == "On",
            "vol": int(t("Volume/Lvl/Val") or 0),
            "mute": t("Volume/Mute") == "On",
            "input": t("Input/Input_Sel"),
            "program": t("Current/Sound_Program"),
            "straight": t("Current/Straight") == "On",
            "hdmi_out": t("HDMI/Output/OUT_1") == "On",
        }

    def inputs(self):
        r = self._send("GET", "<Main_Zone><Input><Input_Sel_Item>GetParam</Input_Sel_Item></Input></Main_Zone>")
        return [(i.findtext("Param"), i.findtext("Title").strip())
                for i in r.find(".//Input_Sel_Item")
                if i.findtext("RW") == "RW"]

    def set_power(self, on):
        self.put_main(f"<Power_Control><Power>{'On' if on else 'Standby'}</Power></Power_Control>")

    def set_volume(self, v):
        v = max(VOL_MIN, min(VOL_MAX, v))
        self.put_main(f"<Volume><Lvl><Val>{v}</Val><Exp>1</Exp><Unit>dB</Unit></Lvl></Volume>")

    def set_mute(self, on):
        self.put_main(f"<Volume><Mute>{'On' if on else 'Off'}</Mute></Volume>")

    def set_input(self, name):
        self.put_main(f"<Input><Input_Sel>{name}</Input_Sel></Input>")

    def set_program(self, name):
        self.put_main(f"<Surround><Program_Sel><Current><Sound_Program>{name}</Sound_Program></Current></Program_Sel></Surround>")

    def set_hdmi_out(self, on):
        self.put_main(f"<Sound_Video><HDMI><Output><OUT_1>{'On' if on else 'Off'}</OUT_1></Output></HDMI></Sound_Video>")


def draw(scr, host, st, err, inputs):
    scr.erase()
    h, w = scr.getmaxyx()

    def put(y, text, attr=0):
        if y < h - 1:
            scr.addnstr(y, 2, text, max(w - 3, 0), attr)

    put(0, f"Yamaha RX-V475  {host}", curses.A_BOLD)
    if err:
        put(2, f"! {err}", curses.A_REVERSE)
    if st:
        db = st["vol"] / 10
        barw = max(min(w - 30, 40), 5)
        fill = round(barw * (st["vol"] - VOL_MIN) / (VOL_MAX - VOL_MIN))
        put(3, f"Power     {'ON' if st['power'] else 'standby'}", curses.A_BOLD if st["power"] else 0)
        put(4, f"Volume    [{'#' * fill}{'-' * (barw - fill)}] {db:+.1f} dB")
        put(5, f"Mute      {'ON' if st['mute'] else 'off'}")
        put(6, f"HDMI out  {'on' if st['hdmi_out'] else 'OFF'}")
        put(7, f"Program   {st['program']}{' (straight)' if st['straight'] else ''}")
        put(9, "Input", curses.A_BOLD)
        for n, (param, title) in enumerate(inputs):
            cur = param == st["input"]
            key = next((k for k, v in HOTKEYS.items() if v == param), " ")
            put(10 + n, f"{'>' if cur else ' '} {key} {param:<10} {title}", curses.A_REVERSE if cur else 0)
    help_lines = [
        "p        power",
        "↑ / ↓    volume",
        "m        mute",
        "0-9      input (see list)",
        "← / →    prev / next input",
        "s        next sound program",
        "o        HDMI out on/off",
        "r        refresh",
        "q        quit",
    ]
    if w >= 78:
        for n, line in enumerate(help_lines):
            if 3 + n < h:
                scr.addnstr(3 + n, 52, line, w - 53, curses.A_DIM)
    elif h > 1:
        scr.addnstr(h - 1, 2, "p pwr ↑↓ vol m mute 0-9/←→ input s prog o hdmi r q", max(w - 3, 0), curses.A_DIM)
    scr.refresh()


def main(scr, host):
    curses.curs_set(0)
    scr.keypad(True)
    scr.timeout(POLL_MS)
    rx = Receiver(host)
    st, err, inputs = None, None, []

    def refresh():
        nonlocal st, err, inputs
        try:
            st = rx.status()
            if not inputs:
                inputs = rx.inputs()
            err = None
        except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as e:
            err = f"{type(e).__name__}: {getattr(e, 'reason', e)}"

    def act(fn, *args):
        nonlocal err
        try:
            fn(*args)
        except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as e:
            err = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
            return
        refresh()

    refresh()
    while True:
        draw(scr, host, st, err, inputs)
        k = scr.getch()
        if k in (ord("q"), 27):
            return
        if k in (-1, ord("r"), curses.KEY_RESIZE):
            refresh()
        elif not st:
            continue
        elif k == ord("p"):
            act(rx.set_power, not st["power"])
        elif k in (curses.KEY_UP, ord("+"), ord("=")):
            act(rx.set_volume, st["vol"] + VOL_STEP)
        elif k in (curses.KEY_DOWN, ord("-")):
            act(rx.set_volume, st["vol"] - VOL_STEP)
        elif k == ord("m"):
            act(rx.set_mute, not st["mute"])
        elif k == ord("o"):
            act(rx.set_hdmi_out, not st["hdmi_out"])
        elif k == ord("s"):
            cur = PROGRAMS.index(st["program"]) if st["program"] in PROGRAMS else -1
            act(rx.set_program, PROGRAMS[(cur + 1) % len(PROGRAMS)])
        elif 0 <= k < 256 and chr(k) in HOTKEYS and HOTKEYS[chr(k)] in dict(inputs):
            act(rx.set_input, HOTKEYS[chr(k)])
        elif k in (curses.KEY_RIGHT, curses.KEY_LEFT, ord("\t")) and inputs:
            names = [p for p, _ in inputs]
            cur = names.index(st["input"]) if st["input"] in names else 0
            step = -1 if k == curses.KEY_LEFT else 1
            act(rx.set_input, names[(cur + step) % len(names)])


def _onoff(v):
    return v == "on"


def build_parser():
    p = argparse.ArgumentParser(
        prog="yam-tui",
        description="Control a Yamaha RX-V475. Without action switches the TUI starts; "
        "with one or more, only those actions are performed (in the order listed here).",
    )
    p.add_argument("host", nargs="?", default=os.environ.get("YAMAHA_HOST", "192.168.0.94"),
                   help="receiver address (default: $YAMAHA_HOST or 192.168.0.94)")
    tri = ["on", "off", "toggle"]
    p.add_argument("-p", "--power", choices=tri, help="power on/off/toggle")
    p.add_argument("-v", "--volume", type=float, metavar="DB",
                   help="set absolute volume in dB (use --volume=-30 for negatives)")
    p.add_argument("--vol-up", nargs="?", const=1, type=int, metavar="N",
                   help="raise volume by N steps of 0.5 dB (default 1)")
    p.add_argument("--vol-down", nargs="?", const=1, type=int, metavar="N",
                   help="lower volume by N steps of 0.5 dB (default 1)")
    p.add_argument("-m", "--mute", choices=tri, help="mute on/off/toggle")
    p.add_argument("-i", "--input", metavar="NAME",
                   help="select input by name (e.g. HDMI1, AV2, AUDIO) or hotkey digit 0-9")
    p.add_argument("--next-input", action="store_true", help="select next input")
    p.add_argument("--prev-input", action="store_true", help="select previous input")
    p.add_argument("-s", "--program", metavar="NAME", help="select sound program by name")
    p.add_argument("--next-program", action="store_true", help="select next sound program")
    p.add_argument("-o", "--hdmi-out", choices=tri, help="HDMI out on/off/toggle")
    p.add_argument("--list-inputs", action="store_true", help="print available inputs")
    p.add_argument("--list-programs", action="store_true", help="print known sound programs")
    p.add_argument("--status", action="store_true", help="print current status")
    return p


def _resolve(value, choices, what):
    """Case-insensitive match of value against choices."""
    for c in choices:
        if c.lower() == value.lower():
            return c
    raise ValueError(f"unknown {what} {value!r}; choose from: {', '.join(choices)}")


def run_actions(rx, a):
    if a.list_programs:
        print("\n".join(PROGRAMS))
    st = None

    def fresh():
        nonlocal st
        st = rx.status()
        return st

    if a.power:
        on = not fresh()["power"] if a.power == "toggle" else _onoff(a.power)
        rx.set_power(on)
        if on:
            time.sleep(1.5)  # receiver ignores commands while waking up
        st = None
    if a.volume is not None:
        rx.set_volume(round(a.volume * 10 / VOL_STEP) * VOL_STEP)
        st = None
    for n, sign in ((a.vol_up, 1), (a.vol_down, -1)):
        if n is not None:
            rx.set_volume((st or fresh())["vol"] + sign * n * VOL_STEP)
            st = None
    if a.mute:
        rx.set_mute(not fresh()["mute"] if a.mute == "toggle" else _onoff(a.mute))
        st = None
    if a.input or a.next_input or a.prev_input or a.list_inputs:
        inputs = rx.inputs()
        names = [p for p, _ in inputs]
        if a.list_inputs:
            for param, title in inputs:
                print(f"{param:<10} {title}")
        if a.input:
            name = HOTKEYS.get(a.input, a.input)
            rx.set_input(_resolve(name, names, "input"))
            st = None
        for flag, step in ((a.next_input, 1), (a.prev_input, -1)):
            if flag:
                cur_in = fresh()["input"]
                cur = names.index(cur_in) if cur_in in names else 0
                rx.set_input(names[(cur + step) % len(names)])
                st = None
    if a.program:
        rx.set_program(_resolve(a.program, PROGRAMS, "program"))
        st = None
    if a.next_program:
        prog = fresh()["program"]
        cur = PROGRAMS.index(prog) if prog in PROGRAMS else -1
        rx.set_program(PROGRAMS[(cur + 1) % len(PROGRAMS)])
        st = None
    if a.hdmi_out:
        rx.set_hdmi_out(not fresh()["hdmi_out"] if a.hdmi_out == "toggle" else _onoff(a.hdmi_out))
        st = None
    if a.status:
        s = fresh()
        print(f"power:    {'on' if s['power'] else 'standby'}")
        print(f"volume:   {s['vol'] / 10:+.1f} dB")
        print(f"mute:     {'on' if s['mute'] else 'off'}")
        print(f"input:    {s['input']}")
        print(f"program:  {s['program']}{' (straight)' if s['straight'] else ''}")
        print(f"hdmi out: {'on' if s['hdmi_out'] else 'off'}")


def cli(argv=None):
    parser = build_parser()
    a = parser.parse_args(argv)
    actions = {k: v for k, v in vars(a).items() if k != "host"}
    if not any(v not in (None, False) for v in actions.values()):
        try:
            curses.wrapper(main, a.host)
        except KeyboardInterrupt:
            pass
        return
    try:
        run_actions(Receiver(a.host), a)
    except (urllib.error.URLError, OSError, ValueError, ET.ParseError) as e:
        sys.exit(f"error: {type(e).__name__}: {getattr(e, 'reason', e)}")


if __name__ == "__main__":
    cli()
