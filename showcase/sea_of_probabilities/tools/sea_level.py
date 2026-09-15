"""Step 5 — L_SeaOfProbabilities (runs inside UnrealEditor-Cmd).

New level with: the SeaOfProbabilitiesActor (assets wired, field built), the
sun (az 197 / el 34, spec 6.3), a sky light on a neutral engine cubemap, an
unbound post-process volume (manual exposure, bloom 0.6 / threshold 1, our fog
+ vignette blendables), a PlayerStart at the spec camera. Saved, then RELOADED
and re-counted, because headless spawns have silently failed to persist before.
"""
import math

import unreal

ROOT = "/Game/SeaOfProbabilities"
LEVEL = ROOT + "/L_SeaOfProbabilities"
EAL = unreal.EditorAssetLibrary


def three_to_ue(x, y, z):
    return unreal.Vector(-z * 100.0, x * 100.0, y * 100.0)


def set_props(obj, **kw):
    for k, v in kw.items():
        obj.set_editor_property(k, v)


def build(mesh_path):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    if not les.new_level(LEVEL):
        return False, "new_level failed for %s" % LEVEL

    # ---- the ocean
    sea_cls = getattr(unreal, "SeaOfProbabilitiesActor", None)
    if sea_cls is None:
        return False, "SeaOfProbabilitiesActor class not exposed (plugin not loaded/built?)"
    sea = eas.spawn_actor_from_class(sea_cls, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    sea.set_actor_label("SeaOfProbabilities")
    set_props(sea,
              die_mesh=EAL.load_asset(mesh_path),
              collection=EAL.load_asset(ROOT + "/MPC_Sea"),
              body_material=EAL.load_asset(ROOT + "/M_DieBody"),
              pips_material=EAL.load_asset(ROOT + "/M_DiePips"),
              ace_material=EAL.load_asset(ROOT + "/M_DieAce"))
    sea.rebuild_field()
    count = sea.get_editor_property("die_count")

    # ---- sun: from spherical (r 90, az 197, el 34) toward the origin, three's frame
    az, el, r = math.radians(197.0), math.radians(34.0), 90.0
    pos3 = (r * math.cos(el) * math.sin(az), r * math.sin(el), r * math.cos(el) * math.cos(az))
    pos = three_to_ue(*pos3)
    direction = (unreal.Vector(0, 0, 0) - pos)
    direction.normalize()
    sun = eas.spawn_actor_from_class(unreal.DirectionalLight, pos, direction.rotator())
    sun.set_actor_label("Sun")
    lc = sun.get_component_by_class(unreal.DirectionalLightComponent)
    set_props(lc, intensity=4.0, light_color=unreal.Color(255, 255, 255, 255), cast_shadows=True,
              mobility=unreal.ComponentMobility.MOVABLE)

    # ---- sky light: neutral engine cubemap standing in for three's RoomEnvironment
    sky = eas.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0))
    sky.set_actor_label("Sky")
    sc = sky.get_component_by_class(unreal.SkyLightComponent)
    cube = EAL.load_asset("/Engine/MapTemplates/Sky/DaylightAmbientCubemap") \
        if EAL.does_asset_exist("/Engine/MapTemplates/Sky/DaylightAmbientCubemap") else None
    set_props(sc, intensity=2.0, mobility=unreal.ComponentMobility.MOVABLE,
              lower_hemisphere_color=unreal.LinearColor(0.69, 0.69, 0.76, 1.0))
    if cube is not None:
        set_props(sc, source_type=unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP, cubemap=cube)

    # ---- post process: manual exposure ~0.52, bloom 0.6 / thr 1, our fog + vignette
    ppv = eas.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
    ppv.set_actor_label("PostFX")
    ppv.set_editor_property("unbound", True)
    s = ppv.get_editor_property("settings")
    set_props(s, override_auto_exposure_method=True, auto_exposure_method=unreal.AutoExposureMethod.AEM_MANUAL,
              override_auto_exposure_bias=True, auto_exposure_bias=math.log2(0.52) + 1.0,
              override_bloom_intensity=True, bloom_intensity=0.6,
              override_bloom_threshold=True, bloom_threshold=1.0,
              override_vignette_intensity=True, vignette_intensity=0.0)
    blend = []
    for m in ("M_PP_Fog", "M_PP_Vignette"):
        wb = unreal.WeightedBlendable()
        wb.set_editor_property("weight", 1.0)
        wb.set_editor_property("object", EAL.load_asset(ROOT + "/" + m))
        blend.append(wb)
    wbs = unreal.WeightedBlendables()
    wbs.set_editor_property("array", blend)
    s.set_editor_property("weighted_blendables", wbs)
    ppv.set_editor_property("settings", s)

    # ---- player start at the spec camera pose (the actor spawns the real camera in play)
    cam_pos, target = three_to_ue(-23.55, 27.5, 65.72), three_to_ue(2.67, -22.52, 6.29)
    look = (target - cam_pos); look.normalize()
    ps = eas.spawn_actor_from_class(unreal.PlayerStart, cam_pos, look.rotator())
    ps.set_actor_label("Start")

    if not les.save_current_level():
        return False, "save_current_level returned False"
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)

    # ---- prove it persisted: reload and count
    les.load_level(LEVEL)
    labels = sorted(a.get_actor_label() for a in eas.get_all_level_actors())
    seas = [a for a in eas.get_all_level_actors() if a.get_class().get_name() == "SeaOfProbabilitiesActor"]
    persisted = {"SeaOfProbabilities", "Sun", "Sky", "PostFX", "Start"} <= set(labels)
    reloaded_count = seas[0].get_editor_property("die_count") if seas else -1
    info = "actors=%s dice_built=%d dice_after_reload=%d" % (labels, count, reloaded_count)
    return persisted and reloaded_count == count, info
