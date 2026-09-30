"""Headless test suite: blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py

Runs against the synthetic fixtures of tests/testdata (tests/tools/generate_test_fbx.py) and a
synthetic _humanoid armature (testutil.make_humanoid). The last case also retargets real Mixamo
downloads onto Raven's _humanoid.gla when they're available locally (skipped otherwise):
  JA_HUMANOID_GLA  path to _humanoid.gla (needs the jediacademy add-on)
  JA_MIXAMO_FBX    directory with Mixamo .fbx files
"""

import glob
import importlib
import math
import os
import sys
import tempfile
from typing import Any, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testutil  # noqa: E402 - path must be set up first

addon = testutil.import_addon()
addon.register()
# the operator imports these lazily, in execute()
fbx = importlib.import_module(testutil.PACKAGE + ".fbx")
importer = importlib.import_module(testutil.PACKAGE + ".mixamo_blender_importer")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTDATA = os.path.join(REPO_ROOT, "tests", "testdata")
FIXTURE = os.path.join(TESTDATA, "mixamo_synth.fbx")
FIXTURES = [os.path.join(TESTDATA, f) for f in ("mixamo_synth.fbx", "mixamo_synth_74.fbx", "mixamo_synth_ascii.fbx")]
FIXTURE_FRAMES = 16

IMPORT_DEFAULTS: Dict[str, Any] = dict(
    scale=0.0, origin_offset=(0.0, 0.0, -24.0), in_place=False, fps=0, nla_strip=True,
    strip_start=-1, sequence_name="", loop_frame=-1, set_scene_range=True)


class FakeOperator:
    """Stands in for the operator, so a case can check what would have been reported to the user."""

    def __init__(self) -> None:
        self.reports: List[Tuple[str, str]] = []

    def report(self, types, message) -> None:
        for t in types:
            self.reports.append((t, message))


def _import(**opt) -> FakeOperator:
    import bpy
    op = FakeOperator()
    result = importer.load(op, bpy.context, filepath=opt.pop("filepath", FIXTURE), **{**IMPORT_DEFAULTS, **opt})
    if result != {"FINISHED"}:
        raise AssertionError(f"import failed: {op.reports}")
    return op


def _import_fails(**opt) -> FakeOperator:
    import bpy
    op = FakeOperator()
    result = importer.load(op, bpy.context, filepath=opt.pop("filepath", FIXTURE), **{**IMPORT_DEFAULTS, **opt})
    if result != {"CANCELLED"} or not any(t == "ERROR" for t, _ in op.reports):
        raise AssertionError(f"expected an error, got {result} {op.reports}")
    return op


def _strips(obj) -> Dict[str, Any]:
    return {s.name: (t, s) for t in testutil.anim(obj).nla_tracks for s in t.strips}


def _tmp(name: str) -> str:
    return os.path.join(tempfile.mkdtemp(prefix="ja-mixamo-test-"), name)


def _source_world(path: str, fps: float = 30.0) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Rest and per-frame world matrices of the file's models by short name, Blender Z-up."""
    scene = fbx.load_scene(path)
    conv = importer.axis_conversion(scene)
    first, last = scene.time_range()
    times = [first + i / fps for i in range(int((last - first) * fps + 1e-4) + 1)]

    def world(t):
        mats: Dict[int, Any] = {}
        for m in scene.all_models():
            local = importer.fbx_local_matrix(m.transform(t))
            parent = mats.get(m.parent.uid) if m.parent is not None else None
            mats[m.uid] = parent @ local if parent is not None else local
        return {m.short_name: conv @ mats[m.uid] for m in scene.all_models()}
    return world(None), [world(t) for t in times]


def _aim(mats: Dict[str, Any], name: str, source_children: Dict[str, str]):
    aim = importer.SOURCE_AIM.get(name) or source_children[name]
    return (mats[aim].to_translation() - mats[name].to_translation()).normalized()


def _source_children(path: str) -> Dict[str, str]:
    scene = fbx.load_scene(path)
    return {m.short_name: m.children[0].short_name for m in scene.all_models() if m.children}


def _pose_at(obj, frame: int) -> Dict[str, Any]:
    testutil.scene().frame_set(frame)
    return {pb.name: pb.matrix.copy() for pb in testutil.pose_bones(obj)}


def _angle(a, b) -> float:
    return math.degrees(a.angle(b)) if a.length > 1e-9 and b.length > 1e-9 else 180.0


# ---------------------------------------------------------------------------

def case_smoke() -> None:
    import bpy
    if addon.bl_info["name"] != "JA Mixamo NLA Import (.fbx)" or addon.MENU_TEXT != "JA Mixamo NLA Import (.fbx)":
        raise AssertionError(f"menu / add-on name: {addon.bl_info['name']!r} {addon.MENU_TEXT!r}")
    if not hasattr(bpy.types, "IMPORT_ANIM_OT_ja_mixamo_fbx"):
        raise AssertionError("operator not registered")

    drawn = []

    class Layout:
        def operator(self, idname, text=""):
            drawn.append((idname, text))

    class Menu:
        layout = Layout()
    addon.menu_func_import(Menu(), bpy.context)
    if drawn != [("import_anim.ja_mixamo_fbx", "JA Mixamo NLA Import (.fbx)")]:
        raise AssertionError(f"menu entry: {drawn}")


def case_parse_formats() -> None:
    """ASCII 7.4, binary 7.4 and binary 7.5 (zlib arrays) of the same scene read identically."""
    mismatches = []
    scenes = [fbx.load_scene(p) for p in FIXTURES]
    ref = scenes[0]
    for path, scene in zip(FIXTURES, scenes):
        label = os.path.basename(path)
        if scene.fps != 30.0 or scene.up_axis != 1:
            mismatches.append(f"{label}: fps {scene.fps}, up axis {scene.up_axis}")
        span = scene.time_range()
        if span is None or abs(span[0]) > 1e-9 or abs(span[1] - 0.5) > 1e-9:
            mismatches.append(f"{label}: time range {span}")
        names = [(m.name, m.kind, m.parent.name if m.parent else None) for m in scene.all_models()]
        ref_names = [(m.name, m.kind, m.parent.name if m.parent else None) for m in ref.all_models()]
        if names != ref_names:
            mismatches.append(f"{label}: model tree differs")
            continue
        for m, r in zip(scene.all_models(), ref.all_models()):
            for t in (None, 0.0, 0.2, 0.37, 0.5):
                a, b = m.transform(t), r.transform(t)
                for key in ("translation", "rotation", "pre_rotation"):
                    if max(abs(x - y) for x, y in zip(a[key], b[key])) > 1e-4:
                        mismatches.append(f"{label}: {m.name} {key} at {t}: {a[key]} != {b[key]}")
    testutil.check(mismatches)


def case_parse_values() -> None:
    scene = fbx.load_scene(FIXTURE)
    by_name = {m.short_name: m for m in scene.all_models()}
    mismatches = []
    hips = by_name["Hips"]
    if hips.name != "mixamorig:Hips" or hips.kind != "LimbNode" or hips.parent is not scene.root:
        mismatches.append(f"Hips: {hips.name} {hips.kind} {hips.parent}")
    if by_name["LeftShoulder"].transform()["pre_rotation"] != (0.0, 0.0, -90.0):
        mismatches.append("LeftShoulder PreRotation")
    if by_name["Body_Geo"].kind != "Mesh" or by_name["Unrelated_Helper"].kind != "Null":
        mismatches.append("extra models kinds")
    # rest = the model's own properties, animation = its curves (key 0 at rest, the middle key moved)
    if hips.transform()["translation"] != (0.0, 100.0, 0.0):
        mismatches.append(f"Hips rest {hips.transform()['translation']}")
    t = 0.25  # key 7.5: halfway between keys 7 and 8, linearly interpolated
    k7, k8 = 7 / 15, 8 / 15
    expected_x = 4.0 * (math.sin(k7 * math.pi) + math.sin(k8 * math.pi)) / 2
    got = hips.transform(t)["translation"]
    if abs(got[0] - expected_x) > 1e-4 or abs(got[2] - 15.0) > 1e-4:
        mismatches.append(f"Hips at {t}: {got}, expected x {expected_x}, z 15")
    if by_name["Head"].curves:
        mismatches.append("Head should not be animated")
    testutil.check(mismatches)


def case_local_matrix() -> None:
    """The FBX transform formula, against matrices built by hand."""
    from mathutils import Euler, Matrix
    base = dict(translation=(1.0, 2.0, 3.0), rotation=(90.0, 0.0, 0.0), scaling=(1.0, 1.0, 1.0), rotation_order="XYZ",
                pre_rotation=(0.0, 0.0, 90.0), post_rotation=(0.0, 0.0, 0.0), rotation_offset=(0.0, 0.0, 0.0),
                rotation_pivot=(0.0, 0.0, 0.0), scaling_offset=(0.0, 0.0, 0.0), scaling_pivot=(0.0, 0.0, 0.0))
    mismatches = []

    def compare(label, got, expected):
        err = max(abs(got[i][j] - expected[i][j]) for i in range(4) for j in range(4))
        if err > 1e-5:
            mismatches.append(f"{label}: off by {err}\n{got}\n{expected}")

    rx = Matrix.Rotation(math.radians(90), 4, "X")
    rz = Matrix.Rotation(math.radians(90), 4, "Z")
    compare("pre-rotation", importer.fbx_local_matrix(base), Matrix.Translation((1, 2, 3)) @ rz @ rx)

    pivot = dict(base, pre_rotation=(0.0, 0.0, 0.0), rotation_pivot=(0.0, 1.0, 0.0))
    compare("pivot", importer.fbx_local_matrix(pivot),
            Matrix.Translation((1, 2, 3)) @ Matrix.Translation((0, 1, 0)) @ rx @ Matrix.Translation((0, -1, 0)))

    post = dict(base, pre_rotation=(0.0, 0.0, 0.0), post_rotation=(0.0, 0.0, 90.0))
    compare("post-rotation", importer.fbx_local_matrix(post), Matrix.Translation((1, 2, 3)) @ rx @ rz.inverted())

    order = dict(base, pre_rotation=(0.0, 0.0, 0.0), rotation=(30.0, 40.0, 50.0), rotation_order="ZYX")
    compare("rotation order", importer.fbx_local_matrix(order),
            Matrix.Translation((1, 2, 3)) @ Euler([math.radians(a) for a in (30, 40, 50)], "ZYX").to_matrix().to_4x4())
    testutil.check(mismatches)


def case_source_axes() -> None:
    """Y-up / +Z-facing Mixamo converted to Blender: up is +Z, the character faces -Y, left is +X."""
    rest, _ = _source_world(FIXTURE)
    mismatches = []
    pos = {n: m.to_translation() for n, m in rest.items()}
    if not pos["Head"].z > pos["Hips"].z > pos["LeftFoot"].z:
        mismatches.append("up axis")
    if not pos["LeftToeBase"].y < pos["LeftFoot"].y:
        mismatches.append("facing: toes should be towards -Y")
    if not pos["LeftHand"].x > pos["LeftShoulder"].x > 0 > pos["RightHand"].x:
        mismatches.append("left side should be +X")
    testutil.check(mismatches)


def case_import_strip() -> None:
    import bpy
    obj = testutil.make_humanoid()
    op = _import(sequence_name="BOTH_TEST", loop_frame=0)
    strips = _strips(obj)
    if list(strips) != ["BOTH_TEST"]:
        raise AssertionError(f"strips: {list(strips)} ({op.reports})")
    track, strip = strips["BOTH_TEST"]
    mismatches = []
    if track.name != "Sequences Layer 1":
        mismatches.append(f"track {track.name}")
    if (strip.frame_start, strip.frame_end) != (0, FIXTURE_FRAMES - 1):
        mismatches.append(f"strip frames {strip.frame_start}-{strip.frame_end}")
    if strip.extrapolation != "NOTHING" or strip.blend_type != "REPLACE" or not strip.select:
        mismatches.append("strip settings")
    action = bpy.data.actions["BOTH_TEST"]
    if not action.use_fake_user:
        mismatches.append("action without fake user")
    scene = testutil.scene()
    if (scene.frame_start, scene.frame_end, scene.render.fps) != (0, FIXTURE_FRAMES - 1, 30):
        mismatches.append(f"scene range / fps {scene.frame_start}-{scene.frame_end} @ {scene.render.fps}")
    if testutil.anim(obj).action is not None:
        mismatches.append("an NLA import must not leave an active action")
    if not any(t == "INFO" and "BOTH_TEST" in m for t, m in op.reports):
        mismatches.append(f"reports {op.reports}")
    testutil.check(mismatches)


def case_retarget_directions() -> None:
    """Every mapped bone points where its Mixamo bone points, at rest and in every frame."""
    obj = testutil.make_humanoid()
    _import(nla_strip=False)
    rest, frames = _source_world(FIXTURE)
    children = _source_children(FIXTURE)
    mismatches = []
    for fi in (0, 4, 7, 11, 15):
        pose = _pose_at(obj, fi)
        for target, source in importer.BONE_MAP:
            if target in importer.SAME_CORRECTION:
                continue
            got = pose[target].col[1].to_3d().normalized()
            expected = _aim(frames[fi], source, children)
            angle = _angle(got, expected)
            if angle > 0.05:
                mismatches.append(f"frame {fi} {target} <- {source}: {angle:.3f} degrees off")
    testutil.check(mismatches)


def case_pelvis_motion() -> None:
    """The pelvis follows the hips, scaled by the hip height ratio, plus the origin offset."""
    obj = testutil.make_humanoid()
    _import(nla_strip=False)
    rest, frames = _source_world(FIXTURE)
    bones = testutil.bones(obj)
    pelvis_rest = bones["pelvis"].matrix_local.to_translation()
    ankles = (bones["ltalus"].head_local.z + bones["rtalus"].head_local.z) / 2
    src_ankles = (rest["LeftFoot"].to_translation().z + rest["RightFoot"].to_translation().z) / 2
    k = (pelvis_rest.z - ankles) / (rest["Hips"].to_translation().z - src_ankles)
    mismatches = []
    for fi in range(0, FIXTURE_FRAMES, 3):
        got = _pose_at(obj, fi)["pelvis"].to_translation()
        delta = (frames[fi]["Hips"].to_translation() - rest["Hips"].to_translation()) * k
        expected = pelvis_rest + delta
        expected.z -= 24.0
        if (got - expected).length > 1e-3:
            mismatches.append(f"frame {fi}: pelvis at {got}, expected {expected}")
    testutil.check(mismatches)


def case_rigid_attachments() -> None:
    """Tags and fingers follow the hand, twist / face bones their parent, bone lengths are kept."""
    obj = testutil.make_humanoid()
    _import(nla_strip=False)
    pairs = [("lhand", "lhang_tag_bone"), ("rhand", "rhang_tag_bone"), ("lhumerus", "lhumerusX"),
             ("rradius", "rradiusX"), ("cranium", "face"), ("face", "jaw"), ("pelvis", "Motion"), ("lfemurYZ", "ltail")]
    heads = [("lhand", "l_d2_j1"), ("rhand", "r_d1_j1"), ("l_d4_j1", "l_d4_j2"), ("lradius", "lhand"), ("ltibia", "ltalus")]
    first = _pose_at(obj, 0)
    mismatches = []
    for fi in (5, 10, 15):
        pose = _pose_at(obj, fi)
        for a, b in pairs:
            r0 = first[a].inverted() @ first[b]
            r1 = pose[a].inverted() @ pose[b]
            err = max(abs(r0[i][j] - r1[i][j]) for i in range(4) for j in range(4))
            if err > 1e-4:
                mismatches.append(f"frame {fi}: {b} moved relative to {a} ({err:.5f})")
        for a, b in heads:
            d0 = (first[b].to_translation() - first[a].to_translation()).length
            d1 = (pose[b].to_translation() - pose[a].to_translation()).length
            if abs(d0 - d1) > 1e-4:
                mismatches.append(f"frame {fi}: {a}-{b} distance {d0:.4f} -> {d1:.4f}")
    testutil.check(mismatches)


def case_formats_same_pose() -> None:
    poses = []
    for path in FIXTURES:
        testutil.reset_scene()
        obj = testutil.make_humanoid()
        _import(filepath=path, nla_strip=False)
        poses.append((os.path.basename(path), _pose_at(obj, 9)))
    mismatches = []
    for label, pose in poses[1:]:
        for name, m in pose.items():
            err = max(abs(m[i][j] - poses[0][1][name][i][j]) for i in range(4) for j in range(4))
            if err > 1e-3:
                mismatches.append(f"{label} {name}: {err}")
    testutil.check(mismatches)


def case_stacked_and_appended() -> None:
    obj = testutil.make_humanoid()
    _import(sequence_name="BOTH_A.BOTH_B")
    _import(sequence_name="BOTH_C")
    strips = _strips(obj)
    mismatches = []
    if sorted(strips) != ["BOTH_A", "BOTH_B", "BOTH_C"]:
        raise AssertionError(f"strips {sorted(strips)}")
    (ta, a), (tb, b), (_, c) = strips["BOTH_A"], strips["BOTH_B"], strips["BOTH_C"]
    if (a.frame_start, a.frame_end) != (b.frame_start, b.frame_end) or ta == tb:
        mismatches.append("BOTH_A / BOTH_B should be stacked on two tracks at the same frames")
    if c.frame_start != FIXTURE_FRAMES or c.frame_end != 2 * FIXTURE_FRAMES - 1:
        mismatches.append(f"BOTH_C at {c.frame_start}-{c.frame_end}, expected after the others")
    if [s.name for _, s in strips.values() if s.select] != ["BOTH_C"]:
        mismatches.append("only the last import's strips should be selected")
    scene = testutil.scene()
    if (scene.frame_start, scene.frame_end) != (0, 2 * FIXTURE_FRAMES - 1):
        mismatches.append(f"scene range {scene.frame_start}-{scene.frame_end}")
    testutil.check(mismatches)


def case_options() -> None:
    import bpy
    mismatches = []

    obj = testutil.make_humanoid()
    _import(fps=15, sequence_name="HALF")
    _, strip = _strips(obj)["HALF"]
    if strip.frame_end - strip.frame_start + 1 != 8 or testutil.scene().render.fps != 15:
        mismatches.append(f"fps 15: {strip.frame_end - strip.frame_start + 1} frames")
    props = getattr(bpy.data.actions["HALF"], "g2_sequence_prop", None)
    if props is not None and props.fps != 15:
        mismatches.append("g2_sequence_prop fps")

    testutil.reset_scene()
    obj = testutil.make_humanoid()
    _import(in_place=True, nla_strip=False, origin_offset=(0.0, 0.0, 0.0))
    rest = testutil.bones(obj)["pelvis"].matrix_local.to_translation()
    for fi in (0, 8, 15):
        p = _pose_at(obj, fi)["pelvis"].to_translation()
        if abs(p.x - rest.x) > 1e-4 or abs(p.y - rest.y) > 1e-4:
            mismatches.append(f"in place, frame {fi}: pelvis moved horizontally to {p}")
    if abs(_pose_at(obj, 8)["pelvis"].to_translation().z - rest.z) < 0.5:
        mismatches.append("in place must keep the vertical motion")

    testutil.reset_scene()
    obj = testutil.make_humanoid()
    _import(scale=0.5, nla_strip=False, origin_offset=(0.0, 0.0, 0.0))
    rest_src, frames = _source_world(FIXTURE)
    expected = testutil.bones(obj)["pelvis"].matrix_local.to_translation() + \
        (frames[15]["Hips"].to_translation() - rest_src["Hips"].to_translation()) * 0.5
    got = _pose_at(obj, 15)["pelvis"].to_translation()
    if (got - expected).length > 1e-3:
        mismatches.append(f"scale 0.5: pelvis {got}, expected {expected}")
    action = testutil.anim(obj).action
    if action is None or action.name != "mixamo_synth":
        mismatches.append("nla_strip=False: the file-named action should be active")
    testutil.check(mismatches)


def case_errors() -> None:
    import bpy
    # no armature
    op = _import_fails()
    if not any("skeleton_root" in m for _, m in op.reports):
        raise AssertionError(op.reports)

    testutil.make_humanoid()
    not_fbx = _tmp("not_fbx.fbx")
    with open(not_fbx, "w") as f:
        f.write("hello\n")
    _import_fails(filepath=not_fbx)
    _import_fails(filepath=_tmp("missing.fbx"))

    # a skeleton without Mixamo names
    sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "tools"))
    gen = importlib.import_module("generate_test_fbx")
    nodes = gen.build_scene()
    for node in nodes[2][2]:
        if node[0] == "Model":
            node[1][1].name = node[1][1].name.replace("mixamorig:Hips", "mixamorig:Root")
    renamed = _tmp("no_hips.fbx")
    gen.write_binary(renamed, nodes, 7500, compress=True)
    op = _import_fails(filepath=renamed)
    if not any("Hips" in m for _, m in op.reports):
        raise AssertionError(op.reports)
    if bpy.data.actions:
        raise AssertionError("a failed import must not leave actions behind")


def case_real_files() -> None:
    """Real Mixamo downloads onto Raven's _humanoid.gla, when both are available locally."""
    import addon_utils
    import bpy
    gla = os.environ.get("JA_HUMANOID_GLA", "")
    files = sorted(glob.glob(os.path.join(os.environ.get("JA_MIXAMO_FBX", ""), "*.fbx")))
    if not gla or not os.path.exists(gla) or not files:
        raise testutil.Skip("set JA_HUMANOID_GLA and JA_MIXAMO_FBX to run it")
    if addon_utils.enable("jediacademy", default_set=False) is None:
        raise testutil.Skip("jediacademy add-on not installed")
    addon_utils.disable("jediacademy", default_set=False)
    gamedata = gla.replace("\\", "/").split("/base/")[0] + "/"
    mismatches = []
    for path in files:
        testutil.reset_scene()
        addon_utils.enable("jediacademy", default_set=False)
        bpy.ops.import_scene.gla(filepath=gla, basepath=gamedata, loadAnimations="NONE")  # pyright: ignore[reportAttributeAccessIssue]
        obj = bpy.data.objects["skeleton_root"]
        op = _import(filepath=path, nla_strip=False)
        rest = {b.name: b.head_local.copy() for b in testutil.bones(obj)}
        ground = min(rest["ltalus"].z, rest["rtalus"].z) - 24.0
        lowest = min(min(_pose_at(obj, f)["ltalus"].to_translation().z, _pose_at(obj, f)["rtalus"].to_translation().z)
                     for f in range(testutil.scene().frame_start, testutil.scene().frame_end + 1, 4))
        print(f"[test]   {os.path.basename(path)}: lowest ankle {lowest:.2f}, rest ground {ground:.2f} {op.reports}")
        if abs(lowest - ground) > 8.0:
            mismatches.append(f"{os.path.basename(path)}: feet {lowest:.2f} far from the ground {ground:.2f}")
    testutil.check(mismatches)


runner = testutil.TestRunner()
cases = [
    ("smoke", case_smoke),
    ("parse_formats", case_parse_formats),
    ("parse_values", case_parse_values),
    ("local_matrix", case_local_matrix),
    ("source_axes", case_source_axes),
    ("import_strip", case_import_strip),
    ("retarget_directions", case_retarget_directions),
    ("pelvis_motion", case_pelvis_motion),
    ("rigid_attachments", case_rigid_attachments),
    ("formats_same_pose", case_formats_same_pose),
    ("stacked_and_appended", case_stacked_and_appended),
    ("options", case_options),
    ("errors", case_errors),
    ("real_files", case_real_files),
]
for name, fn in cases:
    testutil.reset_scene()
    runner.run(name, fn)
runner.report()
