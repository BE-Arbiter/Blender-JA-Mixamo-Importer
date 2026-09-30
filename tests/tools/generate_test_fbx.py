"""Writes tests/testdata/mixamo_synth*.fbx: a synthetic Mixamo-like skeleton and animation.

Real Mixamo downloads are third-party content, so the fixtures are generated: the mixamorig bone
names and hierarchy, a T-pose in centimetres, Y-up, facing +Z, PreRotations on some bones, 30 fps
baked keys, plus a mesh model and a non-namespaced helper the importer must ignore. The same scene is
written three ways: ASCII 7.4, binary 7.4 (32-bit node headers, raw arrays) and binary 7.5 (64-bit
node headers, zlib-compressed arrays).

Standard library only: run it with any Python 3, e.g. Blender's.
    python tests/tools/generate_test_fbx.py
"""

import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testdata")
KTIME_PER_SECOND = 46186158000
FPS = 30
FRAMES = 16

# name, parent, local translation (cm), PreRotation (degrees)
BONES = [
    ("Hips", None, (0.0, 100.0, 0.0), (0.0, 0.0, 0.0)),
    ("Spine", "Hips", (0.0, 10.0, 1.0), (-5.0, 0.0, 0.0)),
    ("Spine1", "Spine", (0.0, 12.0, 0.0), (3.0, 0.0, 0.0)),
    ("Spine2", "Spine1", (0.0, 13.0, 0.0), (2.0, 0.0, 0.0)),
    ("Neck", "Spine2", (0.0, 15.0, -1.0), (0.0, 0.0, 0.0)),
    ("Head", "Neck", (0.0, 10.0, 2.0), (0.0, 0.0, 0.0)),
    ("HeadTop_End", "Head", (0.0, 20.0, 0.0), (0.0, 0.0, 0.0)),
    ("LeftUpLeg", "Hips", (9.0, -5.0, 0.0), (0.0, 0.0, 180.0)),
    ("LeftLeg", "LeftUpLeg", (0.0, 42.0, 0.0), (0.0, 0.0, 0.0)),
    ("LeftFoot", "LeftLeg", (0.0, 43.0, 0.0), (0.0, 0.0, 0.0)),
    ("LeftToeBase", "LeftFoot", (0.0, 8.0, 12.0), (0.0, 0.0, 0.0)),
    ("LeftToe_End", "LeftToeBase", (0.0, 0.0, 6.0), (0.0, 0.0, 0.0)),
    ("RightUpLeg", "Hips", (-9.0, -5.0, 0.0), (0.0, 0.0, 180.0)),
    ("RightLeg", "RightUpLeg", (0.0, 42.0, 0.0), (0.0, 0.0, 0.0)),
    ("RightFoot", "RightLeg", (0.0, 43.0, 0.0), (0.0, 0.0, 0.0)),
    ("RightToeBase", "RightFoot", (0.0, 8.0, 12.0), (0.0, 0.0, 0.0)),
    ("RightToe_End", "RightToeBase", (0.0, 0.0, 6.0), (0.0, 0.0, 0.0)),
]
for side, sign in (("Left", 1.0), ("Right", -1.0)):
    # Mixamo arm bones point along their local +Y: a -90 / +90 degree Z PreRotation lays them out
    BONES += [
        ("%sShoulder" % side, "Spine2", (sign * 5.0, 12.0, 0.0), (0.0, 0.0, -sign * 90.0)),
        ("%sArm" % side, "%sShoulder" % side, (0.0, 12.0, 0.0), (0.0, 0.0, 0.0)),
        ("%sForeArm" % side, "%sArm" % side, (0.0, 27.0, 0.0), (0.0, 0.0, 0.0)),
        ("%sHand" % side, "%sForeArm" % side, (0.0, 25.0, 0.0), (0.0, 0.0, 0.0)),
    ]
    for finger, offset in (("Thumb", (-sign * 0.0, 3.0, 3.0)), ("Index", (0.0, 9.0, 2.5)),
                           ("Middle", (0.0, 9.5, 0.5)), ("Ring", (0.0, 9.0, -1.5)), ("Pinky", (0.0, 8.0, -3.5))):
        BONES += [
            ("%sHand%s1" % (side, finger), "%sHand" % side, offset, (0.0, 0.0, 0.0)),
            ("%sHand%s2" % (side, finger), "%sHand%s1" % (side, finger), (0.0, 3.5, 0.0), (0.0, 0.0, 0.0)),
            ("%sHand%s3" % (side, finger), "%sHand%s2" % (side, finger), (0.0, 3.0, 0.0), (0.0, 0.0, 0.0)),
        ]


def animation(name, frame):
    """(translation, rotation) curves per animated bone at `frame` (None: not animated)."""
    t = frame / (FRAMES - 1)
    wave = math.sin(t * math.pi)
    if name == "Hips":
        return (0.0 + 4.0 * wave, 100.0 - 10.0 * wave, 30.0 * t), (0.0, 25.0 * wave, 0.0)
    if name == "Spine1":
        return None, (15.0 * wave, 0.0, 5.0 * wave)
    if name == "Neck":
        return None, (-10.0 * wave, 20.0 * wave, 0.0)
    if name == "LeftArm":
        return None, (30.0 * wave, 10.0 * wave, 60.0 * wave)
    if name == "LeftForeArm":
        return None, (0.0, 0.0, 70.0 * wave)
    if name == "LeftHand":
        return None, (20.0 * wave, -35.0 * wave, 10.0 * wave)
    if name == "RightArm":
        return None, (-20.0 * wave, 0.0, -45.0 * wave)
    if name == "RightHand":
        return None, (0.0, 50.0 * wave, 0.0)
    if name == "RightHandIndex1":
        return None, (0.0, 0.0, -60.0 * wave)
    if name == "LeftUpLeg":
        return None, (-70.0 * wave, 0.0, 10.0 * wave)
    if name == "LeftLeg":
        return None, (80.0 * wave, 0.0, 0.0)
    if name == "RightFoot":
        return None, (25.0 * wave, 0.0, 0.0)
    return None


# ---------------------------------------------------------------------------
# Scene as a generic node tree: (name, [props], [children]). Object names are Name("Class", "name").

class Name:
    def __init__(self, cls, name):
        self.cls = cls
        self.name = name


class Arr(list):
    """A typed array property: kind "d" (float64), "f" (float32) or "l" (int64)."""

    def __init__(self, kind, values):
        super().__init__(values)
        self.kind = kind


class Short(int):
    pass


def P(name, ptype, label, flags, *values):
    return ("P", [name, ptype, label, flags] + list(values), [])


def build_scene():
    ids = iter(range(1000, 10 ** 6))
    objects = []
    connections = []

    def model(name, kind, props, parent_id):
        uid = next(ids)
        objects.append(("Model", [uid, Name("Model", name), kind], [
            ("Version", [232], []),
            ("Properties70", [], props),
            ("Shading", ["Y"], []),
            ("Culling", ["CullingOff"], []),
        ]))
        connections.append(("C", ["OO", uid, parent_id], []))
        return uid

    uid_of = {}
    for name, parent, trans, pre in BONES:
        props = [P("RotationActive", "bool", "", "", 1), P("InheritType", "enum", "", "", 1)]
        if any(pre):
            props.insert(0, P("PreRotation", "Vector3D", "Vector", "", *pre))
        props.append(P("Lcl Translation", "Lcl Translation", "", "A", *trans))
        uid_of[name] = model("mixamorig:" + name, "LimbNode", props,
                             uid_of[parent] if parent else 0)

    model("Body_Geo", "Mesh", [P("Lcl Translation", "Lcl Translation", "", "A", 0.0, 50.0, 0.0)], 0)
    model("Unrelated_Helper", "Null", [P("Lcl Rotation", "Lcl Rotation", "", "A", 90.0, 0.0, 0.0)], 0)

    stack = next(ids)
    layer = next(ids)
    stop = (FRAMES - 1) * KTIME_PER_SECOND // FPS
    objects.append(("AnimationStack", [stack, Name("AnimStack", "mixamo.com"), ""], [
        ("Properties70", [], [P("LocalStop", "KTime", "Time", "", stop), P("ReferenceStop", "KTime", "Time", "", stop)])]))
    objects.append(("AnimationLayer", [layer, Name("AnimLayer", "BaseLayer"), ""], []))
    connections.append(("C", ["OO", layer, stack], []))

    times = Arr("l", [f * KTIME_PER_SECOND // FPS for f in range(FRAMES)])
    for name, _, _, _ in BONES:
        frames = [animation(name, f) for f in range(FRAMES)]
        for channel, prop, index in (("T", "Lcl Translation", 0), ("R", "Lcl Rotation", 1)):
            values = [v for v in (fr[index] for fr in frames if fr is not None) if v is not None]
            if not values:
                continue
            node = next(ids)
            defaults = values[0]
            objects.append(("AnimationCurveNode", [node, Name("AnimCurveNode", channel), ""], [
                ("Properties70", [], [P("d|X", "Number", "", "A", defaults[0]), P("d|Y", "Number", "", "A", defaults[1]),
                                      P("d|Z", "Number", "", "A", defaults[2])])]))
            connections.append(("C", ["OO", node, layer], []))
            connections.append(("C", ["OP", node, uid_of[name], prop], []))
            for axis in range(3):
                curve = next(ids)
                objects.append(("AnimationCurve", [curve, Name("AnimCurve", ""), ""], [
                    ("Default", [defaults[axis]], []),
                    ("KeyVer", [4009], []),
                    ("KeyTime", [times], []),
                    ("KeyValueFloat", [Arr("f", [v[axis] for v in values])], []),
                    ("KeyAttrFlags", [Arr("l", [8456])], []),
                    ("KeyAttrRefCount", [Arr("l", [FRAMES])], []),
                ]))
                connections.append(("C", ["OP", curve, node, "d|" + "XYZ"[axis]], []))

    return [
        ("FBXHeaderExtension", [], [("FBXHeaderVersion", [1003], []), ("FBXVersion", [7400], []),
                                    ("Creator", ["JA-Mixamo-Importer test generator"], [])]),
        ("GlobalSettings", [], [("Version", [1000], []), ("Properties70", [], [
            P("UpAxis", "int", "Integer", "", 1), P("UpAxisSign", "int", "Integer", "", 1),
            P("FrontAxis", "int", "Integer", "", 2), P("FrontAxisSign", "int", "Integer", "", 1),
            P("CoordAxis", "int", "Integer", "", 0), P("CoordAxisSign", "int", "Integer", "", 1),
            P("UnitScaleFactor", "double", "Number", "", 1.0),
            P("TimeMode", "enum", "", "", 6), P("CustomFrameRate", "double", "Number", "", -1.0)])]),
        ("Objects", [], objects),
        ("Connections", [], connections),
        ("Takes", [], [("Current", ["mixamo.com"], [])]),
    ]


# ---------------------------------------------------------------------------
# ASCII

def ascii_value(v):
    if isinstance(v, Name):
        return '"%s::%s"' % (v.cls, v.name)
    if isinstance(v, str):
        return '"%s"' % v
    if isinstance(v, float):
        return repr(v)
    return str(v)


def write_ascii(path, nodes):
    lines = ["; FBX 7.4.0 project file", "; synthetic Mixamo-like test scene", ""]

    def emit(node, depth):
        name, props, children = node
        pad = "\t" * depth
        if len(props) == 1 and isinstance(props[0], Arr):
            arr = props[0]
            lines.append("%s%s: *%d {" % (pad, name, len(arr)))
            lines.append("%s\ta: %s" % (pad, ",".join(ascii_value(float(v) if arr.kind != "l" else int(v)) for v in arr)))
            lines.append("%s}" % pad)
            return
        head = "%s%s: %s" % (pad, name, ", ".join(ascii_value(p) for p in props))
        if children:
            lines.append(head.rstrip() + " {")
            for c in children:
                emit(c, depth + 1)
            lines.append("%s}" % pad)
        else:
            lines.append(head)

    for n in nodes:
        emit(n, 0)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Binary

def binary_prop(v, compress):
    if isinstance(v, Name):
        raw = ("%s\x00\x01%s" % (v.name, v.cls)).encode("utf-8")
        return b"S" + struct.pack("<I", len(raw)) + raw
    if isinstance(v, str):
        raw = v.encode("utf-8")
        return b"S" + struct.pack("<I", len(raw)) + raw
    if isinstance(v, Arr):
        fmt = {"d": "d", "f": "f", "l": "q"}[v.kind]
        data = struct.pack("<%d%s" % (len(v), fmt), *v)
        encoding = 0
        if compress:
            data, encoding = zlib.compress(data), 1
        return v.kind.encode() + struct.pack("<III", len(v), encoding, len(data)) + data
    if isinstance(v, Short):
        return b"Y" + struct.pack("<h", v)
    if isinstance(v, float):
        return b"D" + struct.pack("<d", v)
    if isinstance(v, int):
        if -2 ** 31 <= v < 2 ** 31:
            return b"I" + struct.pack("<i", v)
        return b"L" + struct.pack("<q", v)
    raise TypeError(v)


def write_binary(path, nodes, version, compress):
    wide = version >= 7500
    header = struct.Struct("<QQQB" if wide else "<IIIB")
    null = b"\x00" * header.size

    def encode(node, offset):
        name, props, children = node
        pbytes = b"".join(binary_prop(p, compress) for p in props)
        name_b = name.encode("ascii")
        body_start = offset + header.size + len(name_b) + len(pbytes)
        body = b""
        for c in children:
            body += encode(c, body_start + len(body))
        if children:
            body += null
        end = body_start + len(body)
        return header.pack(end, len(props), len(pbytes), len(name_b)) + name_b + pbytes + body

    out = b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", version)
    for n in nodes:
        out += encode(n, len(out))
    out += null
    with open(path, "wb") as f:
        f.write(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    nodes = build_scene()
    write_ascii(os.path.join(OUT, "mixamo_synth_ascii.fbx"), nodes)
    write_binary(os.path.join(OUT, "mixamo_synth_74.fbx"), nodes, 7400, compress=False)
    write_binary(os.path.join(OUT, "mixamo_synth.fbx"), nodes, 7500, compress=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
