"""gnue_paths — resolve the machine-specific locations the GNue dev loop needs.

Every repo-side script imports this instead of hardcoding paths. Each value is
resolved in a fixed order and fails with an actionable message:

    1. explicit argument        (function parameter / CLI)
    2. environment variable     GNUE_UE_PROJECT, GNUE_ENGINE, GNUE_BLENDER
    3. gnue.config.json         (repo root, gitignored, per-machine)
    4. auto-discovery           (registry / conventional install dirs)
    5. PathError                "set GNUE_UE_PROJECT or create gnue.config.json"

See PORTABILITY.md. Dependency-free; Windows registry access is optional.

    python tools/gnue_paths.py              # print everything it can resolve
    python tools/gnue_paths.py engine_root  # print one value (for shell scripts)
"""

import glob
import json
import os
import re
import sys

ENV = {"ue_project": "GNUE_UE_PROJECT", "engine": "GNUE_ENGINE", "blender": "GNUE_BLENDER"}
CONFIG_NAME = "gnue.config.json"
PLUGIN_NAME = "GNueImporter"


class PathError(RuntimeError):
    """A location could not be resolved; the message says how to fix it."""


def _norm(p):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(str(p))))


# ---------------------------------------------------------------- repo

def repo_root():
    """This repo — always knowable from __file__."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path():
    return os.path.join(repo_root(), CONFIG_NAME)


_config_cache = None


def config():
    """gnue.config.json as a dict ({} if absent). Keys starting with '_' are notes."""
    global _config_cache
    if _config_cache is None:
        _config_cache = {}
        p = config_path()
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            _config_cache = {k: v for k, v in raw.items() if not k.startswith("_")}
    return _config_cache


def _setting(key, explicit=None):
    """explicit -> env -> config -> None."""
    if explicit:
        return _norm(explicit)
    v = os.environ.get(ENV[key])
    if v:
        return _norm(v)
    v = config().get(key)
    if v:
        return _norm(v)
    return None


def _hint(key):
    # plain ASCII: these messages surface in cmd/PowerShell consoles too
    return ("set %s or add \"%s\" to %s - see PORTABILITY.md"
            % (ENV[key], key, CONFIG_NAME))


# ---------------------------------------------------------------- UE project

def _project_search_dirs():
    home = os.path.expanduser("~")
    return [os.path.join(home, "Documents", "Unreal Projects"),
            os.path.join(home, "OneDrive", "Documents", "Unreal Projects")]


def _looks_like_gnue_project(d):
    if not glob.glob(os.path.join(d, "*.uproject")):
        return False
    return (os.path.isdir(os.path.join(d, "Plugins", PLUGIN_NAME))
            or os.path.isdir(os.path.join(d, "GNueDrops")))


def ue_project(explicit=None):
    """Directory containing the .uproject. Auto-discovery: the one project under
    Documents/Unreal Projects that already has the GNue plugin or a GNueDrops/."""
    p = _setting("ue_project", explicit)
    if p:
        if not glob.glob(os.path.join(p, "*.uproject")):
            raise PathError("UE project dir has no .uproject: %s (%s)" % (p, _hint("ue_project")))
        return p
    found = []
    for base in _project_search_dirs():
        if not os.path.isdir(base):
            continue
        for d in sorted(glob.glob(os.path.join(base, "*"))):
            if os.path.isdir(d) and _looks_like_gnue_project(d):
                found.append(d)
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise PathError("several UE projects carry GNue (%s); %s"
                        % (", ".join(found), _hint("ue_project")))
    raise PathError("no UE project found under %s; %s"
                    % (" or ".join(_project_search_dirs()), _hint("ue_project")))


def uproject(project=None):
    """Full path to the .uproject file."""
    d = ue_project(project)
    hits = glob.glob(os.path.join(d, "*.uproject"))
    if len(hits) != 1:
        raise PathError("expected exactly one .uproject in %s, found %d" % (d, len(hits)))
    return hits[0]


def project_name(project=None):
    return os.path.splitext(os.path.basename(uproject(project)))[0]


def editor_target(project=None):
    """UBT target for the editor build — derived, never hardcoded."""
    return project_name(project) + "Editor"


def engine_association(project=None):
    """EngineAssociation from the .uproject: '5.8' for launcher builds, a GUID
    for source builds. Empty string if unset."""
    with open(uproject(project), "r", encoding="utf-8") as f:
        return str(json.load(f).get("EngineAssociation", ""))


def plugin_dir(project=None):
    return os.path.join(ue_project(project), "Plugins", PLUGIN_NAME)


def drops_dir(project=None):
    return os.path.join(ue_project(project), "GNueDrops")


# ---------------------------------------------------------------- engine

def _reg_value(root_name, subkey, value=None):
    """Read one registry value (or the default value). None if unavailable."""
    try:
        import winreg
    except ImportError:
        return None
    root = getattr(winreg, root_name)
    for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0)):
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view) as k:
                v, _ = winreg.QueryValueEx(k, value)
                return str(v)
        except OSError:
            continue
    return None


def _reg_values(root_name, subkey):
    """All (name, data) pairs under a key. [] if unavailable."""
    try:
        import winreg
    except ImportError:
        return []
    root = getattr(winreg, root_name)
    out = []
    try:
        with winreg.OpenKey(root, subkey) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                    out.append((name, str(data)))
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return out


def _is_engine_root(d):
    return bool(d) and os.path.isdir(os.path.join(d, "Engine", "Binaries"))


def _discover_engine(assoc):
    """Candidates in order; first existing engine root wins."""
    cands = []
    if assoc:
        # a) exact-version key (launcher builds normally register here)
        cands.append(_reg_value("HKEY_LOCAL_MACHINE",
                                r"SOFTWARE\EpicGames\Unreal Engine\%s" % assoc,
                                "InstalledDirectory"))
        # b) launcher install root + UE_<ver> (5.8 was NOT registered under (a)
        #    on the original machine, but INSTALLDIR was)
        base = _reg_value("HKEY_LOCAL_MACHINE", r"SOFTWARE\EpicGames\Unreal Engine", "INSTALLDIR")
        if base:
            cands.append(os.path.join(base, "UE_" + assoc))
        # c) source builds: HKCU ...\Builds holds <GUID> = <path>
        for name, data in _reg_values("HKEY_CURRENT_USER", r"Software\Epic Games\Unreal Engine\Builds"):
            if name.strip("{}").lower() == assoc.strip("{}").lower():
                cands.append(data)
        # d) conventional launcher location
        cands.append(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                  "Epic Games", "UE_" + assoc))
    for c in cands:
        if _is_engine_root(c):
            return _norm(c)
    return None


def engine_root(explicit=None, project=None):
    """UE install directory (the folder containing Engine/)."""
    p = _setting("engine", explicit)
    if p:
        if not _is_engine_root(p):
            raise PathError("not an engine root (no Engine/Binaries): %s (%s)" % (p, _hint("engine")))
        return p
    assoc = engine_association(project)
    found = _discover_engine(assoc)
    if found:
        return found
    raise PathError("engine for EngineAssociation %r not found (registry + Program Files checked); %s"
                    % (assoc, _hint("engine")))


def unreal_cmd(engine=None, project=None):
    return os.path.join(engine_root(engine, project), "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")


def unreal_editor(engine=None, project=None):
    return os.path.join(engine_root(engine, project), "Engine", "Binaries", "Win64", "UnrealEditor.exe")


# ---------------------------------------------------------------- blender

def _version_tuple(name):
    m = re.search(r"(\d+)\.(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def blender_exe(explicit=None):
    """blender.exe — accepts an install dir or the exe itself. Auto-discovery
    picks the newest 'Blender Foundation/Blender X.Y'."""
    p = _setting("blender", explicit)
    if p:
        exe = p if p.lower().endswith(".exe") else os.path.join(p, "blender.exe")
        if not os.path.isfile(exe):
            raise PathError("blender.exe not found at %s (%s)" % (exe, _hint("blender")))
        return exe
    base = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Blender Foundation")
    dirs = sorted(glob.glob(os.path.join(base, "Blender *")), key=_version_tuple)
    for d in reversed(dirs):
        exe = os.path.join(d, "blender.exe")
        if os.path.isfile(exe):
            return exe
    raise PathError("no Blender install under %s; %s" % (base, _hint("blender")))


# ---------------------------------------------------------------- version

def version():
    """Single source of truth: version = "x.y.z" in gnue_exporter/blender_manifest.toml."""
    p = os.path.join(repo_root(), "gnue_exporter", "blender_manifest.toml")
    with open(p, "rb") as f:
        data = f.read()
    try:
        import tomllib
        return str(tomllib.loads(data.decode("utf-8"))["version"])
    except Exception:
        m = re.search(rb'^version\s*=\s*"([^"]+)"', data, re.M)
        if not m:
            raise PathError("no version in %s" % p)
        return m.group(1).decode()


# ---------------------------------------------------------------- CLI

_ORDER = ["repo_root", "version", "ue_project", "uproject", "project_name", "editor_target",
          "engine_association", "engine_root", "unreal_cmd", "plugin_dir", "drops_dir", "blender_exe"]


def describe():
    """{name: value-or-'ERROR: ...'} for everything above."""
    out = {}
    for name in _ORDER:
        try:
            out[name] = globals()[name]()
        except Exception as e:  # noqa: BLE001 — report, don't abort
            out[name] = "ERROR: %s" % e
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in _ORDER:
            sys.exit("unknown value %r; one of: %s" % (name, ", ".join(_ORDER)))
        try:
            print(globals()[name]())
        except PathError as e:
            sys.exit("gnue_paths: %s" % e)
    else:
        d = describe()
        w = max(len(k) for k in d)
        for k in _ORDER:
            print("%-*s  %s" % (w, k, d[k]))
        cfg = config_path()
        print("%-*s  %s" % (w, "config", cfg if os.path.isfile(cfg) else "(none - auto-discovery only)"))
        sys.exit(1 if any(str(d[k]).startswith("ERROR") for k in ("ue_project", "engine_root")) else 0)
