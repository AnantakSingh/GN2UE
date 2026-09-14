"""Package the two client plugins into deliverables/.

    python tools/make_deliverables.py [--dry-run]

Produces:
  deliverables/blender_addon/gnue_exporter-<ver>.zip   (Blender extension zip:
      blender_manifest.toml at zip root — Preferences > Extensions > Install from Disk)
  deliverables/unreal_plugin/GNueImporter-<ver>.zip    (unzip into <Project>/Plugins/)

Run tools/sync_ue_plugin.py first so the packaged UE plugin is current. The
version has ONE source — gnue_exporter/blender_manifest.toml — and this script
refuses to package if bl_info or the synced .uplugin has drifted from it.
The UE plugin location comes from tools/gnue_paths.py (PORTABILITY.md).
"""

import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gnue_paths  # noqa: E402

REPO = gnue_paths.repo_root()
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


def version_drift(plugin_dir, version):
    """Everything that carries a version must equal the manifest's."""
    problems = []
    init_py = os.path.join(REPO, "gnue_exporter", "__init__.py")
    with open(init_py, "r", encoding="utf-8") as f:
        m = re.search(r'"version"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', f.read())
    bl = ".".join(m.groups()) if m else None
    if bl != version:
        problems.append("gnue_exporter/__init__.py bl_info version %s != manifest %s" % (bl, version))
    uplugin = os.path.join(plugin_dir, "GNueImporter.uplugin")
    if os.path.isfile(uplugin):
        with open(uplugin, "r", encoding="utf-8") as f:
            vn = json.load(f).get("VersionName")
        if vn != version:
            problems.append("%s VersionName %s != manifest %s (run tools/sync_ue_plugin.py)"
                            % (uplugin, vn, version))
    else:
        problems.append("no synced plugin at %s (run tools/sync_ue_plugin.py first)" % uplugin)
    return problems


def main(argv):
    dry = "--dry-run" in argv
    version = gnue_paths.version()
    plugin = gnue_paths.plugin_dir()
    bl_zip = os.path.join(REPO, "deliverables", "blender_addon", "gnue_exporter-%s.zip" % version)
    ue_zip = os.path.join(REPO, "deliverables", "unreal_plugin", "GNueImporter-%s.zip" % version)
    print("version    %s  (gnue_exporter/blender_manifest.toml)" % version)
    print("ue plugin  %s" % plugin)
    print("blender    %s" % bl_zip)
    print("unreal     %s" % ue_zip)

    problems = version_drift(plugin, version)
    for p in problems:
        print("VERSION DRIFT:", p)
    if problems:
        return 1
    if dry:
        print("DRY RUN - nothing written")
        return 0

    # Blender extension: manifest at zip ROOT (extension format, Blender 4.2+)
    pack(bl_zip, os.path.join(REPO, "gnue_exporter"), "")
    # UE plugin: zip contains the GNueImporter/ folder itself
    pack(ue_zip, plugin, "GNueImporter")
    print("DELIVERABLES DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
