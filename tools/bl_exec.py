"""Run a Python file inside the open Blender through the blender-mcp addon socket.

    python tools/bl_exec.py build_proxring.py
    python tools/bl_exec.py gnue_exporter/export_cli.py --set GNUE_GROUP=ProxRing

Injects GNUE_REPO (this repo) plus any --set KEY=VALUE as globals of the exec'd
script, so socket-exec'd scripts never need a hardcoded repo path (PORTABILITY.md
§2.4). Needs Blender open with the blender-mcp addon listening (port 9876).

Single-shot and bounded on purpose: one connection, one script, one hard
timeout, no retries — never loop this against a busy editor.
For a Blender that is not open, use:  blender --background --python <script>
"""

import argparse
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gnue_paths  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("script", help="python file to run inside Blender")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="extra global for the script (repeatable), e.g. GNUE_GROUP=ProxRing")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds (hard deadline)")
    a = ap.parse_args()

    script = os.path.abspath(a.script)
    if not os.path.isfile(script):
        sys.exit("bl_exec: no such file: %s" % script)
    g = {"GNUE_REPO": gnue_paths.repo_root(), "__name__": "__main__"}
    for kv in a.set:
        k, eq, v = kv.partition("=")
        if not k or not eq:
            sys.exit("bl_exec: --set expects KEY=VALUE, got %r" % kv)
        g[k] = v

    code = ("import traceback\n"
            "__g = %r\n"
            "try:\n"
            "    exec(compile(open(%r, encoding='utf-8').read(), %r, 'exec'), __g)\n"
            "except Exception:\n"
            "    traceback.print_exc()\n" % (g, script, script))

    try:
        s = socket.create_connection(("127.0.0.1", a.port), timeout=a.timeout)
    except OSError as e:
        sys.exit("bl_exec: cannot reach Blender on port %d (%s).\n"
                 "  Open Blender with the blender-mcp addon running, or run headless:\n"
                 "  blender --background --python %s" % (a.port, e, a.script))
    s.sendall(json.dumps({"type": "execute_code", "params": {"code": code}}).encode())
    s.settimeout(a.timeout)
    data = b""
    while True:
        try:
            chunk = s.recv(1 << 16)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
        try:
            json.loads(data)
            break
        except ValueError:
            continue
    s.close()
    if not data:
        sys.exit("bl_exec: no response from Blender within %.0fs" % a.timeout)
    r = json.loads(data)
    res = r.get("result", {})
    out = res.get("result", res) if isinstance(res, dict) else res
    print(out if isinstance(out, str) else json.dumps(r, indent=1)[:4000])


if __name__ == "__main__":
    main()
