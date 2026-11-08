#!/usr/bin/env python3
"""Minimal curses TUI for Yamaha RX-V475 (XML /YamahaRemoteControl/ctrl API).

Usage: yam-tui [receiver-ip]      (default: $YAMAHA_HOST or 192.168.0.94)

Keys:  p power   ↑/↓ volume   m mute   ←/→ or 0-9 input   s sound program
       o HDMI out on/off   r refresh   q quit
"""
import curses
import os
import sys
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


def cli():
    host = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("YAMAHA_HOST", "192.168.0.94")
    try:
        curses.wrapper(main, host)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
