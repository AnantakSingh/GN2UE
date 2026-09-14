"""Assemble the self-contained GNueImporter UE plugin from repo sources.

Run:  python tools/sync_ue_plugin.py [<ue_project_dir>]

Copies/derives:
  gnue_eval.py     <- evaluator section of gnue_exporter/core.py (bpy-free)
  gnue_pcg.py      <- ue_importer/import_gnue.py (v1 helpers; main() is guarded)
  gnue_importer.py <- ue_importer/import_gnue2.py with plugin-local imports and
                      a callable main(folder, dest)
  init_unreal.py   <- authored in this script (menus + GNueDrops scan)
  README.md        <- ue_plugin_src/README.md
  GNueImporter.uplugin

The plugin never imports from the repo — plug-and-play for end users.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gnue_paths  # noqa: E402  (GNUE_* env / gnue.config.json / auto-discovery — PORTABILITY.md)

REPO = gnue_paths.repo_root()
# argv[1] is the highest-priority override; otherwise the resolver decides
PROJECT = sys.argv[1] if len(sys.argv) > 1 else gnue_paths.ue_project()
PLUGIN = os.path.join(PROJECT, "Plugins", "GNueImporter")
PY = os.path.join(PLUGIN, "Content", "Python")


def read(p):
    with open(os.path.join(REPO, p), "r", encoding="utf-8") as f:
        return f.read()


def write(rel, text):
    path = os.path.join(PLUGIN, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote", path)


# ---- gnue_eval.py: evaluator slice of core.py
core = read("gnue_exporter/core.py")
start = core.index("# ------------------------------------------------------------------ evaluator")
end = core.index("# ------------------------------------------------------------------ pipeline")
write("Content/Python/gnue_eval.py",
      '"""Expression evaluator (generated from gnue_exporter/core.py — do not edit;\n'
      'run tools/sync_ue_plugin.py in the research repo instead)."""\n\n'
      + core[start:end].rstrip() + "\n")

# ---- gnue_pcg.py: verbatim v1 importer (helpers; main() import-guarded)
write("Content/Python/gnue_pcg.py",
      '"""PCG build helpers (generated copy of ue_importer/import_gnue.py)."""\n'
      + read("ue_importer/import_gnue.py"))

# ---- gnue_importer.py: v2 importer with local imports + callable main
imp2 = read("ue_importer/import_gnue2.py")
old_imports = """_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (_HERE, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from gnue_exporter.core import evaluate, NonConstant           # noqa: E402
from import_gnue import (add_node, connect, import_fbx,        # noqa: E402
                         set_spawner_mesh, safe_set, log, warn, WARNINGS)"""
new_imports = """from gnue_eval import evaluate, NonConstant                    # noqa: E402
from gnue_pcg import (add_node, connect, import_fbx,           # noqa: E402
                      set_spawner_mesh, safe_set, log, warn, WARNINGS)"""
assert old_imports in imp2, "import block drifted — update sync_ue_plugin.py"
imp2 = imp2.replace(old_imports, new_imports)

old_main = '''def main(folder=None, dest=None, param_overrides=None, meshes_dest=None):
    folder = folder or os.environ.get("GNUE2_DIR") or os.path.join(_REPO, "export", "ropebridge_v1")'''
new_main = '''def main(folder=None, dest=None, param_overrides=None, meshes_dest=None):
    del WARNINGS[:]
    folder = folder or os.environ.get("GNUE2_DIR")
    if not folder:
        raise ImportError2("no descriptor folder given")'''
assert old_main in imp2, "main() header drifted — update sync_ue_plugin.py"
imp2 = imp2.replace(old_main, new_main)

old_tail = '''    for w in WARNINGS:
        print("GNUE2 WARNING: %s" % w)


if __name__ == "__main__":
    main()'''
new_tail = '''    for w in WARNINGS:
        print("GNUE2 WARNING: %s" % w)
    return {"graph": graph.get_path_name(), "groups": len(groups),
            "counts": counts, "warnings": list(WARNINGS), "result": result}


if __name__ == "__main__":
    main()'''
assert old_tail in imp2
imp2 = imp2.replace(old_tail, new_tail)
write("Content/Python/gnue_importer.py",
      '"""GNue descriptor importer (generated from ue_importer/import_gnue2.py)."""\n' + imp2)

# ---- init_unreal.py
write("Content/Python/init_unreal.py", read("tools/plugin_init_unreal.py"))

# ---- plugin README (repo copy is canonical, so it can't drift)
write("README.md", read(os.path.join("ue_plugin_src", "README.md")))

# ---- binary rebuild script for engine-version mismatches
write("RebuildBinaries.bat", read(os.path.join("ue_plugin_src", "RebuildBinaries.bat")))

# ---- C++ module source (ue_plugin_src/Source -> plugin Source)
src_root = os.path.join(REPO, "ue_plugin_src", "Source")
for root, dirs, files in os.walk(src_root):
    for f in files:
        full = os.path.join(root, f)
        rel = os.path.relpath(full, src_root)
        with open(full, "r", encoding="utf-8") as fh:
            write(os.path.join("Source", rel), fh.read())

# ---- modules
# A module declared in the .uplugin MUST have binaries: UE 5.8 has no "Optional"
# module flag, and a missing one stops the WHOLE plugin (menus and all) from
# loading. So GNuePCG (the custom PCG node) is only declared once it is built -
# tools/build_ue_plugin.ps1 sets GNUE_DECLARE_PCG=1 to declare it for the build
# itself, and every later sync sees the .dll and keeps it. Without the module
# the importer still works, falling back to approximate proximity scaling.
MODULES = [{"Name": "GNueParams", "Type": "Editor", "LoadingPhase": "Default"}]
_pcg_dll = os.path.join(PLUGIN, "Binaries", "Win64", "UnrealEditor-GNuePCG.dll")
if os.path.exists(_pcg_dll) or os.environ.get("GNUE_DECLARE_PCG") == "1":
    # Runtime (not Editor) so imported graphs also work in cooked builds.
    MODULES.append({"Name": "GNuePCG", "Type": "Runtime", "LoadingPhase": "Default"})
else:
    print("NOTE: GNuePCG binaries not found - module left undeclared. Run "
          "tools/build_ue_plugin.ps1 with the editor closed for exact "
          "proximity scaling.")


# ---- uplugin
write("GNueImporter.uplugin", json.dumps({
    "FileVersion": 3,
    "Version": 1,
    "VersionName": gnue_paths.version(),   # single source: blender_manifest.toml
    "FriendlyName": "GNue Importer",
    "Description": "Import Blender Geometry Nodes effects exported by the GN to UE "
                   "exporter as parametric PCG graphs. Drop export folders into "
                   "<Project>/GNueDrops/ or use Tools > GNue Importer.",
    "Category": "Importers",
    "CreatedBy": "GNtoUE research",
    "CanContainContent": True,
    "EnabledByDefault": True,
    "Modules": MODULES,
    "Plugins": [
        {"Name": "PCG", "Enabled": True},
        # Mesh Sampler (scatter on arbitrary mesh surfaces) lives here and is
        # not enabled by default — declaring it makes UE auto-enable it.
        {"Name": "PCGGeometryScriptInterop", "Enabled": True},
        {"Name": "PythonScriptPlugin", "Enabled": True},
    ],
}, indent=1))

print("SYNC DONE")
