"""Copy the SeaOfProbabilities plugin source into the UE project and enable it.

    python showcase/sea_of_probabilities/tools/sync_sea_plugin.py [--build]

Paths come from tools/gnue_paths.py (PORTABILITY.md). --build runs UBT for the
project's editor target afterwards (editor must be closed; SAC off).
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import gnue_paths  # noqa: E402

SRC = os.path.join(HERE, "..", "Plugin", "SeaOfProbabilities")
NAME = "SeaOfProbabilities"


def main(argv):
    project = gnue_paths.ue_project()
    dst = os.path.join(project, "Plugins", NAME)
    keep = {"Binaries", "Intermediate"}
    if os.path.isdir(dst):
        for entry in os.listdir(dst):
            if entry in keep:
                continue
            p = os.path.join(dst, entry)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    shutil.copytree(os.path.normpath(SRC), dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    n = sum(len(f) for _, _, f in os.walk(dst))
    print("synced %d files -> %s" % (n, dst))

    up = gnue_paths.uproject()
    with open(up, "r", encoding="utf-8") as f:
        data = json.load(f)
    plugins = data.setdefault("Plugins", [])
    if not any(p.get("Name") == NAME for p in plugins):
        plugins.append({"Name": NAME, "Enabled": True})
        with open(up, "w", encoding="utf-8") as f:
            json.dump(data, f, indent="\t")
        print("enabled plugin in", os.path.basename(up))
    else:
        print("plugin already enabled in", os.path.basename(up))

    if "--build" in argv:
        bat = os.path.join(gnue_paths.engine_root(), "Engine", "Build", "BatchFiles", "Build.bat")
        cmd = [bat, gnue_paths.editor_target(), "Win64", "Development", "-Project=" + up, "-WaitMutex", "-FromMsBuild"]
        print("BUILD:", " ".join(cmd))
        return subprocess.call(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
