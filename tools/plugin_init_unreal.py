"""GNueImporter plugin bootstrap (runs on editor start via PythonScriptPlugin).

Adds  Tools > GNue Importer  menu entries and scans <Project>/GNueDrops/ for
effect folders exported from Blender. Safe under commandlets: menu/dialog work
is guarded and the startup scan only logs.
"""

import os
import subprocess

import unreal

OWNER = "GNueImporter"


def _drops_dir():
    d = os.path.join(unreal.SystemLibrary.get_project_directory(), "GNueDrops")
    os.makedirs(d, exist_ok=True)
    return os.path.normpath(d)


def _is_effect_dir(path):
    return os.path.isfile(os.path.join(path, "effect.gnue.json"))


def _effect_name(path):
    import json
    try:
        with open(os.path.join(path, "effect.gnue.json"), "r", encoding="utf-8") as f:
            return json.load(f)["source"]["node_group"].replace(" ", "_")
    except Exception:
        return None


def _is_imported(path, name):
    """Up-to-date only when the PCG graph AND every descriptor mesh exist —
    a missing/broken mesh must trigger repair on the next scan."""
    import json
    root = "/Game/GNueImport/%s" % name
    if not unreal.EditorAssetLibrary.does_asset_exist("%s/PCG_%s" % (root, name)):
        return False
    try:
        with open(os.path.join(path, "effect.gnue.json"), "r", encoding="utf-8") as f:
            desc = json.load(f)
        for a in desc.get("assets", []):
            mesh = os.path.splitext(os.path.basename(a["file"]))[0]
            if not unreal.EditorAssetLibrary.does_asset_exist("%s/Meshes/%s" % (root, mesh)):
                return False
    except Exception:
        return False
    return True


def import_folder(folder, show_dialog=True, param_overrides=None):
    import importlib
    import gnue_importer
    importlib.reload(gnue_importer)
    try:
        info = gnue_importer.main(folder, param_overrides=param_overrides)
    except Exception as e:
        unreal.log_error("[GNue] import failed for %s: %s" % (folder, e))
        if show_dialog:
            _msg("GNue import failed", "%s\n\n%s\n\nSee Output Log for details." % (folder, e))
        return None
    msg = ("Imported %s\n%d spawn groups (counts: %s)\n%d warnings"
           % (info["graph"], info["groups"], info["counts"], len(info["warnings"])))
    unreal.log("[GNue] " + msg.replace("\n", " | "))
    if show_dialog:
        _msg("GNue import complete", msg + "\n\nAssign the PCG graph to a PCG Volume to see it.")
    return info


def scan_drops(show_dialog=True, force=False):
    drops = _drops_dir()
    done, skipped, failed = [], [], []
    for sub in sorted(os.listdir(drops)):
        path = os.path.join(drops, sub)
        if not os.path.isdir(path) or not _is_effect_dir(path):
            continue
        name = _effect_name(path)
        if name is None:
            failed.append(sub)
            continue
        if not force and _is_imported(path, name):
            skipped.append(name)
            continue
        info = import_folder(path, show_dialog=False)
        (done if info else failed).append(name)
        if info:
            try:
                _refresh_instance_copies(name)  # keep per-volume copies current
            except Exception as e:
                unreal.log_warning("[GNue] instance-copy refresh for %s: %s" % (name, e))
    summary = ("GNueDrops scan: %d imported %s, %d up-to-date %s, %d failed %s"
               % (len(done), done, len(skipped), skipped, len(failed), failed))
    unreal.log("[GNue] " + summary)
    if show_dialog:
        _msg("GNueDrops scan", summary + ("\n\nFailures: see Output Log." if failed else ""))
    return done, skipped, failed


def _msg(title, text):
    try:
        unreal.EditorDialog.show_message(title, text, unreal.AppMsgType.OK)
    except Exception:
        unreal.log("[GNue] %s: %s" % (title, text))


def _pick_folder():
    """Windows folder picker via PowerShell (no file-dialog API in UE Python)."""
    ps = ("Add-Type -AssemblyName System.Windows.Forms;"
          "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
          "$f.Description = 'Pick a GNue export folder (contains effect.gnue.json)';"
          "if ($f.ShowDialog() -eq 'OK') { [Console]::Out.Write($f.SelectedPath) }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps],
                             capture_output=True, text=True, timeout=600)
        return out.stdout.strip() or None
    except Exception as e:
        unreal.log_error("[GNue] folder picker failed: %s" % e)
        return None


# ------------------------------------------------------------------ menu

def _entry(cls_name, label, tooltip, fn):
    @unreal.uclass()
    class _Entry(unreal.ToolMenuEntryScript):
        @unreal.ufunction(override=True)
        def execute(self, context):
            fn()
    _Entry.__name__ = cls_name
    e = _Entry()
    e.init_entry(OWNER, "LevelEditor.MainMenu.Tools.GNueImporter", "GNue", cls_name,
                 label, tooltip)
    return e


def _on_import_folder():
    folder = _pick_folder()
    if not folder:
        return
    if not _is_effect_dir(folder):
        _msg("Not a GNue folder", "%s\n\nhas no effect.gnue.json — pick the folder the "
             "Blender exporter wrote." % folder)
        return
    import_folder(folder)


def _on_scan():
    scan_drops(show_dialog=True, force=False)


def _on_reimport():
    scan_drops(show_dialog=True, force=True)


def _on_open_drops():
    os.startfile(_drops_dir())


def _read_instance_params(graph_instance, desc_params):
    """Read the volume's current parameter values (needs the GNueParams module
    to have declared them at import time). Bag names are sanitized identifiers;
    override keys keep the descriptor's original names."""
    import gnue_importer
    h = unreal.PCGGraphParametersHelpers
    out = {}
    for p in desc_params:
        name, t = p["name"], str(p["type"]).upper()
        bag = gnue_importer.param_bag_name(name)
        try:
            if t == "FLOAT":
                out[name] = float(h.get_double_parameter(graph_instance, bag))
            elif t == "INT":
                out[name] = int(h.get_int32_parameter(graph_instance, bag))
            elif t == "BOOL":
                out[name] = bool(h.get_bool_parameter(graph_instance, bag))
            elif t == "VECTOR":
                v = h.get_vector_parameter(graph_instance, bag)
                out[name] = [v.x, v.y, v.z]
        except Exception as e:
            unreal.log_warning("[GNue] read parameter %r failed: %s" % (name, e))
    return out


# ------------------------------------------------------- per-volume applies

_DESC_CACHE = {}


def _load_desc(folder):
    import json
    path = os.path.join(folder, "effect.gnue.json")
    mtime = os.path.getmtime(path)
    hit = _DESC_CACHE.get(folder)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, "r", encoding="utf-8") as f:
        desc = json.load(f)
    _DESC_CACHE[folder] = (mtime, desc)
    return desc


def _drop_folder_for(effect):
    for sub in os.listdir(_drops_dir()):
        path = os.path.join(_drops_dir(), sub)
        if os.path.isdir(path) and _is_effect_dir(path) and _effect_name(path) == effect:
            return path
    return None


def _effect_of_graph(graph):
    """/Game/GNueImport/<Effect>/... (base or Instances copy) -> effect name."""
    path = graph.get_path_name()
    if not path.startswith("/Game/GNueImport/"):
        return None
    parts = path.split("/")
    return parts[3] if len(parts) > 4 else None


def _gnue_components():
    try:
        actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    except Exception:
        return []
    out = []
    for a in actors:
        try:
            comp = a.get_component_by_class(unreal.PCGComponent)
        except Exception:
            comp = None
        if comp is None:
            continue
        gi = comp.get_editor_property("graph_instance")
        graph = gi.get_editor_property("graph") if gi else None
        if graph is None:
            continue
        effect = _effect_of_graph(graph)
        if effect:
            out.append((a, comp, gi, graph, effect))
    return out


def _apply_to_volume(actor, comp, gi, effect, values):
    """Build/refresh this volume's own graph copy with `values` and assign it.
    The base graph stays at descriptor defaults, so volumes can diverge."""
    import json
    import re
    import gnue_importer
    folder = _drop_folder_for(effect)
    if folder is None:
        unreal.log_warning("[GNue] no GNueDrops folder for effect %r" % effect)
        return None
    safe = re.sub(r"[^0-9A-Za-z_]", "_", actor.get_actor_label() or actor.get_name())
    base_root = "/Game/GNueImport/%s" % effect
    dest = "%s/Instances/%s" % (base_root, safe)
    info = gnue_importer.main(folder, dest=dest, param_overrides=values,
                              meshes_dest=base_root + "/Meshes")
    copy = unreal.load_asset(info["graph"])
    lib = getattr(unreal, "GNueParamLibrary", None)
    if lib is not None and copy is not None:
        desc = _load_desc(folder)
        spec = [{"name": gnue_importer.param_bag_name(p["name"]),
                 "type": str(p["type"]).lower(),
                 "default": values.get(p["name"], p["default"])}
                for p in desc.get("parameters", [])]
        lib.declare_parameters(copy, json.dumps(spec), True)  # copy defaults = applied values
    if copy is not None and gi.get_editor_property("graph") != copy:
        gi.set_editor_property("graph", copy)
    try:
        comp.generate(True)
    except Exception as e:
        unreal.log_warning("[GNue] regenerate: %s" % e)
    unreal.log("[GNue] applied parameters to %s (graph copy %s)"
               % (actor.get_actor_label(), dest))
    return info


def _refresh_instance_copies(effect):
    """After a Blender reimport of the base effect, rebuild every per-volume
    copy with the values it currently carries."""
    for a, comp, gi, graph, eff in _gnue_components():
        if eff != effect or "/Instances/" not in graph.get_path_name():
            continue
        folder = _drop_folder_for(effect)
        if folder is None:
            continue
        desc = _load_desc(folder)
        values = _read_instance_params(gi, desc.get("parameters", []))
        if values:
            _apply_to_volume(a, comp, gi, eff, values)


def _on_apply_params():
    """Menu action: apply the selected volume's Details-panel parameters now."""
    sel = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_selected_level_actors()
    target = None
    for a in sel:
        comp = a.get_component_by_class(unreal.PCGComponent)
        if comp:
            gi = comp.get_editor_property("graph_instance")
            graph = gi.get_editor_property("graph") if gi else None
            if graph is not None and _effect_of_graph(graph):
                target = (a, comp, gi, _effect_of_graph(graph))
                break
    if target is None:
        _msg("Apply Volume Parameters", "Select a PCG Volume that uses a GNue graph first.")
        return
    a, comp, gi, effect = target
    folder = _drop_folder_for(effect)
    if folder is None:
        _msg("Apply Volume Parameters",
             "No folder in GNueDrops matches effect %r." % effect)
        return
    values = _read_instance_params(gi, _load_desc(folder).get("parameters", []))
    if not values:
        _msg("Apply Volume Parameters",
             "No parameter values readable — is the GNueParams C++ module loaded?")
        return
    if _apply_to_volume(a, comp, gi, effect, values):
        _msg("Applied parameters",
             "%s now uses its own graph copy with these values — other volumes "
             "are unaffected." % a.get_actor_label())


# ------------------------------------------------------- auto-apply watcher

_AUTO = {"enabled": True, "cache": {}, "pending": {}, "accum": 0.0, "busy": False}


def _values_sig(gi, desc_params):
    vals = _read_instance_params(gi, desc_params)
    return tuple(sorted((k, str(v)) for k, v in vals.items()))


def _watch_tick(dt):
    if not _AUTO["enabled"] or _AUTO["busy"]:
        return
    _AUTO["accum"] += dt
    if _AUTO["accum"] < 0.75:
        return
    _AUTO["accum"] = 0.0
    import time
    now = time.time()
    for a, comp, gi, graph, effect in _gnue_components():
        key = comp.get_path_name()
        folder = _drop_folder_for(effect)
        if folder is None:
            continue
        desc_params = _load_desc(folder).get("parameters", [])
        try:
            sig = _values_sig(gi, desc_params)
        except Exception:
            continue
        prev = _AUTO["cache"].get(key)
        _AUTO["cache"][key] = sig
        if prev is None:
            continue
        if sig != prev:
            _AUTO["pending"][key] = now  # value moving — (re)start debounce
        elif key in _AUTO["pending"] and now - _AUTO["pending"][key] > 0.5:
            del _AUTO["pending"][key]  # settled — apply once
            _AUTO["busy"] = True
            try:
                values = _read_instance_params(gi, desc_params)
                _apply_to_volume(a, comp, gi, effect, values)
                gi2 = comp.get_editor_property("graph_instance")
                _AUTO["cache"][key] = _values_sig(gi2, desc_params)
            except Exception as e:
                unreal.log_warning("[GNue] auto-apply failed: %s" % e)
            finally:
                _AUTO["busy"] = False


def _on_toggle_auto():
    _AUTO["enabled"] = not _AUTO["enabled"]
    _msg("GNue auto-apply", "Auto-apply on parameter change is now %s."
         % ("ON" if _AUTO["enabled"] else "OFF"))


_KEEP = []


def _register_menus():
    menus = unreal.ToolMenus.get()
    tools = menus.extend_menu("LevelEditor.MainMenu.Tools")
    sub = tools.add_sub_menu(OWNER, "GNue", "GNueImporter", "GNue Importer",
                             "Import Blender Geometry Nodes effect folders")
    for cls_name, label, tip, fn in (
            ("GNueImportFolder", "Import Effect Folder...",
             "Pick a folder exported by the Blender GN to UE exporter", _on_import_folder),
            ("GNueScanDrops", "Scan GNueDrops",
             "Import any new effect folders found in <Project>/GNueDrops", _on_scan),
            ("GNueReimportDrops", "Reimport All Drops",
             "Force reimport of every effect folder in GNueDrops", _on_reimport),
            ("GNueApplyParams", "Apply Volume Parameters",
             "Rebuild the selected volume's effect from its Details-panel parameter "
             "values (requires the GNueParams module)", _on_apply_params),
            ("GNueToggleAuto", "Toggle Auto Apply",
             "Automatically apply parameter changes on GNue volumes when values "
             "settle (on by default)", _on_toggle_auto),
            ("GNueOpenDrops", "Open GNueDrops Folder",
             "Open the drop folder in Explorer", _on_open_drops)):
        e = _entry(cls_name, label, tip, fn)
        _KEEP.append(e)
        sub.add_menu_entry_object(e)
    menus.refresh_all_widgets()
    unreal.log("[GNue] menu registered under Tools > GNue Importer")


try:
    _register_menus()
except Exception as e:  # commandlets / headless: menus unavailable, imports still work
    unreal.log("[GNue] menu registration skipped: %s" % e)

try:
    scan_drops(show_dialog=False, force=False)
except Exception as e:
    unreal.log_warning("[GNue] startup drops scan failed: %s" % e)

try:
    _WATCH_HANDLE = unreal.register_slate_post_tick_callback(_watch_tick)
    unreal.log("[GNue] auto-apply watcher active (Tools > GNue Importer > Toggle Auto Apply)")
except Exception as e:  # headless/commandlet: no slate — watcher not needed there
    unreal.log("[GNue] auto-apply watcher not started: %s" % e)
