"""Step 3 — materials for Sea of Probabilities (runs inside UnrealEditor-Cmd).

MPC_Sea (game thread writes T each frame + the tweakables), three die materials
sharing one WPO Custom node (rotation about UE +Y by theta, wave + horizon
height, yOffset), and two post-process materials (linear fog, vignette).
Per-instance custom data: [0]=theta [1]=yOffset [2]=glow [3]=hue [4]=x3 [5]=z3.
"""
import os

import unreal

ROOT = "/Game/SeaOfProbabilities"
MPC_PATH = ROOT + "/MPC_Sea"
mel = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary


def enum_member(enum_cls, *candidates, contains=None):
    """UE's Python enum spellings vary (MP_CUSTOM_DATA0 vs MP_CUSTOMDATA0...);
    try exact candidates, then any member whose name contains `contains`."""
    for c in candidates:
        if hasattr(enum_cls, c):
            return getattr(enum_cls, c)
    if contains:
        for n in dir(enum_cls):
            if contains in n.upper():
                return getattr(enum_cls, n)
    raise AttributeError("%s has none of %s (contains %r); members: %s"
                         % (enum_cls.__name__, candidates, contains,
                            [n for n in dir(enum_cls) if n[0].isupper()][:40]))


MP = unreal.MaterialProperty
MP_CLEARCOAT = lambda: enum_member(MP, "MP_CUSTOM_DATA0", "MP_CUSTOMDATA0", contains="CUSTOM_DATA0")   # noqa: E731
MP_CLEARCOAT_ROUGH = lambda: enum_member(MP, "MP_CUSTOM_DATA1", "MP_CUSTOMDATA1", contains="CUSTOM_DATA1")  # noqa: E731


def srgb_to_linear(hexstr):
    h = hexstr.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return unreal.LinearColor(out[0], out[1], out[2], 1.0)


MPC_SCALARS = [("T", 0.0), ("WaveAmp", 7.0), ("WaveScale", 0.018), ("HorizonR", 1010.0), ("ZFront", 59.4),
               ("GlowStrength", 4.0), ("Vignette", 0.45), ("FogNear", 24.0), ("FogFar", 95.0), ("RedAce", 0.0),
               # grid geometry for the wave texture <-> die mapping (pushed by the actor)
               ("Cols", 116.0), ("Rows", 100.0), ("Spacing", 1.2), ("W", 138.0), ("D", 118.8)]
MPC_VECTORS = [("GlowColorA", srgb_to_linear("#0080ff")), ("GlowColorB", srgb_to_linear("#ff0066")),
               ("DiceColor", srgb_to_linear("#000000")), ("BgColor", srgb_to_linear("#242424")),
               ("PipColor", srgb_to_linear("#17171d")), ("AceColor", srgb_to_linear("#c73535"))]


def build_mpc():
    if EAL.does_asset_exist(MPC_PATH):
        mpc = EAL.load_asset(MPC_PATH)
    else:
        mpc = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "MPC_Sea", ROOT, unreal.MaterialParameterCollection, unreal.MaterialParameterCollectionFactoryNew())
    sc = []
    for n, v in MPC_SCALARS:
        p = unreal.CollectionScalarParameter()
        p.set_editor_property("parameter_name", n)
        p.set_editor_property("default_value", float(v))
        sc.append(p)
    vc = []
    for n, v in MPC_VECTORS:
        p = unreal.CollectionVectorParameter()
        p.set_editor_property("parameter_name", n)
        p.set_editor_property("default_value", v)
        vc.append(p)
    mpc.set_editor_property("scalar_parameters", sc)
    mpc.set_editor_property("vector_parameters", vc)
    EAL.save_asset(MPC_PATH)
    return mpc


class MatBuilder:
    def __init__(self, name, domain=None):
        self.full = ROOT + "/" + name
        if EAL.does_asset_exist(self.full):
            self.mat = EAL.load_asset(self.full)
            mel.delete_all_material_expressions(self.mat)
        else:
            self.mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                name, ROOT, unreal.Material, unreal.MaterialFactoryNew())
        if domain is not None:
            self.mat.set_editor_property("material_domain", domain)
        self.y = 0

    def ex(self, cls, x=0, y=None):
        if y is None:
            self.y += 160
            y = self.y
        return mel.create_material_expression(self.mat, cls, x, y)

    def link(self, a, b, b_in, a_out=""):
        if not mel.connect_material_expressions(a, a_out, b, b_in):
            raise RuntimeError("link %s -> %s.%s failed" % (type(a).__name__, type(b).__name__, b_in))

    def out(self, node, prop, a_out=""):
        mel.connect_material_property(node, a_out, prop)

    def const(self, v):
        n = self.ex(unreal.MaterialExpressionConstant, -900)
        n.set_editor_property("r", float(v))
        return n

    def const3(self, c):
        n = self.ex(unreal.MaterialExpressionConstant3Vector, -900)
        n.set_editor_property("constant", c)
        return n

    def mpc(self, mpc, pname):
        n = self.ex(unreal.MaterialExpressionCollectionParameter, -900)
        n.set_editor_property("collection", mpc)
        n.set_editor_property("parameter_name", pname)
        return n

    def custom_data(self, idx):
        n = self.ex(unreal.MaterialExpressionPerInstanceCustomData, -900)
        n.set_editor_property("data_index", int(idx))
        return n

    def custom(self, code, inputs, out_type, x=-300):
        n = self.ex(unreal.MaterialExpressionCustom, x)
        n.set_editor_property("code", code)
        n.set_editor_property("output_type", out_type)
        ins = []
        for name in inputs:
            ci = unreal.CustomInput()
            ci.set_editor_property("input_name", name)
            ins.append(ci)
        n.set_editor_property("inputs", ins)
        return n

    def local_pos(self):
        """Vertex position relative to the INSTANCE pivot (float, LWC-safe) —
        same pattern as the GNue dynamics material."""
        lp_cls = getattr(unreal, "MaterialExpressionLocalPosition", None)
        if lp_cls is not None:
            n = self.ex(lp_cls, -900)
            try:
                n.set_editor_property("local_origin", unreal.MaterialLocalPositionOrigin.INSTANCE)
            except Exception:
                pass
            return n
        wp = self.ex(unreal.MaterialExpressionWorldPosition, -1100)
        n = self.ex(unreal.MaterialExpressionTransformPosition, -900)
        n.set_editor_property("transform_source_type", unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_WORLD)
        n.set_editor_property("transform_type", unreal.MaterialPositionTransformSource.TRANSFORMPOSSOURCE_INSTANCE)
        self.link(wp, n, "")
        return n

    def finish(self):
        mel.recompile_material(self.mat)
        EAL.save_asset(self.full)
        return self.mat


UV_CODE = ("float ix = round((x + W * 0.5) / spacing), iz = round((z + D * 0.5) / spacing);\n"
           "return float2((ix + 0.5) / cols, (iz + 0.5) / rows);\n")
UV_INPUTS = ["x", "z", "cols", "rows", "spacing", "W", "D"]


def wpo_code(show_dir):
    """Die WPO Custom node: inputs P, uv, WaveTex, StateTex -> float3 offset (cm).

    Everything dynamic comes from two Cols x Rows textures sampled at the die's texel:
    WaveRT (GPU-drawn: wave + horizon height) and StateRT (CPU-uploaded: theta, yOffset,
    glow, hue). The ISM instance buffer holds only the die's grid position and is never
    dirtied after the build - any dirty instance makes UE re-upload the whole buffer
    (~58 ms at 262k), which was the last frame-rate ceiling."""
    return ("float4 st = Texture2DSampleLevel(StateTex, StateTexSampler, uv, 0);   // theta, yOff, glow, hue\n"
            "float theta = st.r, yOff = st.g;\n"
            "// spin about UE +Y (three +X) around the instance pivot. Sign derived from the\n"
            "// web build's R_x(+theta): the die's top rolls toward three +Z = UE -X, so the\n"
            "// top face cycles 1 -> 5 -> 6 -> 2 with positive theta (theta = pi shows 6 up).\n"
            "float c = cos(theta), s = sin(theta);\n"
            "float3 r = float3(P.x * c - P.z * s, P.y, P.x * s + P.z * c);\n"
            "// WaveRT stores 1 + h/1024 (see wave_code: emissive is clamped at 0 and most heights\n"
            "// are negative); the unbound default (white) therefore decodes to h = 0.\n"
            "float h = (Texture2DSampleLevel(WaveTex, WaveTexSampler, uv, 0).r - 1.0) * 1024.0;\n"
            "return (r - P) + float3(0, 0, (h + yOff) * 100.0);\n")


WPO_INPUTS = ["P", "uv", "WaveTex", "StateTex"]


def wave_code(show_dir):
    """M_Wave Custom node (UI domain, drawn to WaveRT every frame): for texel uv, the die at
    (ix, iz) -> its three-frame (x, z) -> two-octave simplex wave (spec 4.2, generated
    bit-exact body) minus the horizon term. Output: height in three units (R32F)."""
    with open(os.path.join(show_dir, "noise", "SeaNoise_wave.hlsl"), "r", encoding="utf-8") as f:
        wave = f.read()
    ret = "return amp * (0.75 * nA + 0.25 * nB);"
    assert ret in wave, "generated HLSL changed shape"
    wave = wave.replace(ret, "float wave = amp * (0.75 * nA + 0.25 * nB);")
    return ("float ix = floor(uv.x * cols), iz = floor(uv.y * rows);\n"
            "float x = -W * 0.5 + ix * spacing, z = -D * 0.5 + iz * spacing;\n"
            + wave + "\n"
            "float dz = z - zFront;\n"
            # The UI-domain pixel shader clamps emissive at 0 (GetMaterialEmissive) and the horizon
            # term makes most heights negative -> the field rendered flat. Encode 1 + h/1024
            # (R32F keeps ~1e-4 three-units of precision there); the die WPO decodes it.
            "return 1.0 + (wave - (x * x + dz * dz) / horizonR) / 1024.0;\n")


WAVE_INPUTS = ["uv", "t", "f", "amp", "horizonR", "zFront", "cols", "rows", "spacing", "W", "D"]


def add_die_common(b, mpc, show_dir):
    """Clear-coat surface + the shared WPO, routed through Make Material
    Attributes (the Python MaterialProperty enum has no clear-coat pins).
    Returns (attrs, state): the attributes node and the pixel-shader StateRT sample
    (outputs: B = glow, A = hue) for callers that colour the pips."""
    b.mat.set_editor_property("shading_model",
                              enum_member(unreal.MaterialShadingModel, "MSM_CLEAR_COAT", "MSM_CLEARCOAT", contains="CLEAR"))
    b.mat.set_editor_property("used_with_instanced_static_meshes", True)
    b.mat.set_editor_property("use_material_attributes", True)
    attrs = b.ex(unreal.MaterialExpressionMakeMaterialAttributes, 300, 0)
    b.link(b.const(1.0), attrs, "Metallic")
    b.link(b.const(0.71), attrs, "Roughness")
    b.link(b.const(0.09), attrs, "ClearCoat")
    b.link(b.const(0.29), attrs, "ClearCoatRoughness")
    black = EAL.load_asset("/Engine/EngineResources/Black")
    # the die's texel in both Cols x Rows textures, from its (static) grid position
    uv = b.custom(UV_CODE, UV_INPUTS, unreal.CustomMaterialOutputType.CMOT_FLOAT2, x=-600)
    b.link(b.custom_data(4), uv, "x")
    b.link(b.custom_data(5), uv, "z")
    for pin, pname in (("cols", "Cols"), ("rows", "Rows"), ("spacing", "Spacing"), ("W", "W"), ("D", "D")):
        b.link(b.mpc(mpc, pname), uv, pin)
    wpo = b.custom(wpo_code(show_dir), WPO_INPUTS, unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    b.link(b.local_pos(), wpo, "P")
    b.link(uv, wpo, "uv")
    white = EAL.load_asset("/Engine/EngineResources/WhiteSquareTexture")   # decodes to h = 0 when unbound
    for pname, pin, default in (("WaveRT", "WaveTex", white), ("StateRT", "StateTex", black)):
        tex = b.ex(unreal.MaterialExpressionTextureObjectParameter, -900)
        tex.set_editor_property("parameter_name", pname)
        tex.set_editor_property("texture", default)
        b.link(tex, wpo, pin)
    b.link(wpo, attrs, "WorldPositionOffset")
    # pixel-shader read of the state (float4: theta, yOff, glow, hue) for the pip colour.
    # A Custom node, not a TextureSampleParameter2D: the latter validates its sampler type
    # against the (sRGB) default texture and fails to compile for a linear RGBA32F target.
    state = b.custom("return Texture2DSampleLevel(StateTex, StateTexSampler, uv, 0);",
                     ["uv", "StateTex"], unreal.CustomMaterialOutputType.CMOT_FLOAT4, x=-600)
    b.link(uv, state, "uv")
    tex2 = b.ex(unreal.MaterialExpressionTextureObjectParameter, -900)
    tex2.set_editor_property("parameter_name", "StateRT")
    tex2.set_editor_property("texture", black)
    b.link(tex2, state, "StateTex")
    b.out(attrs, MP.MP_MATERIAL_ATTRIBUTES)
    return attrs, state


PIP_BASE = ("float glow = st.b, hue = st.a;\n"
            "float3 neon = lerp(A, B, hue);\n"
            "return lerp(pipCol * diceCol, neon * 0.35, glow);\n")
PIP_EMIS = ("float glow = st.b, hue = st.a;\n"
            "float3 neon = lerp(A, B, hue);\n"
            "return neon * glow * strength;\n")


def build_pip_material(name, mpc, show_dir, ace):
    b = MatBuilder(name)
    attrs, state = add_die_common(b, mpc, show_dir)
    if ace:
        # pipCol = lerp(PipColor, AceColor, RedAce)
        mix = b.custom("return lerp(pip, ace, redAce);", ["pip", "ace", "redAce"],
                       unreal.CustomMaterialOutputType.CMOT_FLOAT3, x=-600)
        b.link(b.mpc(mpc, "PipColor"), mix, "pip")
        b.link(b.mpc(mpc, "AceColor"), mix, "ace")
        b.link(b.mpc(mpc, "RedAce"), mix, "redAce")
        pipcol = mix
    else:
        pipcol = b.mpc(mpc, "PipColor")
    base = b.custom(PIP_BASE, ["A", "B", "st", "pipCol", "diceCol"], unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    emis = b.custom(PIP_EMIS, ["A", "B", "st", "strength"], unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ca, cb = b.mpc(mpc, "GlowColorA"), b.mpc(mpc, "GlowColorB")
    for n in (base, emis):
        b.link(ca, n, "A"); b.link(cb, n, "B")
        b.link(state, n, "st")            # StateRT texel: (theta, yOff, glow, hue)
    b.link(pipcol, base, "pipCol")
    b.link(b.mpc(mpc, "DiceColor"), base, "diceCol")
    b.link(b.mpc(mpc, "GlowStrength"), emis, "strength")
    b.link(base, attrs, "BaseColor")
    b.link(emis, attrs, "EmissiveColor")
    return b.finish()


def build_body_material(mpc, show_dir):
    b = MatBuilder("M_DieBody")
    attrs, _state = add_die_common(b, mpc, show_dir)
    b.link(b.mpc(mpc, "DiceColor"), attrs, "BaseColor")
    return b.finish()


def build_wave_material(mpc, show_dir):
    """M_Wave: UI-domain material drawn into WaveRT (one texel per die) every frame."""
    b = MatBuilder("M_Wave", unreal.MaterialDomain.MD_UI)
    b.mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
    node = b.custom(wave_code(show_dir), WAVE_INPUTS, unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    uv = b.ex(unreal.MaterialExpressionTextureCoordinate, -900)
    b.link(uv, node, "uv")
    for pin, pname in (("t", "T"), ("f", "WaveScale"), ("amp", "WaveAmp"), ("horizonR", "HorizonR"), ("zFront", "ZFront"),
                       ("cols", "Cols"), ("rows", "Rows"), ("spacing", "Spacing"), ("W", "W"), ("D", "D")):
        b.link(b.mpc(mpc, pname), node, pin)
    b.out(node, MP.MP_EMISSIVE_COLOR)      # UI domain: Final Color
    return b.finish()


def build_post_fog(mpc):
    b = MatBuilder("M_PP_Fog", unreal.MaterialDomain.MD_POST_PROCESS)
    b.mat.set_editor_property("blendable_location",
                              enum_member(unreal.BlendableLocation, "BL_SCENE_COLOR_BEFORE_BLOOM", contains="BEFORE_BLOOM"))
    col = b.ex(unreal.MaterialExpressionSceneTexture, -900)
    col.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    dep = b.ex(unreal.MaterialExpressionSceneTexture, -900)
    dep.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_SCENE_DEPTH)
    fog = b.custom("float d = depth.r / 100.0;\n"                       # planar depth -> three units
                   "return lerp(col.rgb, bg, saturate((d - near) / (far - near)));\n",
                   ["col", "depth", "near", "far", "bg"], unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    b.link(col, fog, "col", "Color")
    b.link(dep, fog, "depth", "Color")
    b.link(b.mpc(mpc, "FogNear"), fog, "near")
    b.link(b.mpc(mpc, "FogFar"), fog, "far")
    b.link(b.mpc(mpc, "BgColor"), fog, "bg")
    b.out(fog, unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return b.finish()


def build_post_vignette(mpc):
    b = MatBuilder("M_PP_Vignette", unreal.MaterialDomain.MD_POST_PROCESS)
    b.mat.set_editor_property("blendable_location",
                              enum_member(unreal.BlendableLocation, "BL_SCENE_COLOR_AFTER_TONEMAPPING", contains="AFTER_TONEMAPPING"))
    col = b.ex(unreal.MaterialExpressionSceneTexture, -900)
    col.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    uv = b.ex(unreal.MaterialExpressionScreenPosition, -900)
    vig = b.custom("float d = distance(uv.xy, float2(0.5, 0.5));\n"
                   "float v = 1.0 - smoothstep(0.3, 0.85, d);\n"        # == smoothstep(0.85, 0.3, d)
                   "return col.rgb * lerp(1.0, v, amount);\n",
                   ["col", "uv", "amount"], unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    b.link(col, vig, "col", "Color")
    b.link(uv, vig, "uv")
    b.link(b.mpc(mpc, "Vignette"), vig, "amount")
    b.out(vig, unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    return b.finish()


def build_all(show_dir, mesh_path):
    mpc = build_mpc()
    body = build_body_material(mpc, show_dir)
    pips = build_pip_material("M_DiePips", mpc, show_dir, ace=False)
    ace = build_pip_material("M_DieAce", mpc, show_dir, ace=True)
    wave = build_wave_material(mpc, show_dir)
    fog = build_post_fog(mpc)
    vig = build_post_vignette(mpc)
    # assign to the die's three slots
    sm = EAL.load_asset(mesh_path)
    mats = list(sm.static_materials)
    by_slot = {str(m.material_slot_name): i for i, m in enumerate(mats)}
    for slot, mat in (("M_DieBody", body), ("M_DiePips", pips), ("M_DieAce", ace)):
        i = by_slot.get(slot)
        if i is None:
            return False, "mesh has no slot %s (slots: %s)" % (slot, list(by_slot))
        sm.set_material(i, mat)
    EAL.save_asset(mesh_path)
    built = [m.get_name() for m in (body, pips, ace, wave, fog, vig)]
    return True, "mpc=%s materials=%s slots=%s" % (mpc.get_name(), built, by_slot)
