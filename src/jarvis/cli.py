"""jarvis: talk to the running daemon, or be the daemon.

Kept to stdlib imports at the top so `jarvis toggle` (what the hotkey runs)
starts in a few tens of milliseconds; the models only load under `daemon`.
"""

import json
import os
import socket
import subprocess
import sys
import time

USAGE = """\
usage: jarvis <command>

  daemon [--no-orb]     run the assistant (normally via systemd: jarvis.service)
  toggle                what the hotkey does: listen / stop listening / interrupt
  listen | release      hold-to-talk: start on key down, stop on key up
  cancel                stop talking and listening
  ask <text...>         send a typed request, as if you'd said it
  say <text...>         speak a line (no brain involved)
  reset                 forget the conversation
  settings              open the settings panel on the orb
  wake on|off|<model>   wake word (models: hey_jarvis alexa hey_mycroft hey_marvin)
  set <key> <value>     change a setting, e.g. set brain.model opus
  status                state, memory use, whether Claude is running
  watch                 print the daemon's event stream
  inject <file.npy|wav> run a recording through the pipeline (testing)
  quit                  stop the daemon
"""


def sock_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "jarvis.sock")


def connect(start=False):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(sock_path())
        return s
    except (FileNotFoundError, ConnectionRefusedError):
        if not start:
            raise SystemExit("jarvis isn't running (systemctl --user start jarvis)")
    subprocess.run(["systemctl", "--user", "start", "jarvis.service"], check=False)
    subprocess.Popen(["notify-send", "-a", "Jarvis", "-t", "2500", "Jarvis is starting up"])
    for _ in range(100):
        time.sleep(0.2)
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(sock_path())
            return s
        except (FileNotFoundError, ConnectionRefusedError):
            continue
    raise SystemExit("jarvis didn't start; see: journalctl --user -u jarvis")


def send(msg, start=False):
    s = connect(start=start)
    s.sendall((json.dumps(msg) + "\n").encode())
    f = s.makefile("r")
    line = f.readline()
    s.close()
    reply = json.loads(line) if line else {}
    if reply.get("ok") is False:
        raise SystemExit(reply.get("error"))
    return reply


def to_value(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        return
    cmd, rest = args[0], args[1:]

    if cmd == "daemon":
        from .daemon import run
        run(orb="--no-orb" not in rest)
    elif cmd in ("toggle", "listen"):
        send({"cmd": cmd}, start=True)
    elif cmd in ("release", "cancel", "reset", "quit", "reload"):
        send({"cmd": cmd})
    elif cmd == "say":
        send({"cmd": "say", "text": " ".join(rest)}, start=True)
    elif cmd == "settings":
        send({"cmd": "settings"}, start=True)
    elif cmd == "ask":
        send({"cmd": "ask", "text": " ".join(rest)}, start=True)
    elif cmd == "wake":
        if not rest:
            raise SystemExit("jarvis wake on|off|<model>")
        if rest[0] in ("on", "off"):
            send({"cmd": "set", "key": "wake.enabled", "value": rest[0] == "on"})
        else:
            send({"cmd": "set", "key": "wake.model", "value": rest[0]})
            send({"cmd": "set", "key": "wake.enabled", "value": True})
    elif cmd == "set":
        if len(rest) < 2:
            raise SystemExit("jarvis set <section.key> <value>")
        send({"cmd": "set", "key": rest[0], "value": to_value(" ".join(rest[1:]))})
    elif cmd == "status":
        r = send({"cmd": "status"})
        r.pop("ok", None)
        mem = r.pop("rss_mb", {})
        for k, v in r.items():
            print(f"{k:15} {v}")
        print(f"{'memory':15} " + ", ".join(f"{k} {v} MB" for k, v in mem.items()) +
              f"  (total {sum(mem.values())} MB)")
    elif cmd == "watch":
        s = connect()
        s.sendall(b'{"cmd":"subscribe"}\n')
        for line in s.makefile("r"):
            ev = json.loads(line)
            if ev.get("ev") in ("level",):
                continue
            if ev.get("ev") == "hello":
                ev = {"ev": "hello", "state": ev["state"]}
            print(json.dumps(ev), flush=True)
    elif cmd == "inject":
        path = os.path.abspath(rest[0])
        if path.endswith(".wav"):
            path = wav_to_npy(path)
        send({"cmd": "inject", "path": path}, start=True)
    else:
        print(USAGE, end="")
        sys.exit(2)


def wav_to_npy(path):
    import wave
    import numpy as np
    with wave.open(path) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    x = np.frombuffer(raw, dtype={2: np.int16, 4: np.int32}[width]).astype(np.float32)
    x /= float(2 ** (8 * width - 1))
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != 16000:
        x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype(np.float32)
    out = path[:-4] + ".16k.npy"
    np.save(out, x)
    return out


if __name__ == "__main__":
    main()
