# Why it looks clean in Blender and dirty in Unreal

## Lumen (Unreal) vs Cycles (Blender) — the shading-error breakdown

You exported a field of tall, thin monoliths. In **Blender Cycles** they render clean;
in **Unreal with Lumen** the vertical faces pick up a grey splotchy grime, the columns
darken in patches, and some faces go hard-dark with no fill. Nothing is broken in the
export — you're seeing the difference between an **offline path tracer** and a
**real-time approximate GI system**, and this particular geometry stresses exactly the
approximations Lumen makes.

---

## 1. Two fundamentally different machines

### Blender Cycles — an offline path tracer (ground truth)

- **Monte Carlo path tracing.** For each pixel it fires rays that bounce through the
  scene, sampling the real rendering equation. Global illumination, soft shadows,
  ambient occlusion, and color bleed are not separate features — they *fall out* of
  tracing enough light paths.
- **It traces the actual triangles.** Cycles walks a BVH over your real mesh. A wall
  1 mm thin is represented exactly as 1 mm thin. There is no simplified stand-in for
  your geometry.
- **It has all the time in the world.** A frame can take seconds to minutes. It keeps
  accumulating samples until the noise converges, then an AI denoiser
  (OpenImageDenoise / OptiX) cleans the last of it.
- **The only artifact is noise, and noise → 0 with more samples.** Given enough
  samples, Cycles *is* the correct answer.

### Unreal Lumen — real-time dynamic GI (an approximation on a 16 ms budget)

Lumen has to produce global illumination in **~8–16 milliseconds per frame**, every
frame, while things move. It cannot trace your millions of real triangles that fast, so
it builds **cheaper stand-ins for both the geometry and the lighting** and reuses them:

- **Simplified geometry — Mesh Distance Fields (software ray tracing, the default).**
  Each mesh is pre-baked into a **signed distance field** (a coarse volume that stores
  "how far to the nearest surface"). Lumen traces *that*, not your triangles. SDFs have
  limited resolution, and **thin geometry is where they fail** — a narrow column may be
  barely captured or captured as a fuzzy blob, so light leaks through it and
  self-shadowing goes wrong.
- **Cached lighting — the Surface Cache.** Lumen captures each mesh's material from up
  to 6 axis-aligned directions onto low-res "cards," computes lighting on those cards,
  and **reuses the cached result** for indirect light. When a mesh is thin, tall, or
  packed against neighbours, the cards **don't cover the surface well** → gaps that read
  as **blotchy grey patches and dark streaks** exactly like the ones on your columns.
- **Undersampled + denoised — the Final Gather.** Lumen shoots only a *few* indirect
  rays per pixel and fills the rest with spatial + temporal filtering (screen probes).
  That's real-time-affordable but leaves **low-frequency splotches, temporal shimmer,
  and lag/ghosting** in motion — the "dirty" grain over the flat faces.
- **Screen traces** add fine contact detail from what's on screen, and fall back to the
  cruder Lumen Scene off-screen — so occlusion can change at screen edges.

There is a **Hardware Ray Tracing** mode that traces the real triangles (via RTX/DXR)
and largely fixes the thin-geometry leaking — but even it still evaluates diffuse GI
through the Surface Cache by default. It's better, not free.

---

## 2. Side by side

| | **Cycles (Blender)** | **Lumen (Unreal)** |
|---|---|---|
| Goal | Correct image | 60 fps image |
| Time budget | Seconds–minutes/frame | ~8–16 ms/frame |
| Geometry it traces | The real triangles (BVH) | Distance-field / card approximations (SW RT) |
| How GI is computed | Trace light paths to convergence | A few rays + cached cards + temporal denoise |
| Lighting reuse | None — recomputed exactly | Surface Cache reused across frames |
| Only artifact | Noise → 0 with samples | Leaking, splotches, dark cards, ghosting |
| Thin geometry | Exact | **Worst case** — poorly represented |
| Result on your columns | Clean | Grimy, patchy, dark-facing |

**The one-sentence version:** Cycles spends minutes tracing your *actual* thin columns
to a converged answer; Lumen has milliseconds, so it traces a *blurry distance-field
copy* of them and reuses *low-res cached lighting* — and thin, tall, crowded columns are
precisely the shape that copy and that cache handle worst.

---

## 3. Why *these* monoliths specifically

Your effect is the pathological case for real-time GI on three counts at once:

1. **Thin + tall.** Mesh Distance Fields under-resolve thin walls → light leaks and
   self-shadowing errors down the columns (the vertical patchy darkening).
2. **Dense and overlapping.** Packed columns make the Surface Cache cards fight for
   coverage and confuse occlusion → the grey blotches and missing indirect fill on
   inward-facing sides.
3. **Big flat matte faces.** Flat diffuse surfaces show the Final Gather's low-frequency
   splotch and temporal noise the most — there's no texture detail to hide it behind.

In Cycles none of these matter, because it never approximates the geometry or caches the
lighting — it just traces the real thing until it's clean.

> **Note — some of the speckle is *your material*, not Lumen.** The GNue effects use a
> 3D-noise coverage material (`M_GNueDyn_*` / the noise mask). Part of the stippled look
> on some columns is that intended stylization, not a lighting bug. Quick way to tell
> them apart below.

---

## 4. Diagnose it in 60 seconds

- **See where the Surface Cache is failing:** viewport → **Show → Visualize → Lumen
  Scene** (and **Surface Cache**). Black/pink areas = no coverage = where your dark
  blotches come from.
- **Separate material grain from Lumen dirt:** console `r.DynamicGlobalIlluminationMethod 0`
  (Lumen off). The splotchy grey GI grime **disappears**; anything stippled that
  *remains* is the noise material doing its job. Re-enable with `2`.
- **Confirm it's the approximation, not the asset:** switch to Hardware Ray Tracing
  (below). If the leaking/patches clear up, it was the distance-field stand-in.

---

## 5. How to make Unreal look closer to Blender

Roughly in order of impact for this scene:

| Fix | Where | What it does |
|---|---|---|
| **Enable Hardware Ray Tracing** | Project Settings → Rendering → Lumen → *Use Hardware Ray Tracing* (needs *Support Hardware Ray Tracing* on + an RTX/DXR GPU) | Traces the real triangles → biggest fix for thin-column leaking |
| **Raise Distance Field resolution** (if staying on software RT) | Static Mesh editor → Build Settings → *Distance Field Resolution Scale* = 2–4 | Sharper SDF stand-in → less leaking/self-shadow error |
| **Raise Lumen quality** | Post Process Volume (Infinite Extent) → *Final Gather Quality* 2–4, *Lumen Scene Detail*, *Max Trace Distance* | More rays / better cache → fewer splotches |
| **Project scalability to Epic/Cinematic** | Settings → Engine Scalability → Global Illumination = Epic | Bumps the Lumen cvars in one click |
| **Bake it instead (closest to Cycles)** | Set lights/meshes to Static, use **GPU Lightmass** | Offline-baked ground-truth GI in lightmaps — Cycles-like quality, but static (no live proximity dynamics) |
| **Or turn GI off for a clean matte look** | `r.DynamicGlobalIlluminationMethod 0` + a Directional + Sky light + SSAO | Removes the approximation entirely; flat, predictable shading |

**Trade-off to know:** the *reason* you're on Lumen is the **live proximity dynamics** —
the fields react to a moving controller every frame, which needs *dynamic* GI. Baked
lighting (GPU Lightmass) gets you Cycles-clean shading but freezes the lighting, so
moving effects won't update their bounce light. For the showcase, **Hardware Ray Tracing
+ Final Gather Quality 2–4** is usually the best "clean *and* still dynamic" middle
ground.

---

## 6. Takeaway

Nothing is wrong with the export or the meshes. Blender looks right because Cycles is a
converged offline path tracer over the real geometry. Unreal looks dirty because Lumen
is a real-time approximation — distance-field geometry, cached cards, undersampled
gather — and your thin, tall, crowded columns are the exact geometry those
approximations handle worst. Push Lumen toward Hardware Ray Tracing and higher gather
quality to close most of the gap, or bake the lighting if you can trade away the live
dynamics.
