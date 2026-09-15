# Prompt: Port "Sea of Probabilities" to Unreal Engine 5 (Niagara + MetaSounds)

You are porting an existing interactive web piece, **Sea of Probabilities**, from three.js / Web Audio to **Unreal Engine 5** (5.4 or newer). It must use **Niagara GPU particles** for the dice and support **far more dice** than the web version. It should **look, move, react and sound the same**. Every behaviour below has to carry over: the waves, hover ripples, click splashes, the phrase reveal, the entrance "dice rain", idle life, neon glow, post FX, the synthesized sound, and the tweak panel.

## 0. Ground truth

- The web version's full source is **`C:\Projects\SeaOfProbabilities\index.html`**. It's one file of about 1,200 lines: HTML, CSS and a single `<script type="module">`. **Read the whole file before you start.** It is the reference implementation. If this document and the file disagree, the file wins. Note the disagreement and tell me.
- Screenshots may be in `C:\Projects\SeaOfProbabilities\Sea of Probs DocPics\`. Use them as the visual target.
- Don't guess numbers. Every constant below comes from the source. Keep them, and expose them as tweakable parameters wherever the web version does.
- When you finish, report what is exact, what is approximated (and why), and the frame rate at each grid-size preset.

---

## 1. What the piece is

The field is a large grid of black, metallic, rounded-corner **six-sided dice** floating on an animated **noise-wave ocean**. The field curves down toward the horizon, and linear fog fades it into a dark grey background.

- **Hover:** moving the cursor over the field sends a spin ripple through the dice under it and plays a synth pluck. The pitch rises from left to right.
- **Click:** a quick click with no drag launches an expanding **ring** from the click point. As the ring passes, each die is kicked upward and spun, and the dice glow. A kick drum, a supersaw pad swell and a noise sweep play.
- **Phrase:** each die a ripple touches strongly enough is "activated". Activated dice settle so their top face spells the phrase **"INFINITE POSSIBILITIES"** as dice art: face 6 up for letter strokes, face 1 up for the background. Untouched dice settle on whichever quarter turn is nearest.
- **Neon glow:** the pips glow with spin energy. The glow lights up fast, fades slowly, and blends from blue to pink with a random mix per die. Bloom picks up only the glow.
- **Entrance:** on load the dice rain in from above, roughly centre-out with scatter, bouncing when they land. Landings play tiny "digital rain" zaps.
- **Idle life:** after 4 s with no input, a virtual cursor wanders the field on simplex noise, rippling dice and playing plucks. Random splashes also fire every few seconds.
- **Always on:** a low detuned-saw drone with faint static. **There is no beat or drum loop.** One was tried and removed on purpose. Don't add one.
- **UI:** brand text at top left, a gear button (toggles all UI) and a sound toggle at bottom left, a camera readout with a "copy camera" button at bottom right, and a full tweak panel. **Space** freezes the waves.

---

## 2. Coordinate conversion (do this consistently)

three.js is right-handed and Y-up. One die is 1 unit. Unreal is left-handed and Z-up, in cm.

Use **1 three unit = 100 UE cm** and map:

```
UE.X = -three.z * 100      (three +z points toward the default viewer)
UE.Y =  three.x * 100
UE.Z =  three.y * 100
```

That mapping flips handedness, so check rotations visually instead of copying angle signs. The die spins about **three's +X axis**, which is **UE's Y axis**. The required invariants are in §4.3. All distances, radii, speeds and heights in this doc are in **three units**. Multiply by 100 for UE, and keep squared-distance terms consistent (for example, the horizon term divides by `horizonR` in three units, so evaluate it in three units and convert the result).

---

## 3. Parameters (current defaults, which are the user's approved tuning)

Build these into a **`USeaOfProbabilitiesSettings` Primary Data Asset** holding the defaults, plus a runtime copy that the panel edits. Save the runtime copy with **SaveGame**, the equivalent of the web version's `localStorage` key `dice-ocean-params-v2`. Provide "reset defaults" and "copy settings as JSON". The JSON must use these exact key names so settings round-trip between web and UE.

```json
{
  "phrase": "INFINITE POSSIBILITIES", "textRows": 6, "textPos": 0.38,
  "cols": 116, "rows": 100, "spacing": 1.2, "bevel": 0.18, "redAce": false,
  "waveSpeed": 0.11, "waveAmp": 7, "waveScale": 0.018, "horizonR": 1010,
  "pulseRadius": 8, "pulseStrength": 6, "springK": 5, "springC": 2, "activateAt": 0.1,
  "fogNear": 24, "fogFar": 95, "shadows": true,
  "splashRadius": 44, "splashHeight": 10, "splashSpin": 20, "ringSpeed": 10,
  "glowStrength": 4, "glowSense": 0.03, "glowFade": 8, "glowColorA": "#0080ff", "glowColorB": "#ff0066",
  "bgColor": "#242424", "diceColor": "#000000",
  "sunIntensity": 4, "sunColor": "#ffffff", "sunAzimuth": 197, "sunElevation": 34,
  "hemiIntensity": 2, "envIntensity": 2, "exposure": 0.52,
  "roughness": 0.71, "metalness": 1, "clearcoat": 0.09, "clearcoatRough": 0.29,
  "lockCamera": false,
  "intro": true, "introHeight": 35, "introSpread": 2.5,
  "idle": true, "idleAfter": 4, "idleEvery": 4, "idleStrength": 0.6,
  "idleCursor": true, "idleCursorSpeed": 0.12, "idleCursorStrength": 0.7,
  "postFx": true, "bloom": true, "bloomStrength": 0.6, "bloomThreshold": 1, "bloomRadius": 0.4, "vignette": 0.45,
  "sound": true, "soundVolume": 1, "sndRoot": "D", "sndScale": "natural minor", "bpm": 99,
  "hoverVol": 0.17, "hoverOctave": 2, "hoverDecay": 0.5, "pluckBright": 20, "pluckReso": 2,
  "thumpVol": 1.5, "thumpHz": 32, "thumpDecay": 1.1, "sweepVol": 0.095,
  "swellVol": 1.25, "swellAttack": 1.5, "swellChord": "diatonic 7th", "swellCutoff": 4070,
  "padReso": 4.5, "padDetune": 12, "gateDiv": "1/16", "gateDepth": 0.15,
  "wobbleRate": 0.1, "wobbleDepth": 110, "swellLength": 0.75,
  "landVol": 0.26, "ambientVol": 0.07, "ambientCutoff": 240,
  "warmth": 0.85, "reverbMix": 0.4, "reverbDecay": 2.3, "echoMix": 0.28, "echoFeedback": 0.69,
  "ambientTexture": 0.017
}
```

The panel's slider ranges are in the source's "control panel" section (`gui.add(params, key, min, max, step)`). Copy them exactly.

### 3.1 Scaling up the particle count

- Add a **grid preset**: `Web exact (116×100)`, `256×256`, `512×512` (default for UE), `1024×1024`, plus custom. `cols` and `rows` keep their meaning: dice across X, and rows in depth from the far edge (row 0) to the near edge.
- On a bigger grid, keep `spacing` at 1.2 so each die stays the same size and the ocean simply gets bigger.
- The phrase would become tiny on a bigger grid, so add **`phraseScaleWithGrid`** (default **true**). It multiplies `textRows` by `rows / 100` before fitting. When it's false, `textRows` is used raw, like the web version.
- The web version recommends 60×44 on small screens. In UE, just use the preset.
- Bigger fields reach past `fogFar`. That's intended: the fog hides the far edge. Don't change the fog defaults.

---

## 4. Simulation (must match exactly)

### 4.1 Architecture

- **Niagara system `NS_SeaOfProbabilities`** with a **GPU Compute Sim** emitter. Spawn exactly `cols*rows` particles once, one per cell, and give each particle its cell index (`ix = i % cols`, `iz = i / cols`). Particles never die. Rebuild the system when `cols`, `rows`, `spacing`, `bevel` or `redAce` change.
- Keep per-die state **on the GPU**, with a **Grid2D Collection** (or render targets) and **Simulation Stages**. Store: `theta`, `omega`, `yOffset`, `yVel`, `glow`, `activated`, `dropped`, `falling`, and the constants `dropAt`, `hue`, `target`. Don't run a per-die CPU loop. The web version's CPU loops (splash ring over every die, spring integration) all move into HLSL stages.
- The **game thread** keeps only small, scalar state. Every frame it sends User Parameters:
  - wave time `t`, `dt`, and whether the waves are frozen
  - a **pulse queue**: up to 32 `(cellIndex, k)` per frame, from hover and the idle cursor
  - a **splash array**: up to 16 active `(x, z, t0, lastR, k)`, with `lastR` and removal tracked on the CPU exactly as in the source
  - intro start time
  - one-shot "reveal", "scramble" and "replay intro" commands
- **Phrase targets:** draw the phrase to a `cols×rows` **Canvas Render Target** using the exact fitting algorithm (§4.6), then sample it in the sim stage (texel red < 0.5 → target = 1). If Canvas can't render a heavy "Arial Black" style, import a heavy sans font asset (Arial Black or the closest match) and keep the same fit logic.
- **Dice rendering:** Niagara **Mesh Renderer** with the die mesh (§6.1). Position = `(x, height + yOffset, z)`. Orientation = rotation of `theta` about three's +X. Per-particle **Dynamic Material Parameters** carry `glow` and `hue`. Intro dice not yet dropped are scaled to zero, as in the web version.

### 4.2 Waves and horizon (per die, every frame; also needed on the CPU for picking)

```
f = waveScale, amp = waveAmp, zFront = D/2, W = (cols-1)*spacing, D = (rows-1)*spacing
x = -W/2 + ix*spacing,  z = -D/2 + iz*spacing
wave = amp * ( 0.75*noise2(x*f + t, z*f + t*0.35) + 0.25*noise2(x*f*2.6 - t*0.6, z*f*2.6) )
height = wave - (x*x + (z - zFront)^2) / horizonR
```

- Each frame, when not frozen: `t += dt * waveSpeed * waveSpeedScale`. Here `dt = min(frameSeconds, 0.033)`, and `waveSpeedScale` is 0.12 if a "reduced motion" option is on, otherwise 1.
- `noise2` is the source's **2D simplex noise**, with a permutation table shuffled by `mulberry32(1337)`. **Port it bit-for-bit**, including the gradient table, F2/G2, the `70*` scale and the `% 8` gradient pick. Implement it twice: in HLSL (upload the 512-entry `perm` table as a texture or array Data Interface) and in C++ (for picking and the idle cursor). The HLSL and C++ versions must agree.

```js
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
// perm: p[i]=i; for i=255..1: j=floor(rand()*(i+1)); swap; perm[i]=p[i&255] for i<512
// grad=[[1,1],[-1,1],[1,-1],[-1,-1],[1,0],[-1,0],[0,1],[0,-1]], F2=0.5*(sqrt3-1), G2=(3-sqrt3)/6
// corner contribution: t=0.5-x*x-y*y; if t>0: t*=t; n=t*t*dot(grad[perm[ii+perm[jj]]%8], (x,y)); return 70*(n0+n1+n2)
```

(The full function is in the source under `// ---------- simplex noise (2D) ----------`.)

### 4.3 Die orientation invariants

The die rotates **only about three's +X axis**, which keeps quarter turns flat. Face layout in three's coordinates:

| Normal | Pips |
|---|---|
| +Y (top at rest) | 1 |
| −Y | 6 |
| +Z | 2 |
| −Z | 5 |
| +X | 3 |
| −X | 4 |

`theta = 0` must show **1 up**, and `theta = π` must show **6 up**. Rotating about X cycles the top face through 1, 2, 6, 5. Check this in UE after converting axes. If the face after a +90° turn doesn't match the web build's rotation direction, flip the sign of the angle (not the face table).

### 4.4 Per-frame order (keep this order)

1. Update wave heights (GPU; the CPU evaluates on demand for picking).
2. **Hover pick → pulse** (§4.5).
3. **Idle splash** check (§4.8).
4. **Idle cursor wander → pulse** (§4.8).
5. **Advance the splash rings** (§4.5).
6. **Per-die integration** (§4.7).
7. Render.

### 4.5 Hover ripple, click splash, pulse

**Picking:** the web version raycasts against an invisible heightfield mesh with one vertex per die. In UE, trace the mouse ray against the analytic height function. Ray-march, then refine with bisection. Map the hit to `ix = round((hx + W/2)/spacing)` and `iz = round((hz + D/2)/spacing)`. Reject hits outside the grid or more than `0.55*spacing` from the cell centre on either axis. Also skip picking while any mouse button is held, so orbit-dragging doesn't ripple, and while the cursor is outside the viewport.

**Hover:** when the picked cell index changes, call `pulse(idx, 1)` and `hoverNote(ix)`.

**`pulse(j, k)`:**

```
cell = ceil(pulseRadius/spacing)
for each neighbour within ±cell (clamped to the grid):
  d = spacing * hypot(dx, dz); if d > pulseRadius: skip
  fall = 1 - d/pulseRadius
  omega[idx] += pulseStrength * fall*fall * k
  if fall >= activateAt: activated[idx] = 1
```

**Click** = left button released within **6 px** of where it was pressed and within **350 ms**, and not over UI. Trace to the field. If it hits, push `splash {x: hit.x, z: hit.z, t0: now, lastR: 0, k: 1}` and call `splashSound(1)`.

**Splash rings**, each frame, for each splash:

```
r = (now - t0)/1000 * ringSpeed
for every die: d = hypot(x - s.x, z - s.z)
  if d <= lastR or d > r or d > splashRadius: skip
  fall = 1 - d/splashRadius
  yVel += splashHeight * fall * k
  omega += splashSpin * fall * k
  if fall >= activateAt: activated = 1
lastR = r; remove the splash when r > splashRadius
```

(Each die gets kicked exactly once as the ring front passes it.)

### 4.6 Phrase → targets

The canvas is `cols × rows`, filled white, with black text centred horizontally.

```
words = phrase.trim().toUpperCase().split(/\s+/)
maxW = cols * 0.94
px = max(5, round(textRows))        // (× rows/100 first if phraseScaleWithGrid)
loop while px >= 5:
  font = 900 weight, px size, "Arial Black"
  greedy word-wrap: add a word to the line if measureText(line + ' ' + word) <= maxW
  fitsW = every line width <= maxW; fitsH = lines*px*1.12 <= rows*0.62
  break if fitsW && fitsH; else px--
lineH = px*1.12; centerY = rows*textPos; top = centerY - lines*lineH/2
line k drawn with its centre at y = top + lineH*(k+0.5), textBaseline middle
target[iz*cols + ix] = (red channel of pixel (ix, iz) < 128) ? 1 : 0
```

Recompute when `phrase`, `textRows` or `textPos` change. The dice keep their state.

### 4.7 Per-die integration (GPU stage)

```
if !dropped:
  if introT < dropAt: hide (scale 0), continue
  dropped = 1; falling = 1; yVel = -6; omega += (rand-0.5)*14
if activated: t0 = target ? PI : 0; rest = t0 + round((theta - t0)/(2PI))*2PI
else:         rest = round(theta/(PI/2)) * (PI/2)
omega += (-springK*(theta - rest) - springC*omega) * dt
theta += omega * dt
if falling:
  yVel -= 70*dt; yOffset += yVel*dt
  if yOffset <= 0: yOffset = 0; yVel *= -0.25; falling = 0; (landing event → zap sound)
else:
  yVel += (-14*yOffset - 2.4*yVel) * dt; yOffset += yVel*dt
glowTarget = min(1, abs(omega)*glowSense)
glow += (glowTarget - glow) * min(1, dt * (glowTarget > glow ? 10 : glowFade))
```

**Initial state at rebuild:** `theta` = a random quarter turn `floor(rand*4)*PI/2`. `hue` = rand in [0, 1). Everything else is 0. Use a stable per-cell hash for `rand`. Matching the web RNG sequence isn't required.

**Entrance (`startIntro`):** `introStart = now`. If `intro` is false, every die starts dropped and not falling, with `yOffset = 0`. Otherwise, for each die:

```
d = hypot(x, z) / hypot(W/2, D/2)
dropAt = introSpread * (0.4*d + 0.6*rand)
dropped = 0; falling = 0; yOffset = introHeight; yVel = 0
introEnd = introStart + (introSpread + 1.5)*1000 ms
```

**Landing sounds:** the GPU can't cheaply report individual landings. Instead, compute each die's landing time on the CPU. It's deterministic: after `dropAt`, the die falls from `introHeight` with `yVel0 = -6` and gravity 70, so `yOffset(τ) = introHeight - 6τ - 35τ²`. Trigger `landThump()` whenever any die's landing time falls within the frame. `landThump` already throttles itself to one call per 40 ms, so sort the landing times once and walk a cursor through them. That matches the web build's sound.

**Reveal:** every die `activated = 1`, `omega += 5 + rand*6`. **Scramble:** `activated = 0`, same spin kick.

### 4.8 Idle life

- `lastInput` resets on mouse move, mouse down, key down, wheel, or touch.
- **Idle** means `now >= introEnd && now - lastInput >= idleAfter*1000`.
- **Idle splash:** if `idle` is on, idle, and `now >= nextIdle`:
  - `x = (rand-0.5)*W*0.7`, `z = (rand-0.5)*D*0.7`
  - push splash `{x, z, t0: now, lastR: 0, k: idleStrength}`
  - `splashSound(0.5*idleStrength)`
  - `nextIdle = now + idleEvery*(0.6 + rand*0.8)*1000`
- **Idle cursor:** if `idle` and `idleCursor` are on, and idle:
  - `tt = (now/1000)*idleCursorSpeed`
  - `x = noise2(tt, 3.7)*W*0.45`, `z = noise2(tt + 11.1, 9.2)*D*0.45`
  - map to the clamped cell
  - when the cell changes: `pulse(idx, idleCursorStrength)` and `hoverNote(ix, 0.7)`
  - when not idle, reset the last idle cell to −1

### 4.9 Freeze

**Space** toggles `frozen`. It only stops wave time `t`; the physics keep running. While frozen, show the red "WAVES FROZEN" tag at top centre.

---

## 5. Camera and input

- Perspective camera with **vertical FOV 42°**. Near clip 0.1 and far clip 600 (three units). Set the UE FOV axis correctly: UE uses horizontal FOV by default, so derive it from aspect or set the aspect-ratio axis constraint to vertical.
- **Start position** (three units): `(-23.55, 27.5, 65.72)`, looking at target `(2.67, -22.52, 6.29)`. Convert with §2.
- **Orbit controls** like three's OrbitControls:
  - left-drag orbits around the target, right-drag pans, wheel dollies
  - damping factor **0.08**
  - polar angle ≤ **π/2 − 0.03**, so the camera never goes below the horizon
  - distance between **10 and 260**
  - `lockCamera` turns the controls off
- **Camera readout** at bottom right: `fps`, `pos x, y, z`, `look x, y, z`, shown in **three units** with 1 decimal. "Copy camera" copies `{"position":[...],"target":[...],"fov":42}`, rounded to 2 decimals, in three units, so values can be pasted back into the web build.

---

## 6. Look

### 6.1 Die mesh

- Generate it procedurally in the editor with a Python or Editor Utility script, so `bevel` can rebuild it.
- **Rounded box** 1×1×1, corner radius `bevel`, 2 segments.
- **Pips:** discs of radius **0.078** with **10 segments**, placed `0.5 + 0.004` out from the centre along each face normal. Offsets use `PIP_OFF = 0.205` on the face's tangent and bitangent axes. The tangent is `(1,0,0)` and the bitangent `(0,1,0)` after rotating +Z onto the face normal (`setFromUnitVectors`).
- **Pip layouts** in `(u, v)` multiples of `PIP_OFF`:

  ```
  1: (0,0)
  2: (-1,-1)(1,1)
  3: (-1,-1)(0,0)(1,1)
  4: (-1,-1)(-1,1)(1,-1)(1,1)
  5: (-1,-1)(-1,1)(0,0)(1,-1)(1,1)
  6: (-1,-1)(-1,0)(-1,1)(1,-1)(1,0)(1,1)
  ```

- **Vertex colours:** body white `#ffffff`, pips `#17171d`. The face-1 pip is `#c73535` if `redAce`, otherwise `#17171d`.
- Keep the triangle count low. With 1M instances, provide a **LOD1** that swaps the pip discs for a baked pip mask in the material.

### 6.2 Dice material (matches `MeshPhysicalMaterial` + glow patch)

- Base colour = `vertexColor * diceColor`. With `diceColor #000000`, everything is black; the vertex colour exists only to derive the pip mask.
- `pipLum = (vc.r + vc.g + vc.b)/3` (from the unmultiplied vertex colour)
- `pipMask = 1 - smoothstep(0.35, 0.75, pipLum)`
- `neon = lerp(glowColorA, glowColorB, hue)`
- `BaseColor = lerp(baseColor, neon*0.35, pipMask*glow)`
- `Emissive = neon * pipMask * glow * glowStrength`, in HDR, so bloom catches only this
- Metallic **1**, Roughness **0.71**, Clear Coat **0.09**, Clear Coat Roughness **0.29**
- Use the **Clear Coat** shading model. Reflections come from the sky light (env intensity 2).

### 6.3 Lighting, fog, background, post

- **Directional light (sun):** colour `sunColor`, intensity mapped so that 4 looks like the web build. Direction from spherical coordinates at radius 90:
  - `pos = (r·cos(el)·sin(az), r·sin(el), r·cos(el)·cos(az))`, with azimuth 197° and elevation 34°
  - the light points from `pos` toward the origin
  - dynamic shadows when `shadows` is on
- **Sky light:** a neutral studio cubemap standing in for three's `RoomEnvironment`, intensity mapped from `envIntensity` 2.
- **Hemisphere light** (sky `#f7f9ff`, ground `#d9d9e2`, intensity 2): approximate it with the sky light's lower-hemisphere colour, or a second, very soft sky light. Match the web screenshots.
- **Background:** solid `bgColor`. No sky sphere, no atmosphere.
- **Fog:** **linear** from `fogNear` to `fogFar`, coloured `bgColor`. UE's Exponential Height Fog isn't linear, so build a post-process material (or a per-material distance lerp) that does `lerp(color, bgColor, saturate((dist - fogNear)/(fogFar - fogNear)))` (plain linear, no smoothstep), with `dist` being the view distance in three units. Sky pixels are `bgColor` anyway.
- **Tone mapping:** ACES filmic, **manual exposure** equivalent to `exposure` 0.52. Turn off auto-exposure and eye adaptation.
- **Bloom:** threshold `bloomThreshold` 1.0, intensity `bloomStrength` 0.6, radius equivalent to 0.4. Only the neon should bloom.
- **Vignette** (post-process material, applied after tone mapping):

  ```
  d = distance(uv, 0.5)
  v = smoothstep(0.85, 0.3, d)
  color *= lerp(1, v, vignette)
  ```

- `postFx` off → bloom and vignette off.
- **UI palette:** if `bgColor` luminance (`0.2126r + 0.7152g + 0.0722b`) is below 0.45, UI ink is `#f2f2f5`, muted `#9a9aa6`, hairlines at 22% white. Otherwise ink is `#17171d` and muted `#7d7d88`. Accent red is `#c73535`.

---

## 7. Sound (MetaSounds): recreate the synths exactly

Everything is synthesized. No samples, except a reverb impulse response that you generate yourself (see master chain). The Web Audio graph is below; the source functions are `ensureAudio`, `setWarmth`, `setReverb`, `setEcho`, `startAmbient`, `pluck`, `kick`, `duck`, `zap`, `sweep`, `swell`, `hoverNote`, `landThump`, `splashSound`. Build **one MetaSound Source per voice type**, triggered with parameters from the game thread, and a **master effects chain**.

### 7.1 Musical helpers

- `ROOTS = {A:0, Bb:1, B:2, C:3, C#:4, D:5, Eb:6, E:7, F:8, F#:9, G:10, G#:11}`
- `rootHz = 110 * 2^(ROOTS[sndRoot]/12)` (D → 146.83 Hz)
- **Scales:**
  - `natural minor` [0,2,3,5,7,8,10]
  - `dorian` [0,2,3,5,7,9,10]
  - `harmonic minor` [0,2,3,5,7,8,11]
  - `minor pentatonic` [0,3,5,7,10]
  - `lydian` [0,2,4,6,7,9,11]
- `noteHz(step, octave) = rootHz * 2^(octave + floor(step/len) + scale[step mod len]/12)`, with a positive modulo
- **Chords:**
  - `diatonic 7th` → scale steps [0,2,4,6] from the degree
  - `diatonic 9th` → [0,2,4,6,8]
  - fixed semitone shapes on `noteHz(degree)`: `minor 7` [0,3,7,10], `minor 9` [0,3,7,10,14], `sus2` [0,2,7,12], `power (1-5-8)` [0,7,12], `open (1-5-8-12)` [0,7,12,19]
- **Swell degree:** random pick from `PROGRESSION = [0, 5, 3, 6]`
- **Gates:** `off` 0, `1/8` 2, `1/16` 4, `1/32` 8 (multiplies `bpm/60`)

### 7.2 Master chain

```
voices → MASTER bus
PUMP bus → MASTER             (drone + pads go through PUMP; it is ducked by click kicks)
MASTER → dry (gain 1) ─┐
MASTER → convolution reverb → wet (reverbMix) ─┤
                                                ├→ waveshaper (tanh drive) → compressor → volume (soundVolume) → out
ECHO send → HP 280 Hz → delayL ─→ out L
                         delayL → delayR ─→ out R
                         delayR → LP 3400 Hz → feedback (echoFeedback) → delayL
            (L/R merged) → echo wet (echoMix) → MASTER
```

- **Delay time** (both taps) = `0.75 * 60/bpm` (dotted eighth). Glide it with a 0.05 s time constant when `bpm` changes.
- **Waveshaper:** `y = tanh(x*drive)/tanh(drive)`, where `drive = 1 + warmth*4`, with 4× oversampling.
- **Compressor:** threshold −12 dB, knee 10, ratio 3, attack 4 ms, release 150 ms.
- **Reverb IR:** stereo, length `reverbDecay` seconds. For each channel:
  - start with white noise
  - apply a one-pole lowpass with coefficient `a = 1 - exp(-2π·4800/sampleRate)` (`y += a*(noise - y)`)
  - multiply by `(1 - i/len)^3 * 2.4`
  
  Generate the IR as a WAV with an editor Python script and load it into a **Submix Convolution Reverb**. Regenerate it when `reverbDecay` changes. If regenerating at runtime isn't practical, pre-bake IRs from 0.5 to 8 s in 0.1 s steps.
- **Duck** (sidechain on the PUMP bus gain), called at time `t` with `amount`:
  - glide toward `1 - amount` with time constant 0.004 s starting at `t`
  - then glide toward 1 with time constant `(60/bpm)*0.18`, starting at `t + 0.03`
  
  Use Audio Modulation (a Control Bus), or run the PUMP bus through a MetaSound that applies the envelope.
- `setTargetAtTime(v, t, τ)` means an exponential approach: `x += (v - x)*(1 - exp(-dt/τ))`.

### 7.3 Voices (all envelopes in seconds)

**Pluck** — `pluck(hz, vol, decay, pan)`, used for hover:
- Two **saws** at `hz`, detuned −10 and +10 cents, plus a **square** at `hz/2` with gain 0.35. Sum them, then multiply by 0.5.
- **Lowpass**, Q = `pluckReso`. Cutoff starts at `min(16000, hz*pluckBright)` and ramps exponentially to `max(120, hz*1.1)` by `0.7*decay`.
- **Amp:** 0.0001 → `vol` (linear, 4 ms) → 0.0001 (exponential, at `decay`).
- **Stereo pan** `pan`. Output to MASTER **and** the ECHO send.

**`hoverNote(ix, volMul = 1)`:**
- Throttle: at most once per **65 ms**.
- `u = ix/(cols-1)`, `step = round(u*9)`
- `pluck(noteHz(step, hoverOctave), hoverVol*volMul, hoverDecay, (u*2-1)*0.7)`

**Kick** — `kick(t, vol, hz, decay)`:
- **Sine** pitch: `hz*5` → exponential to `hz*1.6` at +0.03 s → exponential to `hz` at +0.12 s.
- **Amp:** 0.0001 → `vol` (linear, 3 ms) → 0.0001 (exponential, at `decay`).
- **Beater click:** 30 ms of white noise → highpass 2500 Hz → gain `vol*0.25`, decaying exponentially to 0.0001 in 18 ms.
- Output to MASTER.

**Supersaw pad** — `swell(vol, seconds)`:
- `chord = chordHz(random PROGRESSION degree)` at octave 0
- `attack = min(swellAttack, seconds*0.5)`, `hold = max(attack + 0.1, seconds*0.35)`
- **Voices:** for each chord note, 3 saws detuned `j*padDetune + random(±2)` cents, for j = −1, 0, +1. Gain is 0.4 for the chord root and 0.28 for the other notes. Pan each saw `j*0.55`. Add a **sine sub** at `chord[0]/2` with gain 0.5.
- **Lowpass**, Q = `padReso`:
  - 160 Hz → exponential to `open = max(161, swellCutoff)` at `attack`
  - hold until `hold`
  - exponential to 160 at `seconds`
  - plus a sine LFO of `wobbleRate` Hz and depth `wobbleDepth` Hz added to the cutoff
- **Trance gate:**
  - `rate = (bpm/60)*GATES[gateDiv]`, `depth = rate ? gateDepth : 0`
  - amp gain = `1 - depth/2 + (square LFO at rate → lowpass 90 Hz)*depth/2`
- **Envelope:** 0.0001 → `peak` (linear, at `attack`) → hold `peak` until `hold` → 0.0001 (exponential, at `seconds`), where `peak = 0.16*vol*swellVol`.
- Output to the **PUMP** bus, plus an ECHO send at gain 0.25.

**Noise sweep** — `sweep(vol, seconds)`:
- Looping white noise → **bandpass** Q 4. Frequency: 300 Hz → exponential to 5000 at `0.5*seconds` → exponential to 800 at `seconds`.
- **Amp:** 0.0001 → `vol` (linear, at `0.4*seconds`) → 0.0001 (exponential, at `seconds`).
- Output to MASTER and the ECHO send.

**`splashSound(vol)`:**
- `kick(now, thumpVol*vol, thumpHz, thumpDecay)`
- `duck(now, 0.75)`
- `seconds = clamp((splashRadius/ringSpeed)*swellLength, 0.8, 12)`
- `swell(vol, seconds)`
- if `sweepVol > 0`: `sweep(sweepVol*vol, seconds)`

**Landing zap** — `zap(vol, hz)`:
- **Square**, pitch `hz*4` → exponential to `hz` in 0.04 s.
- **Bandpass** at `hz*2`, Q 3.
- **Amp:** `vol` → exponential to 0.0001 at 0.09 s.
- Random pan in ±0.6. Output to MASTER.

**`landThump()`:** throttle to once per **40 ms**, then `zap(landVol*0.35, noteHz(randInt(0..9), 1))`.

**Drone + static** (always on while sound is on):
- **Fade:** both drone and static fade in over 2.5 s (linear) when sound turns on, and out over 0.8 s when it turns off.
- **Drone:**
  - saws at `rootHz/2`, detuned −9 and +9 cents
  - a sine at `rootHz/2` with gain 0.8
  - a saw at `rootHz*0.75`, detuned +4 cents, with gain 0.35
  - all through a **lowpass** with Q 4 and cutoff `ambientCutoff`, plus a 0.07 Hz sine LFO of depth `ambientCutoff*0.6`
  - gain `ambientVol`, into **PUMP**
- **Static:**
  - a looping 1 s white-noise buffer → bandpass 3200 Hz, Q 0.7
  - gain `ambientTexture`, plus a 0.05 Hz sine LFO of depth `ambientTexture*0.6` added to that gain
  - into MASTER
- **Retune:** changing root, volume, cutoff or texture glides them over 0.3 s.

**Sound toggle** fades as above and saves the state. UE has no autoplay restriction, so start sound when the level starts if `sound` is true.

---

## 8. UI (UMG)

- **Brand**, top left:
  - line 1: "SEA OF PROBABILITIES" with a red `.`, Tomorrow SemiBold 15 px, letter-spacing 0.34 em
  - line 2: "Anantak · hero prototype 03", 10 px, uppercase, 0.22 em, muted colour
  - import Tomorrow from Google Fonts (OFL)
- **Gear button** (36 px circle, bottom left, 26 px from the left edge and 20 px from the bottom): toggles every UI element except itself. When the UI is hidden, the gear sits at 45% opacity. Save the hidden/shown state.
- **Sound button** (36 px circle, 72 px from the left edge): speaker icon; the sound waves appear only when sound is on. Button opacity is 0.6 when off and 1 when on.
- **Camera readout and "COPY CAMERA" pill** at bottom right, monospace 11 px. Hide them on narrow viewports (< 700 px).
- **Loading overlay** with the text "ROLLING THE DICE". It fades out over 0.5 s after the first rendered frame.
- **Tweak panel:** a runtime panel mirroring the web version's lil-gui folders, with the same names, order and ranges.
  - top level: `lock camera`
  - **field (rebuilds):** columns, rows, spacing, bevel, red ace pip, plus the new grid preset and `phraseScaleWithGrid`
  - **waves** · **ripple** · **splash (click)** · **neon glow** · **phrase** · **look** · **lighting** · **dice material** · **entrance** (with "replay entrance") · **idle life** · **post fx**
  - **sound:** sound on, master volume, tempo (bpm), then subfolders **fx** (drive, reverb mix, reverb decay, echo mix, echo feedback, static) · **key** (root note, scale) · **hover pluck** (+ ▶ test note) · **click: kick + supersaw** (+ ▶ test click) · **drone & landings**
  - buttons: reveal phrase · scramble dice · copy settings · reset defaults
  - "field (rebuilds)" changes apply on release (onFinishChange). Everything else applies live.

---

## 9. Deliverables

1. A UE5 project, or plugin content folder, containing:
   - `NS_SeaOfProbabilities`
   - the sim-stage HLSL, including the exact `noise2` port
   - `BP_SeaOfProbabilities` (or a C++ `ASeaOfProbabilitiesActor`) running input, picking, the idle logic, splash bookkeeping, intro timing and landing scheduling
   - the die mesh generator script, `M_Dice`, the post materials (fog, vignette)
   - the MetaSound sources, the submix chain, `WBP_SeaHUD` and `WBP_TweakPanel`
   - the settings data asset and SaveGame
   - a demo level: `L_SeaOfProbabilities`
2. A README covering how to run it, the grid presets, and where each web function lives in UE (a mapping table).
3. A parity report: exact / approximated / missing, plus FPS at 116×100, 512×512 and 1024×1024 on the dev machine.

## 10. Acceptance checks (verify each one and report)

- [ ] With the `Web exact (116×100)` preset and the default camera, the view composition matches the web build and the screenshots (curvature, fog falloff, dice size, lighting direction).
- [ ] Waves use the same noise: compare the C++ `noise2(0.3, 0.7)` and several other samples against the JS function (run it with Node) to 1e-6.
- [ ] Hovering spins a radius-8 patch. Pips glow blue↔pink and fade. The pluck pitch rises left to right and pans.
- [ ] A click makes a ring that travels at 10 units/s out to radius 44. Dice hop and spin once as it passes. The kick thumps, the pad swells over ~3.3 s with a subtle 1/16 gate, the sweep rises and falls, and the drone ducks.
- [ ] Dice touched by ripples settle to spell INFINITE POSSIBILITIES (6 up = stroke). "Reveal phrase" shows the whole phrase; "scramble" breaks it up again.
- [ ] The entrance rain lasts ~2.5 s, roughly centre-out, with bounces and rapid zap ticks.
- [ ] After 4 s idle, the wandering cursor ripples and plucks, with splashes about every 2.4–5.6 s. Any input stops it immediately.
- [ ] Space freezes the waves only. The gear hides the UI. Copy camera outputs three-unit JSON.
- [ ] **No background beat or drum loop exists.**
- [ ] Settings persist, reset, and round-trip JSON with the web build.
- [ ] 512×512 runs smoothly (target 60 fps on the dev GPU). Report 1024×1024 performance, and document which options, such as shadows or LOD1 pips, make it hold 60 fps.
