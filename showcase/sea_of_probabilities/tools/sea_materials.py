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
               ("GlowStrength", 4.0), ("Vignette", 0.45), ("FogNear", 24.0), ("FogFar", 95.0), ("RedAce", 0.0)]
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


def wpo_code(show_dir):
    """Custom node body: inputs P, theta, yOff, x, z, t, f, amp, horizonR, zFront -> float3 offset (cm)."""
    with open(os.path.join(show_dir, "noise", "SeaNoise_wave.hlsl"), "r", encoding="utf-8") as f:
        wave = f.read()
    ret = "return amp * (0.75 * nA + 0.25 * nB);"
    assert ret in wave, "generated HLSL changed shape"
    wave = wave.replace(ret, "float wave = amp * (0.75 * nA + 0.25 * nB);")
    return (wave + "\n"
            "// spin about UE +Y (three +X) around the instance pivot. Sign derived from the\n"
            "// web build's R_x(+theta): the die's top rolls toward three +Z = UE -X, so the\n"
            "// top face cycles 1 -> 5 -> 6 -> 2 with positive theta (theta = pi shows 6 up).\n"
            "float c = cos(theta), s = sin(theta);\n"
            "float3 r = float3(P.x * c - P.z * s, P.y, P.x * s + P.z * c);\n"
            "float dz = z - zFront;\n"
            "float height = wave - (x * x + dz * dz) / horizonR;\n"
            "return (r - P) + float3(0, 0, (height + yOff) * 100.0);\n")


WPO_INPUTS = ["P", "theta", "yOff", "x", "z", "t", "f", "amp", "horizonR", "zFront"]


def add_die_common(b, mpc, show_dir):
    """Clear-coat surface + the shared WPO, routed through Make Material
    Attributes (the Python MaterialProperty enum has no clear-coat pins).
    Returns the attributes node; callers plug BaseColor / EmissiveColor into it."""
    b.mat.set_editor_property("shading_model",
                              enum_member(unreal.MaterialShadingModel, "MSM_CLEAR_COAT", "MSM_CLEARCOAT", contains="CLEAR"))
    b.mat.set_editor_property("used_with_instanced_static_meshes", True)
    b.mat.set_editor_property("use_material_attributes", True)
    attrs = b.ex(unreal.MaterialExpressionMakeMaterialAttributes, 300, 0)
    b.link(b.const(1.0), attrs, "Metallic")
    b.link(b.const(0.71), attrs, "Roughness")
    b.link(b.const(0.09), attrs, "ClearCoat")
    b.link(b.const(0.29), attrs, "ClearCoatRoughness")
    wpo = b.custom(wpo_code(show_dir), WPO_INPUTS, unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    b.link(b.local_pos(), wpo, "P")
    b.link(b.custom_data(0), wpo, "theta")
    b.link(b.custom_data(1), wpo, "yOff")
    b.link(b.custom_data(4), wpo, "x")
    b.link(b.custom_data(5), wpo, "z")
    for pin, pname in (("t", "T"), ("f", "WaveScale"), ("amp", "WaveAmp"), ("horizonR", "HorizonR"), ("zFront", "ZFront")):
        b.link(b.mpc(mpc, pname), wpo, pin)
    b.link(wpo, attrs, "WorldPositionOffset")
    b.out(attrs, MP.MP_MATERIAL_ATTRIBUTES)
    return attrs


PIP_BASE = ("float3 neon = lerp(A, B, hue);\n"
            "return lerp(pipCol * diceCol, neon * 0.35, glow);\n")
PIP_EMIS = ("float3 neon = lerp(A, B, hue);\n"
            "return neon * glow * strength;\n")


def build_pip_material(name, mpc, show_dir, ace):
    b = MatBuilder(name)
    attrs = add_die_common(b, mpc, show_dir)
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
    base = b.custom(PIP_BASE, ["A", "B", "hue", "glow", "pipCol", "diceCol"], unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    emis = b.custom(PIP_EMIS, ["A", "B", "hue", "glow", "strength"], unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    ca, cb = b.mpc(mpc, "GlowColorA"), b.mpc(mpc, "GlowColorB")
    hue, glow = b.custom_data(3), b.custom_data(2)
    for n in (base, emis):
        b.link(ca, n, "A"); b.link(cb, n, "B"); b.link(hue, n, "hue"); b.link(glow, n, "glow")
    b.link(pipcol, base, "pipCol")
    b.link(b.mpc(mpc, "DiceColor"), base, "diceCol")
    b.link(b.mpc(mpc, "GlowStrength"), emis, "strength")
    b.link(base, attrs, "BaseColor")
    b.link(emis, attrs, "EmissiveColor")
    return b.finish()


def build_body_material(mpc, show_dir):
    b = MatBuilder("M_DieBody")
    attrs = add_die_common(b, mpc, show_dir)
    b.link(b.mpc(mpc, "DiceColor"), attrs, "BaseColor")
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
    built = [m.get_name() for m in (body, pips, ace, fog, vig)]
    return True, "mpc=%s materials=%s slots=%s" % (mpc.get_name(), built, by_slot)
