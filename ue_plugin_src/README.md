# GNue Importer — UE plugin for Blender Geometry Nodes effect packs

Turns folders exported by the Blender **GN to UE Exporter** into parametric PCG
graphs: the effect rebuilds itself inside Unreal, with the Blender parameters
(sizes, densities, seeds…) editable on every placed copy. Ships two small C++
modules (**GNueParams** — parameter declaration, **GNuePCG** — per-point scale
math and true 3D noise) plus editor Python. Prebuilt Win64 binaries for
launcher UE 5.8 are included.

---

## 1. Requirements

- **Unreal Engine 5.8** (Epic Games Launcher install). Other engine builds
  work but need one extra step — see Troubleshooting #1.
- A UE **project** (Blueprint or C++, any template — a blank one is fine).
- Nothing else. The plugins GNue depends on (PCG, Python scripting, PCG
  Geometry Script Interop) are part of the engine and are **enabled
  automatically** when this plugin loads.

## 2. Install (once per project)

1. Close the Unreal editor if it's open.
2. Find your project folder — the one containing `YourProject.uproject`.
3. Create a folder called `Plugins` next to the `.uproject` file, if it
   doesn't already exist.
4. Unzip `GNueImporter-x.y.z.zip` **into** `Plugins`. You should end up with:
   ```
   YourProject/
     YourProject.uproject
     Plugins/
       GNueImporter/
         GNueImporter.uplugin   <- if you see this, the layout is right
         Binaries/  Content/  Source/  README.md  RebuildBinaries.bat
   ```
5. Start the editor. If it asks about enabling new plugins, say yes.

**Check it worked:** the menu bar now has **Tools > GNue Importer** (scroll to
the bottom of the Tools menu). The Output Log (Window > Output Log) shows
`[GNue] menu registered` and `[GNue] auto-apply watcher active`. A `GNueDrops`
folder now exists next to your `.uproject` — the plugin created it for you.

## 3. Bring an effect in

1. In Blender, export your effect with the GN to UE exporter — you get a
   folder containing `effect.gnue.json` and a `meshes/` subfolder.
2. Copy that **whole folder** into `YourProject/GNueDrops/`.
   (Menu shortcut: **Tools > GNue Importer > Open GNueDrops Folder**.)
3. Either restart the editor (drops import automatically at startup) or click
   **Tools > GNue Importer > Scan GNueDrops**.
4. The effect appears in the Content Browser under
   `/Game/GNueImport/<EffectName>/` — the graph is `PCG_<EffectName>`, its
   meshes are in `Meshes/`.

The Output Log prints one line per import, e.g.
`[GNue] Imported /Game/GNueImport/CubeField_FX/... | 2 spawn groups`.
A refused import names the unsupported Blender nodes — nothing is guessed.

## 4. Place it in your level

1. In the Content Browser, open `/Game/GNueImport/<EffectName>/`.
2. **Drag `PCG_<EffectName>` into the viewport.** UE creates a PCG Volume
   with the graph assigned and generates immediately.
3. Move the volume — the effect moves with it.

Rules of thumb:

- **Keep the volume's scale at 1,1,1** for effects made of built geometry
  (bridges, circles, spirals, surface effects). The volume's scale multiplies
  those effects.
- For pure ground-scatter effects (grass/rocks over terrain), the volume's
  size IS the scatter area — scale those as you like. They sample whatever
  collidable ground is under the volume.
- Effects that scattered on a shaped mesh in Blender (a pipe, a rock…) carry
  that mesh with them: it rebuilds at the volume automatically, instances
  growing off its faces exactly like Blender's Distribute on Faces.
- To regenerate manually: select the volume > Details > PCG > **Generate**
  (or Cleanup, then Generate).

## 5. Live proximity controllers

If the Blender effect was driven by a helper object (the import log says
`actor binding: tag '<Name>'`, e.g. `FieldController`):

1. Add **any actor** to the level — a plain Cube from the Quickly Add menu is
   perfect. Its mesh and size don't matter, only its position.
2. Select it. In **Details > Actor > Advanced > Tags**, click **+** and type
   the tag name **exactly** as the log printed it: `FieldController`.
3. Move it near the effect. Instances shrink smoothly around it **live,
   every frame** — drag it, animate it, or let physics move it.

No tagged actor in the level? The effect simply renders at full size — it
never disappears. Add the tag whenever you're ready.

**How the reaction stays smooth:** the proximity collapse doesn't regenerate
the effect — it runs on the GPU, every frame. The importer builds a
`M_GNueDyn_*` material whose World Position Offset shrinks each instance
toward its own pivot by its distance to the controller, and a small world
subsystem (GNuePCG module) streams the tagged actor's position into a
`MPC_GNueCtrl_<Tag>` parameter collection each frame — in the editor
viewport, in Play, and in packaged games. Drag the controller, roll a
physics ball through the field, animate it with Sequencer: the effect flows
with it at full frame rate. Regeneration only happens when you change a
Blender *parameter* (that's an editing operation, ~1 s).

Limits: the collapse is visual (collision volumes don't shrink), and greebles
shrink toward their own pivot rather than riding their host instance.

Bonus: tag any mesh actor **`GNueSurface`** and surface-scatter effects will
also grow across *that* actor's mesh, wherever it stands.

## 6. Edit the Blender parameters

Select the volume > Details > **Graph Parameters** (also under Graph Instance).
Every Blender group input is there: widths, counts, densities, Seed…

- **Just edit a value.** About a second after you stop typing/dragging, the
  effect rebuilds and regenerates on its own.
- Each edited volume gets its **own copy** of the graph (under
  `/Game/GNueImport/<Effect>/Instances/<VolumeName>/`), so two bridges can
  have different widths while the original keeps the Blender defaults.
- Manual alternatives: **Tools > GNue Importer > Apply Volume Parameters**
  (apply the selected volume now) and **Toggle Auto Apply** (watcher on/off).

## 7. Iterate from Blender

Re-export from Blender into the **same** drop folder, then click
**Tools > GNue Importer > Reimport All Drops**. Every graph rebuilds in place:
placed volumes keep working, and per-volume parameter copies are refreshed
with their own saved values. Nothing you tuned in UE is lost.

## 8. Troubleshooting

1. **The editor won't open the project: "Plugin 'GNueImporter' failed to load
   because module ... could not be loaded", then it closes.** (Sometimes with
   a Windows "Bad Image / error 0xc000012f" popup first.) The prebuilt
   binaries don't match your engine build — they target launcher UE 5.8
   (BuildId 55116800). Fix: run `Plugins/GNueImporter/RebuildBinaries.bat`
   once (needs Visual Studio 2022 with the "Game development with C++"
   workload), then start the editor again. No Visual Studio? Move the
   `Plugins/GNueImporter` folder out of the project to get back in, and use a
   zip built for your engine version.
2. **"Modules ... built with a different engine version. Rebuild now?"** after
   updating the engine — click Yes if you have Visual Studio, otherwise run
   `RebuildBinaries.bat` as above.
3. **The effect is giant or tiny** — the volume's scale multiplies built
   geometry. Set the volume back to scale 1,1,1.
4. **Nothing spawns** — check the Output Log for `[GNue]` lines; make sure
   the volume has the `/Game/GNueImport/...` graph assigned and press
   Generate once. Ground-scatter effects need collidable ground under the
   volume.
5. **Noise patterns look striped or banded** — you're running an old plugin
   build without the GNuePCG module; the importer then falls back to UE's
   2D-only noise. Rebuild/reinstall the plugin, then Reimport All Drops.
6. **The proximity effect doesn't follow the controller** — the tag on the
   actor must match the import log exactly (`FieldController`, no spaces);
   tags are case-sensitive in spirit — copy the name from the log.

## Files

- `Source/GNueParams/` — C++: declares Blender parameters on imported graphs.
- `Source/GNuePCG/` — C++: **GNue Scale By Attribute** (per-point scale math;
  UE 5.8's stock Attribute Maths Op silently outputs nothing) and
  **GNue Noise 3D** (true 3D Perlin FBM; the stock Spatial Noise node is
  2D-only and stripes on vertical surfaces). The importer wires both up
  automatically and degrades gracefully if the module isn't built.
- `Content/Python/` — importer, menus, GNueDrops scan, auto-apply watcher.
- `RebuildBinaries.bat` — rebuilds the C++ for a non-launcher engine build.

The Python files are **generated** from the GNtoUEresearch repo by
`tools/sync_ue_plugin.py`; C++ source is canonical in `ue_plugin_src/`.
Edit there, not here.

## Behaviour & limits

- Everything lands under `/Game/GNueImport/` — nothing else in your project
  is touched. Reimports rebuild graphs in place (volume references survive).
- Random placement is statistically equivalent to Blender, never identical;
  noise patterns match in character and scale, not pixel-for-pixel.
- Parameter application is settle-then-rebuild (~1s), not per-frame scrubbing.
- Mesh-surface scatter needs the PCG Geometry Script Interop engine plugin
  (declared as a dependency; UE enables it automatically).
