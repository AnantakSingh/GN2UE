"""Run the exporter inside Blender without the UI (socket/headless testing).

    exec(compile(open(r'c:/Projects/GNtoUEresearch/gnue_exporter/export_cli.py').read(),
                 'export_cli.py', 'exec'))

Env-style config via module-level constants patched by the caller, or edit here.
"""

import importlib
import sys

import bpy

REPO = r"c:\Projects\GNtoUEresearch"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import gnue_exporter.core           # noqa: E402
import gnue_exporter.frontend_bpy   # noqa: E402
importlib.reload(gnue_exporter.core)
importlib.reload(gnue_exporter.frontend_bpy)
from gnue_exporter.frontend_bpy import export_group  # noqa: E402

GROUP = globals().get("GNUE_GROUP", "RopeBridge_V1")
OUT = globals().get("GNUE_OUT", r"c:\Projects\GNtoUEresearch\export\ropebridge_v1")

ng = bpy.data.node_groups.get(GROUP)
if ng is None:
    print("CLI ERROR: node group %r not found (have: %s)"
          % (GROUP, [g.name for g in bpy.data.node_groups]))
else:
    ok, report, desc = export_group(ng, OUT)
    print("CLI RESULT:", "OK" if ok else "REFUSED")
    print(report)
