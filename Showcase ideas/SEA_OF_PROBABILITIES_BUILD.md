# Sea of Probabilities — native UE build plan (progress log)

Source spec: `UNREAL_PORT_PROMPT.md` (same folder). **Scope cut (agreed 2026-09-15):**
no phrase reveal, no entrance rain, no sound. Everything else carries over.

Reference: `C:\Projects\SeaOfProbabilities\index.html` (web version, wins on
any disagreement). Target project: the GNtoUE UE 5.8 project; new level
`L_SeaOfProbabilities`. Source of truth for everything built:
`showcase/sea_of_probabilities/` in this repo, synced into the UE project as
plugin `Plugins/SeaOfProbabilities`.

## Architecture (Step 0 decision)

| Prompt asks | We build | Why |
|---|---|---|
| Niagara GPU sim + Grid2D + HLSL stages | **ISM + per-instance custom data + C++ actor** | Niagara emitters/sim stages cannot be authored from Python or headless; they need the editor UI. Every in-scope behaviour is expressible as a C++ per-die loop (`theta/omega/yOffset/yVel/glow`) at 11.6k dice; the GPU only needs `theta, yOffset, glow, hue` per instance, which ISM custom data carries. |
| live-editor MCP | **headless `UnrealEditor-Cmd` Python + compiled C++** | MCP is disconnected and is the documented fork-bomb path. Same result. |
| waves in a sim stage | **material WPO** (HLSL simplex port in a Custom node) + the same port in C++ for picking | one function, two hosts, must agree to 1e-6 |
| vertex-colour pip mask | **two material slots** (body / pips) | survives FBX reliably; no vertex-colour import dependency |

Per-instance custom data layout: `[0]=theta [1]=yOffset [2]=glow [3]=hue`.
Coordinate mapping per spec §2: `UE = (-z, x, y) * 100`; spin axis = UE **+Y**.

## Steps

- [x] **0. Plan + scope** — this file. Close the editor; branch `showcase/sea-of-probabilities`.
- [x] **1. Die mesh** — `blender/make_die.py` builds the rounded box (bevel 0.18, 2 segs) + pip discs (r 0.078, 10 segs, PIP_OFF 0.205, spec face table) in **three's frame**, converts to Blender, exports FBX with two material slots; headless import to `/Game/SeaOfProbabilities/Meshes/SM_Die`. Verify: asset exists, 2 slots, bounds ≈ 100 cm.
- [x] **2. Noise** — exact `mulberry32(1337)` simplex port: `noise/simplex2_ref.py` (bit-exact JS port), generated `perm[512]`, then the same in C++ (`SeaNoise.h`) and HLSL (for the WPO Custom node). Verify Python vs C++ on ≥8 samples to 1e-6 (and vs Node if available).
- [x] **3. Materials** — `M_DieBody` / `M_DiePips` (clear coat, metallic 1, rough 0.71, cc 0.09/0.29; pips: `neon = lerp(A,B,hue)`, base lerp, emissive `neon*glow*glowStrength`), shared WPO: wave height + horizon term + `theta` about +Y + `yOffset`; linear fog via `M_PP_Fog`; `M_PP_Vignette`. Built by `tools/build_sea_assets.py` (headless).
- [x] **4. C++ plugin `SeaOfProbabilities`** _(built + noise-verified; behaviours to be exercised in PIE — see log)_ — `ASeaOfProbabilitiesActor`: settings UPROPERTYs (all spec params, defaults from §3), ISM grid build/rebuild, per-frame order §4.4: wave `t`, hover pick (analytic ray-march + bisection), `pulse`, splash rings, integration §4.7 (springs, spin, hop, glow), custom-data push. Input: mouse move/click (6 px / 350 ms), Space = freeze. Build with `build_ue_plugin.ps1`-style UBT call; SAC off.
- [x] **5. Level `L_SeaOfProbabilities`** — actor, sun (az 197°, el 34°, colour/intensity), sky light, PP volume (ACES, manual exposure ≈ 0.52, bloom 0.6 / thr 1 / radius ≈ 0.4, vignette, fog materials), solid bg `#242424`. Saved headless; **verified by reloading** (earlier headless spawns silently didn't persist — save via `save_dirty_packages`, then reload and count actors).
- [ ] **6. Idle life** — idle splash (`idleEvery`, `idleStrength`) + idle cursor on `noise2(tt,3.7)/(tt+11.1,9.2)`; `lastInput` reset on any input.
- [ ] **7. Camera** — orbit pawn: FOV 42° **vertical**, start pose from §5, orbit/pan/dolly, damping 0.08, polar ≤ π/2−0.03, distance 10–260, `lockCamera`; camera readout + "copy camera" (three-unit JSON).
- [ ] **8. Tweak panel** — all params live on the actor (editor Details = in-editor panel); runtime UMG panel with the spec's folders; settings round-trip JSON with the web keys; SaveGame.
- [ ] **9. Grid presets + perf** — Web exact 116×100, 256², 512² (default), 1024²; FPS at each; note what holds 60.
- [ ] **10. Parity report** — exact / approximated / missing, mapping table web function → UE.

Realistic for the first hour: 0–3 done, 4 started. Progress is logged below
with the step number so the build can be picked up later today.

## Progress log

_(newest at the bottom)_

**2026-09-15 — session 1 (≈1 h): steps 0–5 done, 6 partly, 7–10 open.**

- **0** Plan written; branch `showcase/sea-of-probabilities`; MCP not used (disconnected + fork-bomb path) — headless Python + C++ instead.
- **1** `blender/make_die.py` → `build/SM_Die.fbx` (266 verts, 21 pips = 1+6+2+5+3+4, 3 slots, ±0.504). Imported headless → `/Game/SeaOfProbabilities/Meshes/SM_Die`: 3 slots, 100.8 cm. **PASS.**
- **2** `noise/simplex2_ref.py` == JS under Node on 8 samples, max diff **0.0**. Generated `SeaNoise.h` (C++) + `SeaNoise_wave.hlsl`. C++ self-check at module load: **PASS, max |C++−JS| = 4.9e-13**.
- **3** `MPC_Sea` + `M_DieBody / M_DiePips / M_DieAce` (clear coat via **Make Material Attributes** — the Python `MaterialProperty` enum has no clear-coat pins) with the shared WPO Custom node (spin about +Y, two-octave simplex wave, horizon term, yOffset), `M_PP_Fog` (linear, planar depth), `M_PP_Vignette`. Assigned to the die slots. **PASS**, no shader errors.
- **4** Plugin `SeaOfProbabilities` compiled first try (46 s). `ASeaOfProbabilitiesActor`: all in-scope params, ISM grid + custom data `[theta,yOff,glow,hue,x3,z3]`, wave time (Space freezes), hover pick (analytic ray-march + bisection) → `Pulse`, click (6 px / 350 ms) → `Splash` rings (kick-once), spring/spin/hop/glow integration, **idle life (step 6) included**, start camera at the spec pose with vertical-FOV 42° kept across aspect. Ticks in the editor viewport too (no input there).
- **5** `L_SeaOfProbabilities`: actor (11,600 dice), Sun (az 197 / el 34, 4 lux), Sky (engine cubemap, 2.0), PostFX (manual exposure, bloom 0.6/thr 1, fog + vignette blendables), Start. Saved, **reloaded and re-counted: PASS**.

**Not yet verified visually** (next session, in the editor): spin direction sign (spec 4.3 — flip the sign in the WPO Custom node if 1→2→6→5 runs backwards), exposure/sun intensity mapping, hover/click feel in PIE, fog distance. **Open:** 7 orbit camera + readout/copy-camera, 8 runtime tweak panel + JSON/SaveGame, 9 grid presets + FPS, 10 parity report. Idle life (6) is implemented but untested.

**2026-09-15 — session 2 (paused mid-verification, user away):**

- **MCP works.** The editor's ModelContextProtocol server listens on `127.0.0.1:8000` whenever the editor is open; the Claude Code harness connection only forms at session start, so it was dead this session (it was `ConnectionRefused` because the editor was closed then). `tools/ue_mcp.py` is the bounded client (one process / one call / hard timeout / no retries / python-process guard) — used only for read-only `list` / `describe` so far; process count stayed at 4.
- Toolsets to use next: `EditorToolset.EditorAppToolset` (`CaptureViewport`, `SetCameraTransform`, `StartPIE`/`StopPIE`, `GetVisibleActors`), `EditorToolset.LogsToolset.GetLogEntries`, `SlateInspectorToolset` (Screenshot, Click/Hover/PressKey), `editor_toolset.toolsets.material.MaterialTools`, `...object.ObjectTools`, `...programmatic.ProgrammaticToolset`. Also `NiagaraToolset_System` exists (Niagara *is* MCP-authorable — the ISM design stands, but note it in the parity report).
- **Spin sign fixed in source, NOT yet rebuilt:** `sea_materials.py` WPO now `r = (P.x*c - P.z*s, P.y, P.x*s + P.z*c)`. Derived from the web's `R_x(+θ)`: top rolls toward three +Z = UE −X; cycle 1→5→6→2 for +θ (the web source *comment* says 1→2→6→5 — the comment is backwards, the math is not; note in parity report).
- **Resume order:** (1) `CaptureViewport` the level, compare to `Sea of Probs DocPics/Chosen/20260909_161232.jpg` (near-black glossy dice, strong highlights, saturated pips, curved horizon) → tune sun intensity / exposure bias / fog; (2) rebuild the three die materials with the corrected spin — either headless `SEA_STEP=3` with the editor closed, or in-editor; (3) `StartPIE` + Slate mouse/key simulation to exercise hover ripple, click splash, Space freeze, idle life; read `LogSea` via `GetLogEntries`; (4) then steps 7–10.

**To resume:** open the editor on `/Game/SeaOfProbabilities/L_SeaOfProbabilities`, PIE, hover/click/Space. Rebuild after C++ edits with `python showcase/sea_of_probabilities/tools/sync_sea_plugin.py --build` (editor closed); re-run asset steps with `SEA_STEP=n` via `tools/build_sea_assets.py`.
