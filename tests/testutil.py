import importlib.util
import os
import sys
from types import ModuleType
from typing import Callable, List, Optional, Tuple

PACKAGE = "JA-Mixamo-Importer"


def import_addon() -> ModuleType:
    """Import the repo as the add-on package regardless of its on-disk directory name."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loaded = sys.modules.get(PACKAGE)
    if loaded is not None:
        if os.path.dirname(os.path.abspath(loaded.__file__ or "")) == repo_root:
            return loaded
        # an installed copy of the add-on, enabled without --factory-startup: test the repo instead
        import addon_utils
        addon_utils.disable(PACKAGE, default_set=False)
        for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        PACKAGE, os.path.join(repo_root, "__init__.py"),
        submodule_search_locations=[repo_root],
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def reset_scene() -> None:
    """Clear all Blender state between test cases so one case can't leak objects/data into the next."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)


class Skip(Exception):
    """Raised by a case whose inputs aren't available (e.g. local-only game files)."""


class TestRunner:
    """Runs each case, logs pass/fail immediately, defers raising until every case has run."""

    def __init__(self) -> None:
        self.results: List[Tuple[str, Optional[Exception]]] = []

    def run(self, name: str, fn: Callable[[], None]) -> None:
        print(f"[test] Running {name}...")
        try:
            fn()
        except Skip as e:
            print(f"[test] {name}: SKIP - {e}")
            self.results.append((name, e))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[test] {name}: FAIL - {e}")
            self.results.append((name, e))
        else:
            print(f"[test] {name}: PASS")
            self.results.append((name, None))

    def report(self) -> None:
        print("[test] === Summary ===")
        failed = []
        for name, err in self.results:
            status = "PASS" if err is None else "SKIP" if isinstance(err, Skip) else "FAIL"
            print(f"[test]   {name}: {status}")
            if status == "FAIL":
                failed.append(name)
        if failed:
            raise RuntimeError(f"{len(failed)}/{len(self.results)} test case(s) failed: {', '.join(failed)}")


def check(mismatches: List[str]) -> None:
    """A case's assertion helper: turn a list of mismatch strings into an exception if non-empty."""
    if mismatches:
        shown = mismatches[:30]
        more = f"\n  ... and {len(mismatches) - len(shown)} more" if len(mismatches) > len(shown) else ""
        raise AssertionError(f"{len(mismatches)} mismatch(es):\n" + "\n".join(f"  - {m}" for m in shown) + more)


# ---------------------------------------------------------------------------
# A synthetic _humanoid: Raven's .gla is proprietary, so the tests build an armature with its 53 bone
# names and Ghoul2 hierarchy (fingers and tags under the forearm), in an A-pose facing -Y, Ghoul2
# units, like the jediacademy add-on's import: skeleton_root under a 0.1-scaled scene_root, each
# bone's Y axis along the limb. Proportions are made up.

# name, parent, head, point the bone's Y axis aims at
_CENTRE = [
    ("model_root", None, (0, 0, 0), (1, 0, 0)),
    ("pelvis", "model_root", (0, 0.4, 36), (0, 0.4, 41)),
    ("Motion", "pelvis", (0, 0.4, 37), (1, 0.4, 37)),
    ("lower_lumbar", "pelvis", (0, 0.4, 41), (0, 0.4, 46)),
    ("upper_lumbar", "lower_lumbar", (0, 0.4, 46), (0, 0.4, 51)),
    ("thoracic", "upper_lumbar", (0, 0.4, 51), (0, 0.4, 57)),
    ("cervical", "thoracic", (0, 0.4, 57), (0, 0.4, 60)),
    ("cranium", "cervical", (0, 0.4, 60), (0.02, 0.4, 64)),
    ("face", "cranium", (0, 0.4, 60), (0.02, 0.4, 64)),
    ("ceyebrow", "face", (0, -3.5, 63), (0, -4.5, 63.3)),
    ("jaw", "face", (0, -0.5, 61), (0, -1.5, 60.4)),
]
_LEFT = [
    ("lfemurYZ", "pelvis", (3.6, -0.2, 35.6), (7.4, 0.8, 21.4)),
    ("lfemurX", "lfemurYZ", (5.5, 0.3, 28.5), (7.4, 0.8, 21.4)),
    ("ltibia", "lfemurYZ", (7.4, 0.8, 21.4), (11.1, 1.8, 7.5)),
    ("ltalus", "ltibia", (11.1, 1.8, 7.5), (11.3, -1.2, 5.3)),
    ("ltail", "lfemurYZ", (2.5, 5.2, 38.4), (2.8, 5.4, 37.4)),
    ("lclavical", "thoracic", (0, 0.4, 54.5), (5.9, 1.1, 54.5)),
    ("lhumerus", "thoracic", (5.9, 1.1, 54.5), (13.2, 0.9, 46.4)),
    ("lhumerusX", "lhumerus", (9.5, 1.0, 50.5), (13.2, 0.9, 46.4)),
    ("lradius", "lhumerus", (13.2, 0.9, 46.4), (19.0, 0.3, 39.9)),
    ("lradiusX", "lradius", (16.1, 0.6, 43.2), (19.0, 0.3, 39.9)),
    ("lhand", "lradius", (19.0, 0.3, 39.9), (20.1, 0.0, 38.3)),
    ("l_d1_j1", "lradius", (19.1, -0.6, 39.2), (19.0, -1.4, 37.9)),
    ("l_d1_j2", "lradius", (19.0, -1.4, 37.9), (18.9, -1.7, 36.9)),
    ("l_d2_j1", "lradius", (21.0, -0.9, 37.4), (20.8, -1.2, 36.1)),
    ("l_d2_j2", "lradius", (20.8, -1.2, 36.1), (20.4, -1.3, 35.2)),
    ("l_d4_j1", "lradius", (21.0, 0.4, 37.2), (20.6, 0.3, 36.0)),
    ("l_d4_j2", "lradius", (20.6, 0.3, 36.0), (19.8, 0.2, 35.4)),
    ("lhang_tag_bone", "lradius", (20.1, -0.1, 37.0), (21.0, 0.0, 36.6)),
    ("leye", "face", (1.1, -2.9, 62.6), (1.1, -3.9, 62.6)),
    ("lblip2", "face", (0.6, -3.9, 60.0), (1.4, -3.3, 60.1)),
    ("ltlip2", "face", (0.6, -3.9, 60.2), (1.4, -3.3, 60.1)),
]


def _mirror(entries):
    out = []
    for name, parent, head, aim in entries:
        def m(n):
            return n if n is None else ("r" + n[1:] if n[0] == "l" and n != "lower_lumbar" else n)
        out.append((m(name), m(parent), (-head[0], head[1], head[2]), (-aim[0], aim[1], aim[2])))
    return out


HUMANOID = _CENTRE + _LEFT + _mirror(_LEFT)


def make_humanoid():
    """Builds scene_root / skeleton_root with the synthetic _humanoid bones, returns skeleton_root."""
    import bpy
    from mathutils import Vector

    context = bpy.context
    assert context.scene is not None and context.collection is not None and context.view_layer is not None
    scene_root = bpy.data.objects.new("scene_root", None)
    scene_root.scale = (0.1, 0.1, 0.1)
    context.collection.objects.link(scene_root)

    arm = bpy.data.armatures.new("skeleton_root")
    obj = bpy.data.objects.new("skeleton_root", arm)
    context.collection.objects.link(obj)
    obj.parent = scene_root
    context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, _, head, aim in HUMANOID:
        eb = arm.edit_bones.new(name)
        eb.head = Vector(head)
        eb.tail = Vector(head) + (Vector(aim) - Vector(head)).normalized() * 2.0
    for name, parent, _, _ in HUMANOID:
        if parent is not None:
            arm.edit_bones[name].parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


# bpy's Optional-typed accessors, asserted once here rather than at every call site in the cases

def scene():
    import bpy
    scene = bpy.context.scene
    assert scene is not None
    return scene


def bones(obj):
    import bpy
    assert isinstance(obj.data, bpy.types.Armature)
    return obj.data.bones


def pose_bones(obj):
    assert obj.pose is not None
    return obj.pose.bones


def anim(obj):
    assert obj.animation_data is not None
    return obj.animation_data
