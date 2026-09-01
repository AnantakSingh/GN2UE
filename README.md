# GNtoUE — Blender Geometry Nodes → Unreal Engine bridge

Moves Geometry Nodes effects from Blender to UE 5.8 as **parametric PCG
graphs**: export a node group from Blender's N-panel, drop the folder into a
UE project, edit the Blender parameters on the volume's Details panel and
watch the effect rebuild. Deterministic (no AI at export time), conservative
(unsupported nodes are refused by name, never guessed), statistically
equivalent (UE's RNG, Blender's distributions).

## Start here

| I want to… | Go to |
|---|---|
| **Install the plugins** (end-user flow) | [`deliverables/README.md`](deliverables/README.md) — zipped Blender extension + UE plugin with install/usage steps |
| Understand the Blender exporter | [`gnue_exporter/README.md`](gnue_exporter/README.md) |
| Understand the UE importer / plugin | [`ue_importer/README.md`](ue_importer/README.md) and `GNtoUE/Plugins/GNueImporter/README.md` (in the UE project) |
| See which Blender nodes translate | [`atlas/v1_core_nodes.md`](atlas/v1_core_nodes.md) (the 53-node V1 set) and the full 412-node Translation Atlas (`atlas/gn-ue-atlas.html`, published artifact) |
| See it working | [`media/`](media/) — Blender + in-UE screenshots of the RopeBridge effect |

## The pipeline

```
Blender N-panel "GN to UE"        UE Tools > GNue Importer
  Validate / Export                 GNueDrops auto-scan / menu import
        │                                   │
        ▼                                   ▼
  export folder ──copy──► <UEProject>/GNueDrops/<effect>/
    effect.gnue.json  (descriptor v2: blocks + expression trees + params)
    meshes/*.fbx      (baked, deduped instance meshes)
    manifest.json / export_report.txt
                                            │
                                            ▼
                        /Game/GNueImport/<Effect>/PCG_<Effect>
                        assign to a PCG Volume over ground
                        (explicit-geometry effects build relative to the
                         volume — keep those volumes at scale 1; for scatter
                         effects the volume is the scatter area)
                        edit Graph Parameters → auto-rebuilds (~1s)
                        edited volumes get their own graph copies
```

## Repo map

| Path | What |
|---|---|
| `gnue_exporter/` | Blender extension (deterministic transpiler; `core.py` is bpy-free) |
| `ue_importer/` | UE-side importers: `import_gnue.py` (v1 SpineTree family), `import_gnue2.py` (v2 generic — source of truth for the plugin) |
| `ue_plugin_src/` | C++ modules: **GNueParams** (declares Blender parameters on imported graphs) and **GNuePCG** (`GNue Scale By Attribute` — per-point scale math, which UE 5.8's own `Attribute Maths Op` cannot do: it silently outputs nothing) |
| `tools/` | `sync_ue_plugin.py` (assembles the UE plugin from repo sources — run after edits), `make_deliverables.py` (packages the zips), headless test scripts (`test_*_headless.py`) |
| `deliverables/` | Shippable zips + user-facing README |
| `atlas/` | Node translation atlas (all 412 GN nodes) + V1 core list |
| `export/` | Golden export fixtures (SpineTree v1 package, RopeBridge v2 folder) |
| `build_v1_bridge.py` | Builds the RopeBridge_V1 demo effect in Blender (V1-whitelist-validated) |
| `schema/` | Descriptor v1 JSON schema (v2 is documented in `gnue_exporter/core.py`) |
| `media/` | Verification screenshots |

## Developer loop

1. Edit `ue_importer/import_gnue2.py`, `tools/plugin_init_unreal.py`, or
   `ue_plugin_src/` → run `python tools/sync_ue_plugin.py`.
2. C++ changed? `powershell -ExecutionPolicy Bypass -File tools/build_ue_plugin.ps1`
   (editor must be closed — Live Coding holds the mutex; the script refuses
   otherwise). It also handles declaring GNuePCG in the .uplugin: UE 5.8 has no
   "optional module" flag, so a declared module without binaries stops the whole
   plugin — `sync_ue_plugin.py` only declares it once its .dll exists.
3. Test headless: `UnrealEditor-Cmd.exe <uproject> -run=pythonscript -script=tools\test_*_headless.py`
4. Package: `python tools/make_deliverables.py`.

Blender side iterates via the N-panel or `gnue_exporter/export_cli.py` through
the blender-mcp addon socket (127.0.0.1:9876).
