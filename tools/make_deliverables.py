"""Package the two client plugins into deliverables/.

    python tools/make_deliverables.py

Produces:
  deliverables/blender_addon/gnue_exporter-<ver>.zip   (Blender extension zip:
      blender_manifest.toml at zip root — Preferences > Extensions > Install from Disk)
  deliverables/unreal_plugin/GNueImporter-<ver>.zip    (unzip into <Project>/Plugins/)
"""

import os
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UE_PLUGIN = r"C:\Users\User\Documents\Unreal Projects\GNtoUE\Plugins\GNueImporter"
VERSION = "0.7.0"
SKIP_DIRS = {"__pycache__", "Intermediate"}


def add_tree(z, src_root, arc_root):
    count = 0
    for root, dirs, files in os.walk(src_root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".pyc", ".log", ".pdb")):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src_root)
            arc = os.path.join(arc_root, rel) if arc_root else rel
            z.write(full, arc)
            count += 1
    return count


def pack(zip_path, src_root, arc_root):
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        n = add_tree(z, src_root, arc_root)
    print("wrote %s (%d files, %d bytes)" % (zip_path, n, os.path.getsize(zip_path)))


# Blender extension: manifest at zip ROOT (extension format, Blender 4.2+)
pack(os.path.join(REPO, "deliverables", "blender_addon", "gnue_exporter-%s.zip" % VERSION),
     os.path.join(REPO, "gnue_exporter"), "")

# UE plugin: zip contains the GNueImporter/ folder itself
pack(os.path.join(REPO, "deliverables", "unreal_plugin", "GNueImporter-%s.zip" % VERSION),
     UE_PLUGIN, "GNueImporter")

print("DELIVERABLES DONE")
