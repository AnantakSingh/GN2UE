"""Single-shot client for the live Unreal editor's MCP server (streamable HTTP,
ModelContextProtocol plugin, http://127.0.0.1:8000/mcp).

    python ue_mcp.py list                         # tool names
    python ue_mcp.py describe <toolset_name>      # a toolset's tools (describe_toolset)
    python ue_mcp.py call <tool> '<json args>'    # one tools/call
    python ue_mcp.py py "<python source>"         # convenience: run python in the editor
                                                  # (uses the first tool whose name suggests it)
    options: --timeout S (default 90) --port N

Deliberately bounded (DECISIONS.md D-008): one process, one session, one call,
one hard timeout, no retries, no polling. Refuses to run if the machine already
has many python processes (the earlier fork-bomb signature). Requires the
editor to be open; a refused connection just means it isn't.
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
OPTS = {a.split("=")[0][2:]: (a.split("=", 1)[1] if "=" in a else True) for a in sys.argv[1:] if a.startswith("--")}
TIMEOUT = float(OPTS.get("timeout", 90))
BASE = "http://127.0.0.1:%s/mcp" % OPTS.get("port", "8000")
SESSION = None
RID = [0]


def python_process_count():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"], capture_output=True, text=True, timeout=10).stdout
        return sum(1 for ln in out.splitlines() if ln.lower().startswith("python.exe"))
    except Exception:
        return 0


def post(body):
    global SESSION
    req = urllib.request.Request(BASE, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if SESSION:
        req.add_header("mcp-session-id", SESSION)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        sid = r.headers.get("mcp-session-id")
        if sid:
            SESSION = sid
        raw = r.read().decode("utf-8", "replace")
    if "data:" in raw:   # SSE-wrapped
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                break
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:2000]}


def rpc(method, params=None):
    RID[0] += 1
    body = {"jsonrpc": "2.0", "id": RID[0], "method": method}
    if params is not None:
        body["params"] = params
    return post(body)


def connect():
    r = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "sea-ue-mcp", "version": "0.1"}})
    try:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    except Exception:
        pass
    return r


def tools():
    r = rpc("tools/list", {})
    return r.get("result", {}).get("tools", [])


def call(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    if "error" in r:
        return "RPC ERROR: %s" % json.dumps(r["error"])[:2000]
    res = r.get("result", {})
    parts = res.get("content", [])
    text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
    imgs = [p for p in parts if isinstance(p, dict) and p.get("type") == "image"]
    if imgs:
        import base64, os, time
        out = OPTS.get("image_out") or "ue_mcp_image_%d.png" % int(time.time())
        with open(out, "wb") as f:
            f.write(base64.b64decode(imgs[0]["data"]))
        text += "\n[image saved: %s]" % os.path.abspath(out)
    # some tools return {"returnValue":{"image":{"mimeType","data"}}} as text
    if "\"data\"" in text and ("\"image\"" in text or "\"mimeType\"" in text):
        try:
            import base64, os, time
            obj = json.loads(text)
            rv = obj.get("returnValue", obj)
            img = rv.get("image") if isinstance(rv, dict) and "image" in rv else rv   # {"image":{..}} or {mimeType,data}
            if isinstance(img, dict) and img.get("data"):
                out = OPTS.get("image_out") or "ue_mcp_image_%d.png" % int(time.time())
                with open(out, "wb") as f:
                    f.write(base64.b64decode(img["data"]))
                text = "[image saved: %s (%s)]" % (os.path.abspath(out), img.get("mimeType"))
        except Exception as e:
            text = "[image decode failed: %s] " % e + text[:200]
    if res.get("isError"):
        text = "TOOL ERROR: " + text
    return text or json.dumps(res)[:3000]


def main():
    n = python_process_count()
    if n > 30:
        sys.exit("ue_mcp: refusing to run - %d python processes already (fork-bomb guard). Investigate first." % n)
    if not ARGS:
        sys.exit(__doc__)
    try:
        connect()
        cmd = ARGS[0]
        if cmd == "list":
            for t in tools():
                print("%-40s %s" % (t["name"], (t.get("description") or "").strip().splitlines()[0][:100] if t.get("description") else ""))
        elif cmd == "describe":
            print(call("describe_toolset", {"toolset_name": ARGS[1]}))
        elif cmd == "call":
            print(call(ARGS[1], json.loads(ARGS[2]) if len(ARGS) > 2 else {}))
        elif cmd == "py":
            names = [t["name"] for t in tools()]
            cand = [t for t in names if "python" in t.lower() or "exec" in t.lower()]
            if not cand:
                sys.exit("ue_mcp: no python-execution tool among: %s" % names)
            print("using tool:", cand[0], file=sys.stderr)
            # common argument spellings; the server ignores unknown ones or errors clearly
            print(call(cand[0], {"code": ARGS[1], "script": ARGS[1], "python_code": ARGS[1]}))
        else:
            sys.exit("ue_mcp: unknown command %r" % cmd)
    except urllib.error.URLError as e:
        sys.exit("ue_mcp: cannot reach %s (%s) - is the editor open with the MCP plugin?" % (BASE, e.reason))
    except TimeoutError:
        sys.exit("ue_mcp: timed out after %.0fs - the editor's game thread is busy; not retrying." % TIMEOUT)
    finally:
        m = python_process_count()
        if m > n + 2:
            print("ue_mcp: WARNING python process count rose %d -> %d during this call" % (n, m), file=sys.stderr)


if __name__ == "__main__":
    main()
