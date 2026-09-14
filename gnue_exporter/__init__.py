"""GN->UE exporter — Blender extension package.

core.py is bpy-free; frontend_bpy.py and the UI below need Blender.
"""

bl_info = {
    "name": "GN to UE Exporter",
    "author": "GNtoUE research",
    # legacy field (extensions read blender_manifest.toml); keep it equal to the
    # manifest's version — tools/make_deliverables.py refuses to package on drift
    "version": (0, 7, 0),
    "blender": (4, 2, 0),
    "location": "3D View & Node Editor sidebar (N) > GN to UE",
    "description": "Export V1-core Geometry Nodes effects to a UE-importable descriptor folder",
    "category": "Import-Export",
}

try:
    import bpy
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False

if _HAS_BPY:
    from . import frontend_bpy

    def _gn_groups_on(obj):
        out = []
        if obj:
            for m in obj.modifiers:
                if m.type == "NODES" and m.node_group:
                    out.append(m.node_group)
        return out

    def _group_items(self, context):
        items = []
        seen = set()
        for ngr in _gn_groups_on(context.active_object):
            items.append((ngr.name, ngr.name, "On active object"))
            seen.add(ngr.name)
        for ngr in bpy.data.node_groups:
            if ngr.bl_idname == "GeometryNodeTree" and ngr.name not in seen:
                items.append((ngr.name, ngr.name, ""))
        return items or [("", "<no geometry node groups>", "")]

    class GNUESettings(bpy.types.PropertyGroup):
        export_dir: bpy.props.StringProperty(
            name="Export Folder", subtype="DIR_PATH", default="//gnue_export/",
            description="Folder that will receive effect.gnue.json, meshes/ and the report")
        node_group: bpy.props.EnumProperty(name="Node Group", items=_group_items)

    class GNUE_OT_validate(bpy.types.Operator):
        bl_idname = "gnue.validate"
        bl_label = "Validate (V1 check)"
        bl_description = "Check the node group against the V1 core set without writing files"

        def execute(self, context):
            from . import core
            s = context.scene.gnue
            ng = bpy.data.node_groups.get(s.node_group)
            if ng is None:
                self.report({"ERROR"}, "Pick a geometry node group")
                return {"CANCELLED"}
            sess = core.Session()
            ir = frontend_bpy.read_group(ng)
            try:
                core.lower(ir, sess)
            except core.ExportRefused:
                for e in sess.errors[:8]:
                    self.report({"ERROR"}, e)
                self.report({"ERROR"}, "%d problem(s) — not translatable yet" % len(sess.errors))
                return {"CANCELLED"}
            self.report({"INFO"}, "V1-clean: translatable (%d warnings)" % len(sess.warnings))
            for w in sess.warnings[:5]:
                self.report({"WARNING"}, w)
            return {"FINISHED"}

    class GNUE_OT_export(bpy.types.Operator):
        bl_idname = "gnue.export"
        bl_label = "Export for Unreal"
        bl_description = "Write descriptor + baked meshes + report to the export folder"

        def execute(self, context):
            s = context.scene.gnue
            ng = bpy.data.node_groups.get(s.node_group)
            if ng is None:
                self.report({"ERROR"}, "Pick a geometry node group")
                return {"CANCELLED"}
            out_dir = bpy.path.abspath(s.export_dir)
            if not out_dir:
                self.report({"ERROR"}, "Pick an export folder")
                return {"CANCELLED"}
            ok, report, _ = frontend_bpy.export_group(ng, out_dir)
            txt = bpy.data.texts.get("gnue_report") or bpy.data.texts.new("gnue_report")
            txt.clear()
            txt.write(report)
            if not ok:
                self.report({"ERROR"}, "Export refused — see 'gnue_report' text block")
                return {"CANCELLED"}
            self.report({"INFO"}, "Exported to %s" % out_dir)
            return {"FINISHED"}

    class _PanelMixin:
        bl_label = "GN to UE"
        bl_region_type = "UI"
        bl_category = "GN to UE"

        def draw(self, context):
            s = context.scene.gnue
            col = self.layout.column()
            col.prop(s, "node_group")
            col.prop(s, "export_dir")
            row = col.row(align=True)
            row.operator("gnue.validate", icon="CHECKMARK")
            row.operator("gnue.export", icon="EXPORT")

    class GNUE_PT_view3d(_PanelMixin, bpy.types.Panel):
        bl_idname = "GNUE_PT_view3d"
        bl_space_type = "VIEW_3D"

    class GNUE_PT_node(_PanelMixin, bpy.types.Panel):
        bl_idname = "GNUE_PT_node"
        bl_space_type = "NODE_EDITOR"

    _CLASSES = (GNUESettings, GNUE_OT_validate, GNUE_OT_export, GNUE_PT_view3d, GNUE_PT_node)

    def register():
        for c in _CLASSES:
            bpy.utils.register_class(c)
        bpy.types.Scene.gnue = bpy.props.PointerProperty(type=GNUESettings)

    def unregister():
        del bpy.types.Scene.gnue
        for c in reversed(_CLASSES):
            bpy.utils.unregister_class(c)
