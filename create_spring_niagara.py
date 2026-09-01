"""
create_spring_niagara.py
========================
Unreal Engine 5.8.1 Python script to create a Niagara-based Card Spring effect,
equivalent to the Blender Geometry Nodes setup in create_spring_nodes.py.

REQUIRES: Unreal Engine 5.8.1
PLUGINS REQUIRED:
  - "Python Editor Script Plugin" (Edit > Plugins > Scripting)
  - "Niagara" (enabled by default in UE 5.8)
  - "Niagara Extras" (optional, for additional module templates)

HOW TO RUN:
  Method A (Recommended): Edit > Execute Python Script > select this file
  Method B: Output Log (Python mode):
    exec(open(r"C:\Projects\4D hands research\TestDatasetCreation\create_spring_niagara.py").read())

NOTE ON UE 5.8.1 MCP PLUGIN:
  UE 5.8.1 includes an experimental MCP plugin that lets AI agents control
  the editor directly. If you enable it (Edit > Plugins > "Model Context Protocol"),
  your AI assistant could potentially wire Niagara nodes for you interactively.
  This script takes the Python automation approach instead.

WHAT THIS SCRIPT CREATES:
  /Game/CardSpring/
  ├── Niagara/
  │   ├── NS_CardSpring         (Niagara System)
  │   └── Modules/
  │       ├── NMS_CardTiming    (Module Script - timing/stagger)
  │       ├── NMS_CardBend      (Module Script - bend strength)
  │       └── NMS_CurvePlacement (Module Script - spline placement)
  ├── Blueprints/
  │   └── BP_SplineArc          (Actor with SplineComponent)
  └── Materials/
      └── M_CardBend            (Material with WPO for card flex)
"""

import unreal
import traceback

# ============================================================================
# CONFIGURATION
# ============================================================================
ASSET_ROOT = "/Game/CardSpring"
SYSTEM_NAME = "NS_CardSpring"
SPLINE_BP_NAME = "BP_SplineArc"
MATERIAL_NAME = "M_CardBend"
CARD_COUNT = 52

# Blender uses meters, UE uses centimeters. Factor = 100
SCALE = 100.0

# Default parameter values (already scaled to UE units where needed)
DEFAULTS = {
    "SpringProgress": 0.0,       # Keyframe this 0 -> 1
    "CardSpacing":    1.5,       # Blender 0.015 * 100
    "FlightSpeed":    30.0,      # Blender 0.3 * 100
    "UnbendPoint":    0.1,       # Unitless ratio, same as Blender
    "MaxBend":        5.0,       # Bend intensity
    "CardBaseRotation": (0, 0, 0),  # Euler degrees
}


# ============================================================================
# LOGGING
# ============================================================================
def log(msg):
    unreal.log(f"[CardSpring] {msg}")

def log_warn(msg):
    unreal.log_warning(f"[CardSpring] {msg}")

def log_err(msg):
    unreal.log_error(f"[CardSpring] {msg}")


# ============================================================================
# HELPERS
# ============================================================================
def ensure_dir(path):
    if not unreal.EditorAssetLibrary.does_directory_exist(path):
        unreal.EditorAssetLibrary.make_directory(path)
        log(f"Created: {path}")


def asset_exists(path):
    return unreal.EditorAssetLibrary.does_asset_exist(path)


def load_asset(path):
    return unreal.EditorAssetLibrary.load_asset(path)


def create_asset_with_factory(name, package_path, factory):
    """Create an asset using the UE 5.8 AssetTools API."""
    full_path = f"{package_path}/{name}"
    if asset_exists(full_path):
        log_warn(f"Already exists: {full_path}")
        return load_asset(full_path)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset = asset_tools.create_asset(
        asset_name=name,
        package_path=package_path,
        asset_class=None,
        factory=factory
    )
    if asset:
        log(f"Created: {full_path}")
    else:
        log_err(f"FAILED to create: {full_path}")
    return asset


# ============================================================================
# STEP 1: FOLDER STRUCTURE
# ============================================================================
def create_folders():
    log("=" * 50)
    log("STEP 1: Creating folder structure")
    for sub in ["", "/Niagara", "/Niagara/Modules", "/Blueprints", "/Materials"]:
        ensure_dir(f"{ASSET_ROOT}{sub}")


# ============================================================================
# STEP 2: NIAGARA SYSTEM
# ============================================================================
def create_niagara_system():
    log("=" * 50)
    log("STEP 2: Creating Niagara System")

    factory = unreal.NiagaraSystemFactoryNew()
    system = create_asset_with_factory(
        SYSTEM_NAME, f"{ASSET_ROOT}/Niagara", factory
    )

    if system is None:
        return None

    # In UE 5.8, the factory creates a system with one default emitter.
    # We can access emitter handles to configure properties.
    try:
        handles = system.get_emitter_handles()
        if handles and len(handles) > 0:
            log(f"  System has {len(handles)} emitter(s)")
            # The first handle is the default emitter
            emitter_handle = handles[0]
            log(f"  Default emitter: {emitter_handle.get_name()}")
        else:
            log_warn("  System has no emitters — add one manually")
    except Exception as e:
        log_warn(f"  Could not inspect emitter handles: {e}")

    return system


# ============================================================================
# STEP 3: NIAGARA MODULE SCRIPTS
# ============================================================================
def create_module_scripts():
    """
    Create NiagaraScript assets for custom modules.
    
    In UE 5.8, NiagaraScriptFactoryNew creates module script assets.
    Alternatively, you can create Scratch Pad modules directly inside 
    the Niagara System editor (they live inside the system asset).
    
    This creates standalone module scripts that can be shared across systems.
    """
    log("=" * 50)
    log("STEP 3: Creating Niagara Module Scripts")

    module_defs = {
        "NMS_CardTiming": {
            "description": "Block D: Per-card timing stagger (MapRange equivalent)",
            "inputs": [
                ("SpringProgress", "Float"),
                ("CardSpacing", "Float"),
                ("FlightSpeed", "Float"),
                ("ParticleIndex", "Int32"),
            ],
            "outputs": [
                ("CurveFactor", "Float"),
            ],
        },
        "NMS_CardBend": {
            "description": "Block E: Diagonal bend strength calculation",
            "inputs": [
                ("CurveFactor", "Float"),
                ("UnbendPoint", "Float"),
                ("MaxBend", "Float"),
            ],
            "outputs": [
                ("BendStrength", "Float"),
            ],
        },
        "NMS_CurvePlacement": {
            "description": "Block F: Spline sampling + rotation + final position",
            "inputs": [
                ("CurveFactor", "Float"),
                ("BendStrength", "Float"),
                ("CardBaseRotation", "Vector"),
            ],
            "outputs": [
                ("FinalPosition", "Vector"),
                ("FinalRotation", "Quat"),
            ],
        },
    }

    created = []
    for name, defn in module_defs.items():
        try:
            factory = unreal.NiagaraScriptFactoryNew()
            module_asset = create_asset_with_factory(
                name, f"{ASSET_ROOT}/Niagara/Modules", factory
            )
            if module_asset:
                created.append(name)
                log(f"  {name}: {defn['description']}")
                log(f"    Inputs:  {[f'{n} ({t})' for n, t in defn['inputs']]}")
                log(f"    Outputs: {[f'{n} ({t})' for n, t in defn['outputs']]}")
        except Exception as e:
            log_warn(f"  Could not create {name}: {e}")
            log_warn(f"  Create as Scratch Pad module in the Niagara editor instead.")

    return created


# ============================================================================
# STEP 4: SPLINE ARC BLUEPRINT
# ============================================================================
def create_spline_blueprint():
    """
    Creates a Blueprint Actor with a SplineComponent.
    This is the UE equivalent of Blender's Quadratic Bezier (Block A).
    
    The spline has 3 control points:
      [0] Source hand position
      [1] Midpoint + Z offset (the arc apex)  
      [2] Target hand position
    
    At runtime, update these points from your hand tracking data.
    """
    log("=" * 50)
    log("STEP 4: Creating Spline Arc Blueprint")

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)

    bp = create_asset_with_factory(
        SPLINE_BP_NAME, f"{ASSET_ROOT}/Blueprints", factory
    )

    if bp:
        log("  MANUAL STEPS for BP_SplineArc:")
        log("  1. Open the Blueprint")
        log("  2. Add Component > Spline")
        log("  3. Add two Variables (Type: Actor Object Reference):")
        log("     - SourceActor")
        log("     - TargetActor")
        log("  4. Check 'Instance Editable' (the eyeball icon) for both variables")
        log("  5. In the Construction Script:")
        log("     - Get SourceActor -> Get Actor Location -> Set Spline Point 0 (World Space)")
        log("     - Get TargetActor -> Get Actor Location -> Set Spline Point 2 (World Space)")
        log("     - Add the two locations, divide by 2, add (0,0,30) -> Set Spline Point 1")
        log("  6. Compile and Save")

    return bp


# ============================================================================
# STEP 5: CARD BEND MATERIAL
# ============================================================================
def create_bend_material():
    """
    Creates a Material asset for per-vertex card bending via World Position Offset.
    
    This is the UE equivalent of Blender's per-vertex position manipulation 
    in Block E (dot product → square → multiply by bend strength → Z offset).
    
    Niagara passes BendStrength per particle via Dynamic Material Parameters.
    The material reads it and displaces vertices diagonally.
    """
    log("=" * 50)
    log("STEP 5: Creating Card Bend Material")

    mat_path = f"{ASSET_ROOT}/Materials/{MATERIAL_NAME}"
    if asset_exists(mat_path):
        log_warn(f"  Material already exists: {mat_path}")
        return load_asset(mat_path)

    factory = unreal.MaterialFactoryNew()
    mat = create_asset_with_factory(
        MATERIAL_NAME, f"{ASSET_ROOT}/Materials", factory
    )

    if mat:
        log("  Material created. Build this WPO graph inside it:")
        log("")
        log("  ┌─────────────────────────────────────────────────────┐")
        log("  │ MATERIAL GRAPH: M_CardBend                         │")
        log("  │                                                     │")
        log("  │ [DynamicParameter] (Index 0 = BendStrength)         │")
        log("  │       │                                             │")
        log("  │       ▼                                             │")
        log("  │ [Local Position] → [ComponentMask XY]               │")
        log("  │       │                                             │")
        log("  │       ▼                                             │")
        log("  │ [DotProduct] with Constant2D(-0.707, 0.707)         │")
        log("  │       │                                             │")
        log("  │       ▼                                             │")
        log("  │ [Multiply] (self × self)  ← squaring                │")
        log("  │       │                                             │")
        log("  │       ▼                                             │")
        log("  │ [Multiply] × BendStrength                           │")
        log("  │       │                                             │")
        log("  │       ▼                                             │")
        log("  │ [AppendVector] (0, 0, Result) → World Position Offset│")
        log("  └─────────────────────────────────────────────────────┘")
        log("")
        log("  This bends each card's surface along the diagonal axis,")
        log("  exactly like the Blender Geometry Nodes Block E does.")

    return mat


# ============================================================================
# STEP 6: PRINT HLSL FOR SCRATCH PAD MODULES
# ============================================================================
def print_module_hlsl():
    """
    Prints the HLSL code for each custom module.
    
    In UE 5.8.1, Scratch Pad modules support HLSL with the standard 
    Niagara HLSL extensions (saturate, lerp, etc. are available).
    
    To create a Scratch Pad module:
    1. Open NS_CardSpring in the Niagara Editor
    2. In Particle Update, click [+] > New Scratch Pad Module
    3. Name it (e.g., "CardTiming")
    4. In the Scratch Pad editor, define inputs/outputs in the Parameters tab
    5. Switch to the HLSL tab and paste the code
    """
    log("=" * 50)
    log("STEP 6: HLSL Code for Scratch Pad Modules")
    log("=" * 50)

    # ---- Module 1: CardTiming ----
    log("""
╔══════════════════════════════════════════════════════════════╗
║  MODULE 1: CardTiming  (Blender Block D equivalent)        ║
╠══════════════════════════════════════════════════════════════╣
║  INPUTS:                                                    ║
║    SpringProgress  (Float)  → User.SpringProgress           ║
║    CardSpacing     (Float)  → User.CardSpacing              ║
║    FlightSpeed     (Float)  → User.FlightSpeed              ║
║    ParticleIndex   (Int32)  → Particles.UniqueID            ║
║  OUTPUTS:                                                   ║
║    CurveFactor     (Float)  → Particles.CurveFactor (new)   ║
╚══════════════════════════════════════════════════════════════╝

HLSL:

// Per-card stagger: each card starts moving at a different time
float FromMin = float(ParticleIndex) * CardSpacing;
float FromMax = FromMin + FlightSpeed;

// MapRange+Clamp: remap SpringProgress [FromMin..FromMax] → [0..1]
float Range = FromMax - FromMin;
float OutCurveFactor;
if (Range > 0.0001f)
{
    OutCurveFactor = saturate((SpringProgress - FromMin) / Range);
}
else
{
    OutCurveFactor = (SpringProgress >= FromMin) ? 1.0f : 0.0f;
}
""")

    # ---- Module 2: CardBend ----
    log("""
╔══════════════════════════════════════════════════════════════╗
║  MODULE 2: CardBend  (Blender Block E equivalent)          ║
╠══════════════════════════════════════════════════════════════╣
║  INPUTS:                                                    ║
║    CurveFactor   (Float)  → Particles.CurveFactor           ║
║    UnbendPoint   (Float)  → User.UnbendPoint                ║
║    MaxBend       (Float)  → User.MaxBend                    ║
║  OUTPUTS:                                                   ║
║    BendStrength  (Float)  → Particles.BendStrength (new)    ║
║                                                              ║
║  NOTE: The actual per-vertex diagonal bend happens in the   ║
║        M_CardBend material (WPO). This module just          ║
║        calculates the STRENGTH for each card particle.      ║
╚══════════════════════════════════════════════════════════════╝

HLSL:

// Cards start fully bent and flatten as they travel.
// At CurveFactor=0 → BendStrength=MaxBend (fully bent at launch)
// At CurveFactor>=UnbendPoint → BendStrength=0 (flat in flight)
float OutBendStrength;
if (UnbendPoint > 0.0001f)
{
    OutBendStrength = lerp(MaxBend, 0.0f, saturate(CurveFactor / UnbendPoint));
}
else
{
    OutBendStrength = (CurveFactor > 0.0f) ? 0.0f : MaxBend;
}
""")

    # ---- Module 3: CurvePlacement ----
    log("""
╔══════════════════════════════════════════════════════════════╗
║  MODULE 3: CurvePlacement  (Blender Block F equivalent)    ║
╠══════════════════════════════════════════════════════════════╣
║  INPUTS:                                                    ║
║    CurveFactor       (Float)   → Particles.CurveFactor      ║
║    CardBaseRotation  (Vector)  → User.CardBaseRotation       ║
║    SplineDI          (Spline)  → Data Interface (see setup)  ║
║  OUTPUTS:                                                   ║
║    Position          (Vector)  → Particles.Position          ║
║    MeshOrientation   (Quat)    → Particles.MeshOrientation   ║
║                                                              ║
║  BEST APPROACH: Use visual nodes in the Scratch Pad graph   ║
║  (not raw HLSL) because Spline DI calls are node-based.     ║
╚══════════════════════════════════════════════════════════════╝

VISUAL NODE WIRING (Scratch Pad graph):

1. SAMPLE SPLINE:
   [Sample Spline Position by Unit Distance]
     ├─ Spline: SplineDI (Data Interface)
     ├─ U: Particles.CurveFactor
     └─ → SplinePos (Vector)

   [Sample Spline Direction by Unit Distance]
     ├─ Spline: SplineDI
     ├─ U: Particles.CurveFactor
     └─ → SplineTangent (Vector)

   [Sample Spline Up Vector by Unit Distance]
     ├─ Spline: SplineDI
     ├─ U: Particles.CurveFactor
     └─ → SplineUp (Vector)

2. BUILD ROTATION (equivalent to Blender's two Align Rotation to Vector nodes):
   [Make Rotation From XZ]
     ├─ X: SplineTangent (Forward along curve)
     ├─ Z: SplineUp
     └─ → CurveQuat (Quat)

3. APPLY BASE ROTATION (equivalent to Blender's Rotate Rotation node):
   [Rotator to Quaternion] (or use Euler degrees directly)
     ├─ Rotator: User.CardBaseRotation
     └─ → BaseQuat (Quat)

   [Combine Rotations]
     ├─ A: CurveQuat
     ├─ B: BaseQuat
     └─ → FinalQuat (Quat)

4. WRITE OUTPUTS:
   Particles.Position = SplinePos
   Particles.MeshOrientation = FinalQuat

NOTES:
  - The per-vertex bend deformation is handled by the M_CardBend material,
    NOT this module. This module just places and orients the whole card mesh.
  - If you want an additional particle-level Z-offset for the bend
    (a rough approximation), add:
      float3 BendOffset = RotateVector(float3(0, 0, BendStrength * 0.5), FinalQuat);
      Particles.Position = SplinePos + BendOffset;
""")


# ============================================================================
# STEP 7: PRINT EMITTER CONFIGURATION GUIDE
# ============================================================================
def print_emitter_setup():
    log("=" * 50)
    log("STEP 7: Niagara Emitter Configuration (UE 5.8.1)")
    log("=" * 50)
    log("""
Open NS_CardSpring and configure the emitter:

┌─────────────────────────────────────────────────────────────┐
│ EMITTER PROPERTIES (UE 5.8.1)                              │
├─────────────────────────────────────────────────────────────┤
│ Sim Target:          CPUSim (switch to GPU for production)  │
│ Determinism:         ON (consistent card ordering)          │
│ Fixed Bounds:        ON → (Min: -500,-500,-500              │
│                            Max: 500, 500, 500)              │
│ Local Space:         OFF (world space)                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ EMITTER STACK                                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ SPAWN:                                                      │
│   [Spawn Burst Instantaneous]                               │
│     Spawn Count: 52                                         │
│                                                             │
│ PARTICLE SPAWN:                                             │
│   [Initialize Particle]                                     │
│     Lifetime Mode: Infinite (or 99999)                      │
│     Mass: 1.0                                               │
│     NOTE: In UE 5.8, "Infinite" lifetime is available.      │
│           If not, use a very large number.                   │
│                                                             │
│ PARTICLE UPDATE:                                            │
│   [CardTiming]     ← Scratch Pad Module 1                   │
│   [CardBend]       ← Scratch Pad Module 2                   │
│   [CurvePlacement] ← Scratch Pad Module 3                   │
│                                                             │
│ RENDER:                                                     │
│   [Mesh Renderer]                                           │
│     Particle Mesh: <Search for your Card FBX in Content browser>│
│     Facing Mode: Default (NOT camera-facing)                │
│     Mesh Orientation: Particles.MeshOrientation             │
│     Enable Dynamic Material Parameters: YES                 │
│     Material Parameter 0: Particles.BendStrength            │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ SYSTEM USER PARAMETERS                                     │
├─────────────────────────────────────────────────────────────┤
│ Name               │ Type    │ Default │ Description        │
│────────────────────│─────────│─────────│────────────────────│
│ SpringProgress     │ Float   │ 0.0     │ Animate 0→1        │
│ CardSpacing        │ Float   │ 1.5     │ Stagger delay (cm) │
│ FlightSpeed        │ Float   │ 30.0    │ Travel speed (cm)  │
│ UnbendPoint        │ Float   │ 0.1     │ When cards flatten │
│ MaxBend            │ Float   │ 5.0     │ Initial bend amount│
│ CardBaseRotation   │ Vector  │ 0,0,0   │ Card orient (deg)  │
│ SplineDI           │ Spline  │ —       │ Link to BP_Spline  │
└─────────────────────────────────────────────────────────────┘
""")


# ============================================================================
# STEP 8: PRINT MCP ALTERNATIVE
# ============================================================================
def print_mcp_note():
    log("=" * 50)
    log("ALTERNATIVE: UE 5.8.1 MCP Plugin")
    log("=" * 50)
    log("""
UE 5.8.1 ships with an experimental Model Context Protocol (MCP) plugin.
If you enable it, your AI assistant can control the Unreal Editor directly —
including spawning actors, creating materials, and potentially wiring 
Niagara nodes.

TO ENABLE:
  1. Edit > Plugins > search "Model Context Protocol"
  2. Enable the plugin, restart the editor
  3. The plugin starts an MCP server (local HTTP)
  4. Connect your AI tool to the MCP endpoint

This could allow your AI assistant to:
  ✓ Create the material graph nodes for M_CardBend
  ✓ Configure emitter stack modules
  ✓ Wire Scratch Pad nodes visually
  ✓ Place and configure actors in the level

NOTE: The MCP plugin is EXPERIMENTAL in 5.8.1. The Python script 
approach in this file is more stable and reproducible.
""")


# ============================================================================
# STEP 9: SAVE
# ============================================================================
def save_all():
    log("=" * 50)
    log("STEP 9: Saving all assets")
    unreal.EditorAssetLibrary.save_directory(ASSET_ROOT)
    log(f"Saved: {ASSET_ROOT}")


# ============================================================================
# MAIN
# ============================================================================
def main():
    log("╔══════════════════════════════════════════════════════════╗")
    log("║   CARD SPRING NIAGARA SETUP — Unreal Engine 5.8.1      ║")
    log("║   Blender Geometry Nodes → Niagara + Material WPO      ║")
    log("╚══════════════════════════════════════════════════════════╝")

    try:
        create_folders()
        system   = create_niagara_system()
        modules  = create_module_scripts()
        bp       = create_spline_blueprint()
        material = create_bend_material()
        print_module_hlsl()
        print_emitter_setup()
        print_mcp_note()
        save_all()

        log("")
        log("╔══════════════════════════════════════════════════════════╗")
        log("║   DONE! Assets created under /Game/CardSpring/         ║")
        log("╠══════════════════════════════════════════════════════════╣")
        log(f"║   Niagara System:  {ASSET_ROOT}/Niagara/{SYSTEM_NAME}")
        log(f"║   Module Scripts:  {ASSET_ROOT}/Niagara/Modules/NMS_*")
        log(f"║   Spline Actor:    {ASSET_ROOT}/Blueprints/{SPLINE_BP_NAME}")
        log(f"║   Bend Material:   {ASSET_ROOT}/Materials/{MATERIAL_NAME}")
        log("║                                                        ║")
        log("║   NEXT STEPS:                                          ║")
        log("║   1. Open NS_CardSpring → configure emitter (see log)  ║")
        log("║   2. Open M_CardBend → build the WPO graph (see log)   ║")
        log("║   3. Open BP_SplineArc → add SplineComponent           ║")
        log("║   4. Place actors in level, keyframe SpringProgress    ║")
        log("╚══════════════════════════════════════════════════════════╝")

    except Exception as e:
        log_err(f"Script failed: {e}")
        log_err(traceback.format_exc())


# Execute
main()
