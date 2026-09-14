# GNue — Onboarding

Welcome. This doc gets you from zero to productively changing the project. Read
it top to bottom once; it's ~20 minutes and will save you days.

---

## 1. What this project is

**GNue** is a bridge that moves **Blender Geometry Nodes effects into Unreal
Engine 5.8** as native, editable, real-time assets. A technical artist designs
an effect in Blender; GNue translates it into an Unreal **PCG graph** (plus a
material and a bit of C++) that runs in the engine — no Blender at runtime,
ships in a packaged game, and reacts live to gameplay.

It is **two plugins**:

1. **Blender exporter** (`gnue_exporter/`) — an N-panel add-on. You pick a
   Geometry Nodes group, it validates that every node is supported, and writes
   a portable **descriptor folder** (`effect.gnue.json` + baked `meshes/*.fbx`).
2. **Unreal importer** (`ue_importer/` + `ue_plugin_src/`) — drop the folder
   into `GNueDrops/` and it builds a PCG graph that reproduces the effect.

**Core philosophy:** it's a **deterministic compiler**, not an AI guess. A
fixed set of ~57 Blender nodes translate; anything else is **refused by name**,
never approximated. Randomness is *statistically* equivalent to Blender (same
distributions, different exact placement), never identical.

---

## 2. The mental model (read this — it's the whole thing)

An effect flows through these stages:

```
Blender GN graph
  │  gnue_exporter/frontend_bpy.py  (reads the live bpy node tree)
  ▼
IR  →  validate (whitelist)  →  lower to "blocks" + expression trees
  │  gnue_exporter/core.py   (bpy-free: this is the real compiler)
  ▼
effect.gnue.json  (descriptor v2.1: params + ~22 block types + baked meshes)
  │  copy folder into  <UEProject>/GNueDrops/
  ▼
ue_importer/import_gnue2.py  (THE importer — source of truth for the plugin)
  │  a NUMERIC KERNEL evaluates deterministic blocks into explicit points;
  │  random / proximity / noise parts stay LIVE as PCG nodes or a material
  ▼
/Game/GNueImport/<Effect>/PCG_<Effect>   (a real Unreal PCG graph)
```

Three ideas do most of the work:

- **Numeric kernel** (in `import_gnue2.py`): most nodes are *evaluated at import
  time* — the kernel computes where every instance ends up and bakes explicit
  Create Points. Curves, duplication, set-position, trig layouts, accumulate
  (prefix sums / random walks), trim — all kernel.
- **Live PCG** for the parts that must stay dynamic: scatter → Surface/Mesh
  Sampler; randomness → Transform Points ranges; per-point scale → our custom
  `GNue Scale By Attribute` node; 3D noise → our `GNue Noise 3D` node.
- **The dynamics layer** (newest, v0.7): proximity reactions run **per-frame on
  the GPU**, not by regenerating. The importer builds an `M_GNueDyn_*` material
  (World Position Offset: proximity-modulated scale + spin + shake) and a C++
  **world subsystem** streams the tagged controller's position into a Material
  Parameter Collection every frame. See §6.

---

## 3. Repo layout (where things live)

| Path | What it is |
|---|---|
| `gnue_exporter/core.py` | **The compiler.** bpy-free: whitelist validation, expression lowering, block lowering, numeric evaluator, descriptor emit. Start here to understand translation. |
| `gnue_exporter/frontend_bpy.py` | Blender-side: reads the live node tree into the IR, bakes FBX meshes, bakes shaped scatter surfaces. |
| `gnue_exporter/__init__.py`, `blender_manifest.toml` | The Blender add-on (N-panel UI + extension manifest). |
| `gnue_exporter/export_cli.py` | Headless export entry (used via the Blender socket in dev). |
| `ue_importer/import_gnue2.py` | **THE importer.** Numeric kernel + PCG emission + material builder. This is the source of truth; the plugin's Python is generated from it. ~2000 lines — the heart of the UE side. |
| `ue_importer/import_gnue.py` | The old v1 (SpineTree family) importer + shared helpers (`add_node`, `connect`, `import_fbx`, `set_spawner_mesh`). v2 reuses its helpers. |
| `ue_plugin_src/Source/GNueParams/` | C++ module: declares Blender parameters on the imported graph (Details-panel editing). |
| `ue_plugin_src/Source/GNuePCG/` | C++ module: `GNueScaleByAttribute` (per-point scale math), `GNueNoise3D` (3D Perlin), `GNueDynamicsSubsystem` (per-frame proximity controller streaming). |
| `ue_plugin_src/README.md` | The **user-facing** plugin manual (install → import → place → controllers → parameters → troubleshooting). Ships inside the zip. |
| `tools/sync_ue_plugin.py` | **Assembles the UE plugin** from repo sources into the live project's `Plugins/GNueImporter/`. Run after editing the importer or C++. |
| `tools/build_ue_plugin.ps1` | Builds the C++ modules (editor must be closed). |
| `tools/make_deliverables.py` | Packages the shippable zips into `deliverables/`. |
| `tools/plugin_init_unreal.py` | The plugin's `init_unreal.py` (menus, GNueDrops auto-scan, auto-apply watcher). |
| `tools/test_*.py` | Headless UE test scripts (run via `UnrealEditor-Cmd -run=pythonscript`). |
| `build_*.py` | Scripts that build the demo/test effects **in Blender** (RopeBridge, StoneCircle, DominoSpiral, CubeField, ProxRing, ProxGarden…). |
| `atlas/` | The 412-node Blender→UE **translation atlas** (`gn-ue-atlas.html`) + the 53-node V1 core list. |
| `deliverables/` | Shippable zips + `README.md` (install guide) + `SUPPORTED_NODES.md` (the 63 supported nodes). |
| `media/` | Verification screenshots. |
| `schema/` | Descriptor v1 JSON schema (v2 is documented in `core.py`). |

**Two projects, not one.** This repo (**GN2UE**, wherever you cloned it) is the
**source**. The live Unreal project is separate — yours lives wherever you
created it (typically `Documents\Unreal Projects\<Name>\`), and every script
finds it through `tools/gnue_paths.py` (see [PORTABILITY.md](PORTABILITY.md)).
`sync_ue_plugin.py` copies the built plugin from the repo into that project's
`Plugins/`.

---

## 4. Environment setup for a new machine

**You never edit paths in source.** Every build/test script resolves the repo,
your UE project, the engine and Blender through `tools/gnue_paths.py`:
`GNUE_*` env vars → `gnue.config.json` (copy `gnue.config.example.json`) →
auto-discovery. Run `python tools/gnue_paths.py` to see what it finds on your
machine. Details and the fix-up plan: [PORTABILITY.md](PORTABILITY.md).

| Need | Version / notes |
|---|---|
| **Unreal Engine 5.8** | Epic Games Launcher install, any location — found from the registry / your project's `EngineAssociation`, or set `engine` in `gnue.config.json`. |
| **Blender 5.2** (or 4.2+) | Any location — the newest `Blender Foundation\Blender X.Y` is auto-discovered, or set `blender` in `gnue.config.json`. |
| **Visual Studio 2022** | With the **"Game development with C++"** workload — required to build the C++ modules. |
| **Python 3** | For the repo's build/test scripts (any recent 3.x). Unreal has its own bundled Python for in-editor scripts. |
| **blender-mcp add-on** (optional) | Enables driving Blender headlessly over a TCP socket (port 9876) for scripted effect building. Not required for normal use. |

**⚠️ Windows Smart App Control must be OFF.** It silently blocks freshly-built
DLLs and UBT's own build assemblies (error `0x800711C7`), which makes every C++
build fail with a confusing "module could not be loaded". Turn it off:
Settings → Privacy & Security → Windows Security → App & browser control →
Smart App Control → **Off** (note: this is a one-way switch). This cost a full
day to diagnose — don't repeat it.

---

## 5. The dev loop (how to actually make a change)

**Changing the importer (Python — most common):**
1. Edit `ue_importer/import_gnue2.py`.
2. `python tools/sync_ue_plugin.py` — pushes it into the live project's plugin.
3. Test headless (fast, no clicking):
   ```powershell
   $cmd = python tools/gnue_paths.py unreal_cmd; $up = python tools/gnue_paths.py uproject
   & $cmd $up -run=pythonscript -script="tools\test_cubefield_import.py"
   ```
   — or reimport an effect and inspect the graph.
4. Or test live: **Tools → GNue Importer → Reimport All Drops** in the editor.

**Changing the C++ (`ue_plugin_src/Source/…`):**
1. Edit the source.
2. **Close the Unreal editor** (Live Coding holds a mutex on the binaries).
3. `powershell -ExecutionPolicy Bypass -File tools/build_ue_plugin.ps1`
   (it syncs, declares GNuePCG only when its DLL exists, builds, re-syncs).
4. Reopen the editor and verify (check the Output Log for load errors).

**Changing the exporter / a Blender effect:**
- Effects are built by the `build_*.py` scripts. In dev they're run *inside a
  running Blender* over the socket; a new dev can also just open the `.blend`
  (`BlenderGeometryNodesBasic/SimpleGeoNodes.blend`) and paste/run the script
  in Blender's scripting tab.
- Export a group via the N-panel (Validate → Export) or `export_cli.py`.

**Packaging a release:**
`python tools/make_deliverables.py` → updates `deliverables/*/`. Bump the
version in `make_deliverables.py`, `sync_ue_plugin.py` (`VersionName`), and
`gnue_exporter/blender_manifest.toml` first.

**Golden rule:** the importer's Python and C++ live in the **repo**, and the
plugin is *generated*. Never edit files under the live project's
`Plugins/GNueImporter/` directly — `sync_ue_plugin.py` overwrites them.

---

## 6. How the dynamics layer works (v0.7, the newest piece)

For proximity-driven effects (a controller object makes instances react):

- **Blender side** only expresses "instance scale = f(distance to controller)"
  using Object Info → distance → Map Range → Scale Instances.
- **Importer** detects the actor-driven scale and, instead of baking it, builds
  `M_GNueDyn_*`: a material whose **World Position Offset** gives each instance
  a proximity-modulated **scale + spin + shake**, driven by Time and
  PerInstanceRandom (so each instance animates independently). One `agitation`
  value (0 near → 1 far) drives all three: near = small/still/calm, far =
  big/spinning/shaking.
- **C++ subsystem** (`GNueDynamicsSubsystem`) ticks every frame, finds the actor
  tagged with the controller's name, and writes its position into
  `MPC_GNueCtrl_<Tag>` (a Material Parameter Collection). The material reads it.
- Result: the effect reacts at full frame rate; regeneration happens **only**
  when you change a Blender *parameter*.

**Gotchas that already bit us (all fixed, but know them):**
- Material math must be in **Instance** space, not "Local" (which is the whole
  component); absolute world positions are LWC doubles that Distance/Transform
  reject — move offsets to world as *vectors*.
- Build the material **once per name** — a scale driving X/Y/Z from one
  controller decomposes per-component and will otherwise stack duplicate node
  chains and break the WPO (`_dyn_mat_cache` guards this).

---

## 7. Where the deeper knowledge lives

- **`deliverables/README.md`** — user install guide + a running changelog of
  what each version fixed (0.3 → 0.7). Great history of *why* things are the
  way they are.
- **`deliverables/SUPPORTED_NODES.md`** — the exact 57 supported nodes and how
  each maps to Unreal.
- **`ue_plugin_src/README.md`** — the end-user manual + troubleshooting.
- **`ue_importer/README.md`** — UE-side engine constraints & API notes (the
  things UE 5.8 does that surprised us — the dead `Attribute Maths Op`, World
  vs Instance space, etc.).
- **`gnue_exporter/README.md`** — exporter internals & known approximations.
- **`atlas/`** — the full 412-node translation map; what's *not* in V1 and why.
- **The changelog sections are the real design log.** When something looks
  weird, grep the changelog for the feature — the reason is usually there.

---

## 8. Current status & roadmap

**Status (v0.7.0):** All six demo effects translate and run. The dynamics
layer's C++ is built and verified (subsystem tracks controllers live; material
builds/compiles clean). Preparing an initial **open-source V0 release**.

**Known limits / good first tasks:**
- Nested node groups must be ungrouped before export (not yet inlined).
- **Repeat Zone / Simulation Zone** unsupported — needs loop unrolling in the
  exporter. This is the biggest missing node family and a real sub-project.
- Dynamics reaction is *visual* (collision volumes don't change).
- Spin/shake amounts are material defaults; per-effect exposure is a follow-up.
- The Niagara-vs-PCG question: very dense, purely-runtime effects may belong in
  Niagara instead of PCG — see the design discussion in the changelog.

**Before shipping V0 publicly:** fresh-install test on a clean machine, decide
source-only vs. prebuilt binaries (Smart App Control blocks unsigned builds on
some machines), and add a LICENSE.

---

## 9. Two footguns specific to this project

1. **Smart App Control** (see §4) — turn it off before any C++ build.
2. **Don't automate the *live* editor with tight polling loops.** There's an
   `mcp_tool.py` helper (in a scratch dir) that scripts the running editor over
   its MCP server; driving it in a loop while the editor is busy has repeatedly
   spawned thousands of hung processes and exhausted RAM. For scripting, prefer
   **headless commandlets** (`UnrealEditor-Cmd -run=pythonscript`, one process,
   safe) and drive the *live* editor by hand. (This mostly matters for
   AI/scripted workflows; a human clicking in the editor is fine.)
