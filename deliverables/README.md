# GN → UE bridge — client deliverables

Two plugins that move Geometry Nodes effects from Blender to Unreal Engine as
parametric PCG graphs. Regenerate these zips with `python tools/make_deliverables.py`.

## What's new in 0.7.0 (continuous proximity dynamics)

- **Live, per-frame proximity dynamics.** Effects driven by a controller now
  react continuously on the GPU instead of regenerating: as the controller
  approaches, instances shrink and settle; far from it they scale up, **spin,
  and shake** — each instance animating independently. Drag the controller,
  roll a physics ball through, or animate it in Sequencer and the whole field
  flows with it at full frame rate.
- Powered by a new world subsystem (in the GNuePCG C++ module) that streams the
  tagged controller's position each frame, plus a `M_GNueDyn_*` material the
  importer builds automatically (World Position Offset: proximity-modulated
  scale + spin + shake, driven by Time and per-instance identity). No user
  setup beyond tagging the controller actor.
- Regeneration now happens **only** when you change a Blender parameter — the
  moving controller never triggers a rebuild.
- Limits: the reaction is visual (collision volumes don't change); spin/shake
  amounts are material defaults for now (per-effect exposure is a follow-up).

## What's new in 0.6.0 (3D noise + never-vanish)

- **True 3D noise (GNue Noise 3D, C++).** UE's stock Spatial Noise samples
  only X/Y, so on vertical surfaces whole columns shared one value — coverage
  masks made straight top-to-bottom stripes. Noise now matches Blender's
  Noise Texture in three dimensions: organic patches on walls, pipes, rocks.
- **Effects never vanish without their controller.** Proximity-driven
  effects previously spawned *nothing* until you created the tagged actor;
  now they render at full size and collapse only once a controller exists.
- Live tracking works at any distance (previously the controller was only
  watched inside the volume's own bounds), and `RebuildBinaries.bat` ships
  in the plugin for non-launcher engine builds.
- The plugin README is now a complete step-by-step walkthrough (install →
  import → place → controllers → parameters → troubleshooting).

## What's new in 0.5.0 (effects carry their surface)

- **Scatter on the actual surface:** when a Blender effect scatters on a shaped
  mesh (a pipe, a rock, a tree trunk — anything that isn't just flat ground),
  the exporter now ships that mesh with the effect (`SM_GNue_Surface.fbx`) and
  the UE graph rebuilds it at the PCG volume: the surface spawns there and the
  instances grow off its faces, aligned to the face normals like Blender's
  Distribute on Faces. Flat ground hosts keep the old behaviour (your UE
  level's own floor is the terrain).
- **Tag any actor `GNueSurface`** and the effect also samples that actor's
  mesh, wherever it stands — move the actor, regenerate, the scatter follows.
- Density lowers to Poisson-disk sampling on the mesh (statistical, like all
  our randomness). Needs the PCG Geometry Script Interop plugin, which the
  GNue Importer plugin now declares — UE enables it automatically.

## What's new in 0.4.0 (fidelity fixes)

- **Smooth proximity scaling.** Instances now shrink continuously as the
  controller approaches, instead of popping out of existence. This needed a
  custom PCG node (**GNue Scale By Attribute**, in the plugin's GNuePCG
  module): UE 5.8's stock *Attribute Maths Op* — and in fact every
  `Attribute * Op` / `Make * Attribute` node — silently produces no output
  data, so per-point scale math is impossible with the shipped nodes.
- **Per-instance size variety restored.** Scale expressions like
  `random(0.4, 1.6) * Greeble Size` were collapsing to a flat 1.0 because only
  a *bare* random leaf was recognised; products are now evaluated as a
  min/max range, so scattered details vary again.
- **Noise features are the right size.** PCG Spatial Noise samples world
  centimetres scaled by 1e-4, so its default feature size is ~100 m — noise
  read as a constant and every instance came out the same height. Blender's
  Noise Texture *Scale* is now mapped onto the node (feature size 1/Scale
  metres), and the noise **multiplies** the random base scale rather than
  replacing it.
- If the GNuePCG module isn't compiled for your engine build, the importer
  says so in its report and falls back to stepped scale bands — the effect
  still imports, it just scales in steps.

## What's new in 0.3.0 (V1.x feature pack #1)

- **Actor binding (Object Info):** effects driven by a Blender object (e.g. a
  proximity controller) work live in UE — tag any UE actor with the Blender
  object's name (Details > Actor > Tags) and the effect tracks it as it moves
  (regenerate, or just move the actor — PCG tracking picks it up).
  Proximity *scale falloff* is exact and smooth via the GNuePCG node (see
  0.4.0 above).
- **Noise gradients (Noise Texture):** coverage masks and noise-driven scaling
  lower to PCG Spatial Noise (statistical equivalence — patterns differ,
  distributions match), at Blender's feature size.
- **Greebles (Realize Instances + scatter):** details scattered on instance
  surfaces lower to a per-instance sample cloud composed via Copy Points —
  they inherit each instance's transform, so proximity collapse carries them.
- **Trim Curve:** exact arc-length trims in the numeric kernel.
- **Accumulate Field:** prefix sums — including seeded random walks (the
  SpineTree spine pattern) — evaluated numerically; a new Seed regenerates
  the walk.
- Odd instance origins now bake correctly (no more half-sunk instances), and
  scatter can also target any actor tagged `GNueSurface` (experimental)
  besides the default ground ray-cast.

## blender_addon/gnue_exporter-0.7.0.zip

Blender 4.2+ **extension** (tested on 5.2).

**Install:** Blender > Edit > Preferences > Extensions (or Add-ons) >
"Install from Disk…" > pick the zip.

**Use:** select the object with your Geometry Nodes modifier > N-panel >
**GN to UE** tab > pick the node group and an export folder > **Validate**
(checks the graph against the supported V1 node set, names anything that
doesn't translate) > **Export**. The folder receives `effect.gnue.json`,
`meshes/*.fbx`, `manifest.json`, and `export_report.txt`.

## unreal_plugin/GNueImporter-0.7.0.zip

UE 5.8 plugin with two small C++ modules: **GNueParams** (declares Blender
parameters on imported graphs) and **GNuePCG** (the *GNue Scale By Attribute*
and *GNue Noise 3D* nodes, plus the world subsystem that drives the live
proximity dynamics — all wired up automatically, no manual setup).
Prebuilt Win64 editor binaries for UE 5.8 are included;
other engine versions rebuild from the bundled Source/ (right-click the
.uproject > Generate project files > build). Depends on the PCG and Python
Editor Script plugins (declared in the .uplugin).

**Install:** unzip into `<YourProject>/Plugins/` (creating
`Plugins/GNueImporter/`) and restart the editor. Prebuilt binaries target
launcher UE 5.8; on any other engine build run the bundled
`RebuildBinaries.bat` once (needs Visual Studio 2022 C++), or the editor will
refuse to open the project with a "module could not be loaded" dialog.

**Use (plug-and-play):** copy any exported effect folder into
`<YourProject>/GNueDrops/` — it imports automatically at startup, or via
**Tools > GNue Importer > Scan GNueDrops**. Then drop a **PCG Volume** in your
level over some ground and assign `/Game/GNueImport/<Effect>/PCG_<Effect>`.
The effect builds relative to that volume, so move the volume to move the
effect. **Keep the volume at scale 1** for exactly the size it was in Blender —
the volume's scale multiplies effects made of explicit geometry (bridges,
circles, spirals). For scattered effects the volume's size is the scatter
area instead, so scale those to taste.
Menu also offers: Import Effect Folder… (browse anywhere), Reimport All Drops
(after re-exporting from Blender; safe — rebuilds in place, placed volumes
keep working), Open GNueDrops Folder.

## Parameters in UE

Imported effects expose their Blender parameters on the PCG volume's Details
panel (Graph Parameters section — declared by the GNueParams module). **Just
edit a value** — about a second after it settles the effect rebuilds and
regenerates automatically. Each edited volume gets its own graph copy
(`/Game/GNueImport/<Effect>/Instances/<VolumeName>/`), so volumes diverge
freely while the base graph keeps the Blender defaults. Menu extras:
**Apply Volume Parameters** (manual apply) and **Toggle Auto Apply**.
Blender reimports refresh every copy with its own saved values — nothing you
edited in UE is lost when iterating.

## Known limits

- The 53-node V1 core set plus the V1.x pack above translates (see
  `atlas/v1_core_nodes.md`); anything else is refused with a per-node
  report — never guessed. Descriptors carry a `requires` list so older
  importers refuse V1.x exports gracefully.
- Random placement is statistically equivalent to Blender, not identical.
- Parameter application is settle-then-rebuild (~1s after you stop editing),
  not per-frame slider scrubbing.
- Scatter on a *flat* Blender ground plane samples the UE level's own ground
  (any collidable surface under the volume) — flat terrain is intentionally
  not exported. Shaped surfaces (pipes, rocks…) ship with the effect and
  rebuild at the volume (0.5.0).
- The folder picker dialog is Windows-only; the GNueDrops flow works everywhere.
