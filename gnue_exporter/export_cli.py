"""Run the exporter inside Blender without the UI (socket/headless testing).

Over the blender-mcp socket (tools/bl_exec.py injects GNUE_REPO for you):
    python tools/bl_exec.py gnue_exporter/export_cli.py --set GNUE_GROUP=RopeBridge_V1

Headless:
    blender --background <file.blend> --python gnue_exporter/export_cli.py

Config via caller-injected globals or environment variables (PORTABILITY.md §2.4):
    GNUE_REPO   repo root — derived from __file__ when Blender runs the file directly
    GNUE_GROUP  node group to export           (default RopeBridge_V1)
    GNUE_OUT    output folder                  (default <repo>/export/<group, lowercased>)
"""

import importlib
import os
import sys

import bpy

REPO = (globals().get("GNUE_REPO") or os.environ.get("GNUE_REPO")
        or (os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if "__file__" in globals() else None))
if not REPO:
    raise RuntimeError("set GNUE_REPO before exec'ing export_cli.py - see PORTABILITY.md")
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import gnue_exporter.core           # noqa: E402
import gnue_exporter.frontend_bpy   # noqa: E402
importlib.reload(gnue_exporter.core)
importlib.reload(gnue_exporter.frontend_bpy)
from gnue_exporter.frontend_bpy import export_group  # noqa: E402

GROUP = globals().get("GNUE_GROUP") or os.environ.get("GNUE_GROUP") or "RopeBridge_V1"
OUT = (globals().get("GNUE_OUT") or os.environ.get("GNUE_OUT")
       or os.path.join(REPO, "export", GROUP.lower()))

ng = bpy.data.node_groups.get(GROUP)
if ng is None:
    print("CLI ERROR: node group %r not found (have: %s)"
          % (GROUP, [g.name for g in bpy.data.node_groups]))
else:
    ok, report, desc = export_group(ng, OUT)
    print("CLI RESULT:", "OK" if ok else "REFUSED")
    print(report)
