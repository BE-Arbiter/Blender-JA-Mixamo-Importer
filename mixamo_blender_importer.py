"""Retargets a Mixamo FBX animation onto a Jedi Academy _humanoid armature, as an action / NLA strip.

Unlike a 3ds Max dotXSI, a Mixamo skeleton does not share the target's base pose: Mixamo rigs rest in
a T-pose, _humanoid.gla in an A-pose (arms ~48 degrees down, legs slightly apart). So each mapped
bone gets a rest correction C, the swing turning the target bone's rest direction onto the source
bone's rest direction, and then follows the source's world-space rotation delta:

    R_target(t) = R_source(t) @ R_source_rest^-1 @ C @ R_target_rest

Only the pelvis is positioned from the file (Hips translation, scaled by the leg length ratio);
every other bone keeps its rest offset from its (anatomical) parent. Everything is computed in the
armature's space: the Mixamo file is converted from Y-up to Z-up, which makes it face -Y like the
_humanoid skeleton the jediacademy addon imports.
"""

import os

import bpy
from typing import Literal, Set

from mathutils import Matrix, Vector, Euler, Quaternion

from . import fbx

OperatorReturnItems = Literal["RUNNING_MODAL", "CANCELLED", "FINISHED", "PASS_THROUGH", "INTERFACE"]

# _humanoid bone <- Mixamo bone (without the "mixamorig:" namespace).
# Bones not listed follow their parent rigidly (twist bones, face, tails, Motion).
BONE_MAP = (
    ("pelvis", "Hips"),
    ("lower_lumbar", "Spine"), ("upper_lumbar", "Spine1"), ("thoracic", "Spine2"),
    ("cervical", "Neck"), ("cranium", "Head"),

    ("lclavical", "LeftShoulder"), ("lhumerus", "LeftArm"), ("lradius", "LeftForeArm"), ("lhand", "LeftHand"),
    ("l_d1_j1", "LeftHandThumb1"), ("l_d1_j2", "LeftHandThumb2"),
    ("l_d2_j1", "LeftHandIndex1"), ("l_d2_j2", "LeftHandIndex2"),
    ("l_d4_j1", "LeftHandRing1"), ("l_d4_j2", "LeftHandRing2"),
    ("lhang_tag_bone", "LeftHand"),

    ("rclavical", "RightShoulder"), ("rhumerus", "RightArm"), ("rradius", "RightForeArm"), ("rhand", "RightHand"),
    ("r_d1_j1", "RightHandThumb1"), ("r_d1_j2", "RightHandThumb2"),
    ("r_d2_j1", "RightHandIndex1"), ("r_d2_j2", "RightHandIndex2"),
    ("r_d4_j1", "RightHandRing1"), ("r_d4_j2", "RightHandRing2"),
    ("rhang_tag_bone", "RightHand"),

    ("lfemurYZ", "LeftUpLeg"), ("ltibia", "LeftLeg"), ("ltalus", "LeftFoot"),
    ("rfemurYZ", "RightUpLeg"), ("rtibia", "RightLeg"), ("rtalus", "RightFoot"),
)

# Mixamo bone -> the joint its direction points to, when it isn't simply its first child
SOURCE_AIM = {
    "Hips": "Spine", "Spine2": "Neck", "Neck": "Head", "Head": "HeadTop_End",
    "LeftHand": "LeftHandMiddle1", "RightHand": "RightHandMiddle1",
    "LeftUpLeg": "LeftLeg", "RightUpLeg": "RightLeg",
    "LeftFoot": "LeftToeBase", "RightFoot": "RightToeBase",
}

# Bones whose rest correction is their hand's, so they stay rigidly attached to it (saber tags)
SAME_CORRECTION = {"lhang_tag_bone": "lhand", "rhang_tag_bone": "rhand"}

# Ghoul2 parents the fingers and hand tags to the forearm: they have to follow the hand instead
ANATOMICAL_PARENT = {
    b: ("lhand" if b.startswith("l") else "rhand")
    for b in ("l_d1_j1", "l_d1_j2", "l_d2_j1", "l_d2_j2", "l_d4_j1", "l_d4_j2", "lhang_tag_bone",
              "r_d1_j1", "r_d1_j2", "r_d2_j1", "r_d2_j2", "r_d4_j1", "r_d4_j2", "rhang_tag_bone")
}
ANATOMICAL_PARENT.update({"l_d1_j2": "l_d1_j1", "l_d2_j2": "l_d2_j1", "l_d4_j2": "l_d4_j1",
                          "r_d1_j2": "r_d1_j1", "r_d2_j2": "r_d2_j1", "r_d4_j2": "r_d4_j1"})

# Leg joints measuring both skeletons' hip height, for the automatic scale
TARGET_LEG = ("pelvis", ("ltalus", "rtalus"))
SOURCE_LEG = ("Hips", ("LeftFoot", "RightFoot"))


class MixamoError(Exception):
    pass


def find_skeleton(context):
    """The armature to animate: skeleton_root (as named by the jediacademy addon), else the
    active armature. None if the scene has neither."""
    scene_objects = context.scene.objects
    obj = scene_objects.get("skeleton_root")
    if obj is not None and obj.type == "ARMATURE":
        return obj
    obj = context.active_object
    if obj is not None and obj.type == "ARMATURE" and obj.name in scene_objects:
        return obj
    return None


def fbx_local_matrix(tr):
    """FBX local transform: T * Roff * Rp * Rpre * R * Rpost^-1 * Rp^-1 * Soff * Sp * S * Sp^-1."""
    def rot(deg, order="XYZ"):
        return Euler([d * 0.017453292519943295 for d in deg], order).to_matrix().to_4x4()

    T = Matrix.Translation(tr["translation"])
    Roff = Matrix.Translation(tr["rotation_offset"])
    Rp = Matrix.Translation(tr["rotation_pivot"])
    Rpre = rot(tr["pre_rotation"])
    R = rot(tr["rotation"], tr["rotation_order"])
    Rpost_inv = rot(tr["post_rotation"]).inverted()
    Soff = Matrix.Translation(tr["scaling_offset"])
    Sp = Matrix.Translation(tr["scaling_pivot"])
    S = Matrix.Diagonal(Vector(tr["scaling"]).to_4d())
    return T @ Roff @ Rp @ Rpre @ R @ Rpost_inv @ Rp.inverted() @ Soff @ Sp @ S @ Sp.inverted()


def axis_conversion(scene):
    """File axes -> Blender Z-up. Mixamo files are Y-up and face +Z: (x, y, z) -> (x, -z, y)."""
    if scene.up_axis == 2:
        return Matrix.Identity(4)
    return Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))


def get_fcurves(obj, action):
    """FCurve collection of `action` for `obj`, on Blender 4.4+ (slotted actions) and older."""
    anim = obj.animation_data_create()
    anim.action = action
    if not hasattr(action, "slots"):
        return action.fcurves

    slot = anim.action_slot
    if slot is None:
        slot = action.slots.new(id_type="OBJECT", name=obj.name)
        anim.action_slot = slot

    from bpy_extras import anim_utils
    ensure = getattr(anim_utils, "action_ensure_channelbag_for_slot")  # Blender 4.4+
    return ensure(action, slot).fcurves


def new_fcurve(fcurves, data_path, index, group):
    # the group keyword was renamed with slotted actions (channelbags)
    for keyword in ("group_name", "action_group"):
        try:
            return fcurves.new(data_path, index=index, **{keyword: group})
        except TypeError:
            continue
    return fcurves.new(data_path, index=index)


class Importer:
    def __init__(self, operator, context, filepath, opt):
        self.operator = operator
        self.context = context
        self.filepath = filepath
        self.opt = opt
        self.message = None
        self.warnings = []

    # -----------------------------------------------------------------------
    def run(self):
        obj = find_skeleton(self.context)
        if obj is None:
            raise MixamoError("No skeleton_root armature: import _humanoid.gla with the jediacademy addon first")

        scene = fbx.load_scene(self.filepath)
        self.read_source(scene)
        self.fps = self.opt["fps"] or scene.fps

        if self.opt["nla_strip"]:
            return obj, self.import_as_strip(obj)

        frames = [float(f) for f in range(len(self.times))]
        action = self.bake(obj, frames)
        if self.opt["set_scene_range"]:
            s = self.context.scene
            s.frame_start, s.frame_end = 0, len(self.times) - 1
            s.frame_current = 0
            s.render.fps = int(round(self.fps))
            s.render.fps_base = 1.0
        return obj, action

    def read_source(self, scene):
        """World matrices of the Mixamo bones, at rest and at every output frame, in Blender Z-up."""
        models = [m for m in scene.all_models() if m.kind in ("LimbNode", "Null", "Root", "")]
        by_short = {}
        for m in models:
            by_short.setdefault(m.short_name, m)
        if "Hips" not in by_short:
            raise MixamoError("No Mixamo Hips bone in the file (bone names must be mixamorig:Hips, ...)")
        self.src_models = by_short

        span = scene.time_range()
        if span is None:
            raise MixamoError("The file contains no animation")
        fps = self.opt["fps"] or scene.fps
        first, last = span
        count = int((last - first) * fps + 1e-4) + 1
        self.times = [first + i / fps for i in range(count)]

        conv = axis_conversion(scene)
        wanted = set(by_short.values())

        def world_matrices(t):
            world = {}
            for m in scene.all_models():
                local = fbx_local_matrix(m.transform(t))
                parent = world.get(m.parent.uid) if m.parent is not None else None
                world[m.uid] = parent @ local if parent is not None else local
            return {m.short_name: conv @ world[m.uid] for m in wanted}

        self.src_rest = world_matrices(None)
        self.src_anim = [world_matrices(t) for t in self.times]

    # -----------------------------------------------------------------------
    def sequence_names(self):
        names = [n.strip() for n in self.opt.get("sequence_name", "").split(".")]
        names = [n for n in names if n]
        return names or [os.path.splitext(os.path.basename(self.filepath))[0].replace(" ", "_")]

    def import_as_strip(self, obj):
        """Bakes into its own action (keys 0..N-1) on a new NLA strip, laid out like the jediacademy
        addon's .gla + animation.cfg import (same as the JA dotXSI add-on)."""
        anim = obj.animation_data_create()
        prev_action = anim.action
        prev_slot = getattr(anim, "action_slot", None)

        num = len(self.times)
        start = self.opt["strip_start"]
        if start < 0:
            ends = [s.frame_end for t in anim.nla_tracks for s in t.strips]
            start = int(max(ends)) + 1 if ends else 0

        names = self.sequence_names()
        action = self.bake(obj, [float(f) for f in range(num)], names[0])
        slot = getattr(anim, "action_slot", None)

        props = getattr(action, "g2_sequence_prop", None)  # jediacademy addon: animation.cfg metadata
        if props is not None:
            props.loop_start_frame = self.opt["loop_frame"]
            props.num_frames = num
            props.fps = int(round(self.fps))

        # Blender would clip the strip to the action range of the previous assignment
        if hasattr(anim, "action_slot"):
            anim.action_slot = None
        anim.action = None

        actions = [action]
        for name in names[1:]:
            copy = action.copy()
            copy.name = name
            copy.use_fake_user = True
            actions.append(copy)

        for track in anim.nla_tracks:
            for s in track.strips:
                s.select = False

        placed = [self.add_strip(anim, act, slot, start, num) for act in actions]
        anim.use_nla = True

        anim.action = prev_action
        if prev_action is not None and hasattr(anim, "action_slot") and prev_slot is not None:
            try:
                anim.action_slot = prev_slot
            except (RuntimeError, TypeError):
                pass

        end = start + max(0, num - 1)
        scene = self.context.scene
        if self.opt["set_scene_range"]:
            only_ours = sum(len(t.strips) for t in anim.nla_tracks) == len(placed)
            if only_ours:
                scene.frame_start, scene.frame_end = start, end
                scene.render.fps = int(round(self.fps))
                scene.render.fps_base = 1.0
            else:
                scene.frame_start = min(scene.frame_start, start)
                scene.frame_end = max(scene.frame_end, end)
            scene.frame_current = start

        our_tracks = {track for _, track in placed}
        solo = [t.name for t in anim.nla_tracks if t.is_solo and t not in our_tracks]
        msg = "Added %s, frames %d-%d" % (", ".join("%r on %r" % (s.name, t.name) for s, t in placed), start, end)
        if solo:
            msg += " (track %r is soloed, un-solo it to see the new strips)" % solo[0]
        self.message = msg
        print("Mixamo:", msg)
        return action

    def add_strip(self, anim, action, slot, start, num):
        """Adds a strip for `action` on the first "Sequences Layer n" track that is free there."""
        if slot is not None and hasattr(action, "slots"):
            slot = next((s for s in action.slots if s.identifier == slot.identifier), None)

        strip = None
        track = None
        layer = 1
        while strip is None:
            if layer > 64:
                raise MixamoError("Could not find a free NLA track at frame %d" % start)
            track_name = "Sequences Layer %d" % layer
            track = anim.nla_tracks.get(track_name) or anim.nla_tracks.new()
            track.name = track_name
            free = all(s.frame_end < start or s.frame_start > start + num - 1 for s in track.strips)
            if free:
                try:
                    strip = track.strips.new(action.name, start, action)
                except RuntimeError:
                    strip = None
            layer += 1
        assert track is not None

        if hasattr(strip, "action_slot") and slot is not None:
            strip.action_slot = slot
        strip.action_frame_start = 0
        strip.action_frame_end = max(0, num - 1)
        strip.frame_start = start
        strip.frame_end = start + max(0, num - 1)
        strip.scale = 1.0
        strip.repeat = 1.0
        strip.extrapolation = "NOTHING"
        strip.blend_type = "REPLACE"
        strip.use_auto_blend = False
        strip.blend_in = strip.blend_out = 0.0
        strip.select = True
        return strip, track

    # -----------------------------------------------------------------------
    def source_aim(self, name):
        """Rest direction of a Mixamo bone (towards its aim joint), None if it has none."""
        model = self.src_models.get(name)
        if model is None:
            return None
        aim = SOURCE_AIM.get(name)
        if aim is None or aim not in self.src_rest:
            children = [c.short_name for c in model.children if c.short_name in self.src_rest]
            aim = children[0] if children else None
        if aim is None:
            return None
        d = self.src_rest[aim].to_translation() - self.src_rest[name].to_translation()
        return d.normalized() if d.length > 1e-6 else None

    def scale_factor(self, rest):
        """File units -> armature units: the ratio of both skeletons' hip heights above the ankles."""
        if self.opt["scale"] > 0:
            return self.opt["scale"]

        def height(mats, root, feet):
            ankles = [mats[f].to_translation().z for f in feet if f in mats]
            if root not in mats or not ankles:
                return None
            return mats[root].to_translation().z - sum(ankles) / len(ankles)

        target = height(rest, TARGET_LEG[0], TARGET_LEG[1])
        source = height(self.src_rest, SOURCE_LEG[0], SOURCE_LEG[1])
        if not target or not source or target <= 0 or source <= 0:
            self.warnings.append("Could not measure the legs, scale set to 1")
            return 1.0
        return target / source

    def bake(self, obj, frames, action_name=None):
        arm = obj.data
        # The jediacademy exporter reads poses as skeleton_root.matrix_local @ pose_bone.matrix: the
        # Ghoul2 space is the armature's parent space. The source is converted into armature space.
        L = obj.matrix_local.copy()
        L_inv = L.inverted()

        bones = list(arm.bones)
        rest = {b.name: b.matrix_local.copy() for b in bones}
        rest_inv = {n: m.inverted() for n, m in rest.items()}

        mapping = {t: s for t, s in BONE_MAP if t in rest and s in self.src_rest}
        if "pelvis" not in mapping:
            raise MixamoError("Armature %r has no pelvis bone, or the file has no Hips" % obj.name)
        missing = [t for t, s in BONE_MAP if t in rest and t not in mapping]
        if missing:
            self.warnings.append("No source bone for %s" % ", ".join(missing))

        # Source rest / animation, in armature space
        src_rest = {n: L_inv @ m for n, m in self.src_rest.items()}
        src_anim = [{n: L_inv @ m for n, m in frame.items()} for frame in self.src_anim]
        src_rest_rot_inv = {n: m.to_quaternion().inverted() for n, m in src_rest.items()}

        # Rest corrections: swing the target's rest bone direction (its Y axis) onto the source's
        correction = {}
        for t, s in mapping.items():
            if t in SAME_CORRECTION:
                continue
            aim = self.source_aim(s)
            if aim is not None:
                aim = (L_inv.to_3x3() @ aim).normalized()
                correction[t] = rest[t].to_3x3().col[1].normalized().rotation_difference(aim)
            else:
                correction[t] = Quaternion()
        for t, other in SAME_CORRECTION.items():
            if t in mapping:
                correction[t] = correction.get(other, Quaternion())

        k = self.scale_factor(rest)
        origin = L_inv @ Matrix.Translation(Vector(self.opt["origin_offset"])) @ L

        # Order: every bone after its anatomical parent
        def parent_of(b):
            p = ANATOMICAL_PARENT.get(b.name)
            return p if p in rest else (b.parent.name if b.parent else None)
        order = []
        seen = set()

        def visit(name):
            if name in seen:
                return
            seen.add(name)
            p = parent_of(arm.bones[name])
            if p is not None:
                visit(p)
            order.append(name)
        for b in bones:
            visit(b.name)

        pelvis_rest = rest["pelvis"].to_translation()
        hips_rest = src_rest[mapping["pelvis"]].to_translation()

        action = bpy.data.actions.new(action_name or self.sequence_names()[0])
        action.use_fake_user = True
        fcurves = get_fcurves(obj, action)

        num = len(src_anim)
        locs = {n: [] for n in rest}
        quats = {n: [] for n in rest}
        for fi in range(num):
            src = src_anim[fi]
            posed = {}
            for name in order:
                p = parent_of(arm.bones[name])
                follow = posed[p] @ rest_inv[p] @ rest[name] if p is not None else rest[name].copy()
                s = mapping.get(name)
                if s is None:
                    posed[name] = follow
                    continue
                rot = src[s].to_quaternion() @ src_rest_rot_inv[s] @ correction[name] @ rest[name].to_quaternion()
                if name == "pelvis":
                    delta = (src[s].to_translation() - hips_rest) * k
                    if self.opt["in_place"]:
                        delta.x = delta.y = 0.0
                    pos = pelvis_rest + delta
                else:
                    pos = follow.to_translation()
                posed[name] = Matrix.LocRotScale(pos, rot, None)

            final = {n: origin @ m for n, m in posed.items()}
            for bone in bones:
                name = bone.name
                if bone.parent:
                    par = bone.parent.name
                    basis = rest_inv[name] @ rest[par] @ final[par].inverted() @ final[name]
                else:
                    basis = rest_inv[name] @ final[name]
                loc, quat, _ = basis.decompose()
                prev = quats[name][-1] if quats[name] else None
                if prev is not None:
                    quat.make_compatible(prev)
                locs[name].append(loc)
                quats[name].append(quat)

        for bone in bones:
            name = bone.name
            obj.pose.bones[name].rotation_mode = "QUATERNION"
            escaped = bpy.utils.escape_identifier(name)
            for path, values, size in (
                    ('pose.bones["%s"].location' % escaped, locs[name], 3),
                    ('pose.bones["%s"].rotation_quaternion' % escaped, quats[name], 4)):
                for component in range(size):
                    fc = new_fcurve(fcurves, path, component, name)
                    fc.keyframe_points.add(num)
                    co = [0.0] * (2 * num)
                    co[0::2] = frames
                    co[1::2] = [v[component] for v in values]
                    fc.keyframe_points.foreach_set("co", co)
                    fc.keyframe_points.foreach_set("interpolation", [LINEAR] * num)
                    fc.update()

        print("Mixamo: %d frames at %g fps, scale %.4f, %d/%d bones mapped" % (num, self.fps, k, len(mapping), len(bones)))
        return action


LINEAR = getattr(bpy.types.Keyframe.bl_rna.properties["interpolation"], "enum_items")["LINEAR"].value


def load(operator, context, filepath="", **opt) -> Set[OperatorReturnItems]:
    importer = Importer(operator, context, filepath, opt)
    try:
        obj, action = importer.run()
    except (MixamoError, fbx.FBXError, OSError) as e:
        operator.report({"ERROR"}, str(e))
        return {"CANCELLED"}

    message = importer.message or "Imported %r onto %r" % (action.name, obj.name)
    if importer.warnings:
        operator.report({"WARNING"}, " - ".join(importer.warnings + [message]))
    else:
        operator.report({"INFO"}, message)
    return {"FINISHED"}
