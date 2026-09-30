import importlib
import sys
from typing import Any, Dict, Set, cast

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, IntProperty, FloatVectorProperty
from bpy_extras.io_utils import ImportHelper

from .mixamo_blender_importer import OperatorReturnItems

bl_info = {
    "name": "JA Mixamo NLA Import (.fbx)",
    "author": "BE-Arbiter",
    "version": (1, 0, 0),
    "blender": (4, 1, 0),
    "location": "File > Import > JA Mixamo NLA Import (.fbx)",
    "description": "Retargets Mixamo FBX animations (binary or ASCII) onto the Jedi Academy _humanoid skeleton as NLA strips",
    "category": "Import-Export"
}

# F8 "Reload Scripts": the operator imports the submodules lazily, so reload the ones already loaded
for _name in ("fbx", "mixamo_blender_importer"):
    _module = sys.modules.get("%s.%s" % (__name__, _name))
    if _module is not None:
        importlib.reload(_module)


class ImportMixamoFBX(bpy.types.Operator, ImportHelper):  # pyright: ignore[reportIncompatibleMethodOverride]  # invoke() stubs of the two bases differ
    """Retarget a Mixamo FBX animation onto the Jedi Academy _humanoid skeleton"""
    bl_idname = "import_anim.ja_mixamo_fbx"
    bl_label = "Import Mixamo FBX as NLA Strip"
    bl_options = {"UNDO", "PRESET"}

    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})  # pyright: ignore[reportInvalidTypeForm]

    scale: FloatProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Scale",
        description="File units to armature units for the pelvis motion. 0 = automatic, from both skeletons' hip heights",
        default=0.0, min=0.0, max=1000.0
    )

    origin_offset: FloatVectorProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Origin Offset",
        description="Translation added to the whole skeleton in every frame, in Ghoul2 units. Every stock _humanoid animation has model_root at (0, 0, -24)",
        default=(0.0, 0.0, -24.0),
        subtype="TRANSLATION", size=3
    )

    in_place: BoolProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="In Place",
        description="Drop the horizontal motion of the hips (keep only the vertical one)",
        default=False
    )

    fps: IntProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="FPS",
        description="Frame rate the animation is resampled to, 0 = the file's (Mixamo: 30)",
        default=0, min=0, max=240
    )

    nla_strip: BoolProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Add as NLA Strip",
        description="Put the animation in a new NLA strip (one action per sequence, like the jediacademy addon's .gla import with animation.cfg) instead of making it the active action",
        default=True
    )

    strip_start: IntProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Strip Start",
        description="Frame where the strip starts, -1 = right after the last existing strip",
        default=-1, min=-1
    )

    sequence_name: StringProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Sequence Name",
        description="Name of the action / animation.cfg sequence (e.g. BOTH_STAND2). Several names separated by dots create one action per name, with their strips stacked at the same frames. Empty = file name",
        default=""
    )

    loop_frame: IntProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Loop Frame",
        description="animation.cfg loop frame: -1 = no loop, 0 = loop from the start",
        default=-1, min=-1
    )

    set_scene_range: BoolProperty(  # pyright: ignore[reportInvalidTypeForm]
        name="Set Scene Range && FPS",
        description="Set the scene frame range and frame rate to the animation's",
        default=True
    )

    def draw(self, context):
        from .mixamo_blender_importer import find_skeleton
        layout = self.layout
        assert layout is not None

        skeleton = find_skeleton(context)
        if skeleton is not None:
            layout.label(text="Armature: %s" % skeleton.name, icon="ARMATURE_DATA")
        else:
            layout.label(text="No skeleton_root: import _humanoid.gla first", icon="ERROR")
        layout.prop(self, "scale")
        layout.prop(self, "origin_offset")
        layout.prop(self, "in_place")
        layout.prop(self, "fps")

        box = layout.box()
        box.prop(self, "nla_strip")
        sub = box.column()
        sub.enabled = self.nla_strip
        sub.prop(self, "strip_start")
        sub.label(text="Sequence Name:")
        sub.prop(self, "sequence_name", text="")
        sub.prop(self, "loop_frame")
        layout.prop(self, "set_scene_range")

    def execute(self, context: bpy.types.Context) -> Set[OperatorReturnItems]:
        from . import mixamo_blender_importer
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        keywords = cast(Dict[str, Any], self.as_keywords(ignore=("filter_glob", "filepath")))
        return mixamo_blender_importer.load(self, context, filepath=self.filepath, **keywords)  # pyright: ignore[reportAttributeAccessIssue]  # from ImportHelper


MENU_TEXT = "JA Mixamo NLA Import (.fbx)"


def menu_func_import(self, context):
    self.layout.operator(ImportMixamoFBX.bl_idname, text=MENU_TEXT)


classes = (ImportMixamoFBX,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
