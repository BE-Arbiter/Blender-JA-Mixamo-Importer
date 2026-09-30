"""Standard-library-only FBX reader, binary (6.x / 7.x) and ASCII, for skeletal animation.

Only what a Mixamo animation needs: the Model tree with each model's transform properties, the
animation curves connected to their Lcl Translation / Rotation / Scaling, and the frame rate.
Matrix math is left to the caller (Blender's mathutils); this module only hands out the FBX
transform components (degrees, file units, file axes). Testable outside Blender.
"""

import re
import struct
import zlib
from bisect import bisect_right

KTIME_PER_SECOND = 46186158000

# GlobalSettings TimeMode -> frames per second (14 = custom: CustomFrameRate)
TIME_MODES = {
    1: 120.0, 2: 100.0, 3: 60.0, 4: 50.0, 5: 48.0, 6: 30.0, 7: 30.0, 8: 29.97, 9: 29.97,
    10: 25.0, 11: 24.0, 12: 1000.0, 13: 23.976, 15: 96.0, 16: 72.0, 17: 59.94, 18: 119.88,
}

# FBX RotationOrder enum -> Euler order in Blender's notation (same meaning: "XYZ" = X applied first)
ROTATION_ORDERS = ("XYZ", "XZY", "YZX", "YXZ", "ZXY", "ZYX")


class FBXError(Exception):
    pass


class Node:
    __slots__ = ("name", "props", "children")

    def __init__(self, name, props, children):
        self.name = name
        self.props = props
        self.children = children

    def find(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def find_all(self, name):
        return [c for c in self.children if c.name == name]

    def array(self, name):
        """Values of an array property: inline list (binary) or the "a" child (ASCII)."""
        node = self.find(name)
        if node is None:
            return []
        if node.props and isinstance(node.props[0], list):
            return node.props[0]
        a = node.find("a")
        return list(a.props) if a is not None else list(node.props)

    def value(self, name, default=None):
        node = self.find(name)
        return node.props[0] if node is not None and node.props else default


# ---------------------------------------------------------------------------
# Binary

BINARY_MAGIC = b"Kaydara FBX Binary  \x00"
ARRAY_TYPES = {"f": ("f", 4), "d": ("d", 8), "l": ("q", 8), "i": ("i", 4), "b": ("b", 1)}
SCALAR_TYPES = {"Y": ("<h", 2), "C": ("<?", 1), "I": ("<i", 4), "F": ("<f", 4), "D": ("<d", 8), "L": ("<q", 8)}


def _read_binary(data):
    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500
    header = struct.Struct("<QQQB" if wide else "<IIIB")

    def read_node(pos):
        end, num_props, _, name_len = header.unpack_from(data, pos)
        pos += header.size
        if end == 0:
            return None, pos
        name = data[pos:pos + name_len].decode("ascii", "replace")
        pos += name_len
        props = []
        for _ in range(num_props):
            t = chr(data[pos])
            pos += 1
            if t in SCALAR_TYPES:
                fmt, size = SCALAR_TYPES[t]
                props.append(struct.unpack_from(fmt, data, pos)[0])
                pos += size
            elif t in ARRAY_TYPES:
                length, encoding, clen = struct.unpack_from("<III", data, pos)
                pos += 12
                raw = data[pos:pos + clen]
                pos += clen
                if encoding == 1:
                    raw = zlib.decompress(raw)
                fmt, size = ARRAY_TYPES[t]
                props.append(list(struct.unpack_from("<%d%s" % (length, fmt), raw)))
            elif t in "SR":
                length = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                raw = data[pos:pos + length]
                pos += length
                if t == "S":
                    # binary "Name\x00\x01Class" is ASCII's "Class::Name"
                    s = raw.decode("utf-8", "replace")
                    if "\x00\x01" in s:
                        n, c = s.split("\x00\x01", 1)
                        s = "%s::%s" % (c, n)
                    props.append(s)
                else:
                    props.append(raw)
            else:
                raise FBXError("Unknown binary FBX property type %r at %d" % (t, pos - 1))
        children = []
        while pos < end:
            child, pos = read_node(pos)
            if child is None:
                break
            children.append(child)
        return Node(name, props, children), end

    pos = 27
    top = []
    while pos < len(data) - header.size:
        node, pos = read_node(pos)
        if node is None:
            break
        top.append(node)
    return version, Node("", [], top)


# ---------------------------------------------------------------------------
# ASCII

_TOKEN = re.compile(r'"([^"]*)"|(;[^\n]*)|([{}:,\n])|([^\s,:{}";]+)')


def _ascii_value(s):
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _read_ascii(text):
    # (kind, value): kind "s" string, "w" bare word, or the punctuation itself
    tokens = []
    for m in _TOKEN.finditer(text):
        s, comment, punct, word = m.groups()
        if comment is not None:
            continue
        if s is not None:
            tokens.append(("s", s))
        elif punct is not None:
            tokens.append((punct, punct))
        else:
            tokens.append(("w", word))

    pos = 0
    n = len(tokens)

    def parse_children():
        nonlocal pos
        children = []
        while pos < n:
            kind, val = tokens[pos]
            if kind in ("\n", ","):
                pos += 1
                continue
            if kind == "}":
                pos += 1
                return children
            if kind == "w" and pos + 1 < n and tokens[pos + 1][0] == ":":
                name = val
                pos += 2
                props = []
                while pos < n:
                    kind, val = tokens[pos]
                    if kind == ",":
                        pos += 1
                        while pos < n and tokens[pos][0] == "\n":
                            pos += 1
                        continue
                    if kind in ("\n", "}", "{"):
                        break
                    props.append(val if kind == "s" else _ascii_value(val))
                    pos += 1
                sub = []
                if pos < n and tokens[pos][0] == "{":
                    pos += 1
                    sub = parse_children()
                children.append(Node(name, props, sub))
                continue
            pos += 1
        return children

    return Node("", [], parse_children())


def read(path):
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(BINARY_MAGIC):
        _, root = _read_binary(data)
        return root
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if "FBXHeaderExtension" not in text[:4096] and "Objects" not in text:
        raise FBXError("%s is not an FBX file" % path)
    return _read_ascii(text)


# ---------------------------------------------------------------------------
# Scene

def properties70(node):
    """Properties70 of an object: name -> tuple of values (P: name, type, label, flags, values...)."""
    out = {}
    p70 = node.find("Properties70") or node.find("Properties60")
    if p70 is None:
        return out
    for p in p70.children:
        if p.name in ("P", "Property") and p.props:
            vals = p.props[4:] if p.name == "P" else p.props[3:]
            out[p.props[0]] = tuple(vals)
    return out


def split_name(full):
    """ "Model::mixamorig:Hips" -> ("Model", "mixamorig:Hips")."""
    if "::" in full:
        cls, name = full.split("::", 1)
        return cls, name
    return "", full


class Curve:
    def __init__(self, times, values, default):
        self.times = times  # seconds
        self.values = values
        self.default = default

    def sample(self, t):
        times, values = self.times, self.values
        if not times:
            return self.default
        if t <= times[0]:
            return values[0]
        if t >= times[-1]:
            return values[-1]
        i = bisect_right(times, t)
        t0, t1 = times[i - 1], times[i]
        f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        return values[i - 1] + (values[i] - values[i - 1]) * f


class Model:
    """A transform node. Transform components are in the file's units / axes, angles in degrees."""

    def __init__(self, uid, name, kind, props):
        self.uid = uid
        self.name = name
        self.kind = kind  # "LimbNode", "Null", "Mesh", "Root"...
        self.parent = None
        self.children = []
        self.props = props
        # "Lcl Translation" etc. -> [Curve x, y, z] (None where not animated)
        self.curves = {}

    def vec(self, key, default=(0.0, 0.0, 0.0)):
        v = self.props.get(key)
        if not v or len(v) < 3:
            return tuple(default)
        return tuple(float(x) for x in v[:3])

    @property
    def rotation_order(self):
        v = self.props.get("RotationOrder")
        order = int(v[0]) if v else 0
        return ROTATION_ORDERS[order] if 0 <= order < len(ROTATION_ORDERS) else "XYZ"

    @property
    def short_name(self):
        """Name without namespace: "mixamorig:Hips" -> "Hips"."""
        return self.name.rsplit(":", 1)[-1]

    def channel(self, key, t, default):
        """Value of "Lcl Translation" / "Lcl Rotation" / "Lcl Scaling" at time t (None = rest)."""
        base = self.vec(key, default)
        curves = self.curves.get(key)
        if t is None or curves is None:
            return base
        return tuple(c.sample(t) if c is not None else base[i] for i, c in enumerate(curves))

    def transform(self, t=None):
        """FBX transform components at time t (None: the model's own, un-animated values)."""
        return {
            "translation": self.channel("Lcl Translation", t, (0.0, 0.0, 0.0)),
            "rotation": self.channel("Lcl Rotation", t, (0.0, 0.0, 0.0)),
            "scaling": self.channel("Lcl Scaling", t, (1.0, 1.0, 1.0)),
            "rotation_order": self.rotation_order,
            "pre_rotation": self.vec("PreRotation"),
            "post_rotation": self.vec("PostRotation"),
            "rotation_offset": self.vec("RotationOffset"),
            "rotation_pivot": self.vec("RotationPivot"),
            "scaling_offset": self.vec("ScalingOffset"),
            "scaling_pivot": self.vec("ScalingPivot"),
        }


class Scene:
    def __init__(self, root):
        self.models = {}  # uid -> Model
        self.up_axis = 1
        self.up_sign = 1
        self.front_axis = 2
        self.front_sign = 1
        self.coord_axis = 0
        self.coord_sign = 1
        self.unit_scale = 1.0
        self.fps = 30.0
        self._build(root)

    def _build(self, root):
        gs = root.find("GlobalSettings")
        if gs is not None:
            p = properties70(gs)

            def geti(k, d):
                v = p.get(k)
                return int(v[0]) if v else d
            self.up_axis, self.up_sign = geti("UpAxis", 1), geti("UpAxisSign", 1)
            self.front_axis, self.front_sign = geti("FrontAxis", 2), geti("FrontAxisSign", 1)
            self.coord_axis, self.coord_sign = geti("CoordAxis", 0), geti("CoordAxisSign", 1)
            v = p.get("UnitScaleFactor")
            self.unit_scale = float(v[0]) if v else 1.0
            mode = geti("TimeMode", 0)
            if mode == 14:
                v = p.get("CustomFrameRate")
                if v and float(v[0]) > 0:
                    self.fps = float(v[0])
            elif mode in TIME_MODES:
                self.fps = TIME_MODES[mode]

        objects = root.find("Objects")
        if objects is None:
            raise FBXError("The file has no Objects section")

        curve_nodes = {}  # uid -> {"d|X": default...}
        curves = {}  # uid -> Curve
        stacks = []
        for obj in objects.children:
            if len(obj.props) < 2:
                continue
            uid = obj.props[0]
            cls, name = split_name(str(obj.props[1]))
            if obj.name == "Model":
                kind = obj.props[2] if len(obj.props) > 2 else ""
                self.models[uid] = Model(uid, name, kind, properties70(obj))
            elif obj.name == "AnimationCurveNode":
                curve_nodes[uid] = {"name": name, "props": properties70(obj), "curves": {}, "target": None}
            elif obj.name == "AnimationCurve":
                times = [float(t) / KTIME_PER_SECOND for t in obj.array("KeyTime")]
                values = [float(v) for v in obj.array("KeyValueFloat") or obj.array("KeyValueDouble")]
                default = obj.value("Default", 0.0)
                curves[uid] = Curve(times, values, float(default or 0.0))
            elif obj.name == "AnimationStack":
                stacks.append(uid)

        root_model = Model(0, "RootNode", "Root", {})
        self.root = root_model

        connections = root.find("Connections")
        links = []
        if connections is not None:
            for c in connections.children:
                if c.name in ("C", "Connect") and len(c.props) >= 3:
                    links.append(c.props)

        layer_of_curve_node = {}
        for props in links:
            ctype, child, parent = props[0], props[1], props[2]
            prop = props[3] if len(props) > 3 else None
            if ctype == "OO" and child in self.models:
                model = self.models[child]
                if parent in self.models:
                    model.parent = self.models[parent]
                elif parent == 0:
                    model.parent = root_model
            elif ctype == "OP" and child in curves and parent in curve_nodes:
                curve_nodes[parent]["curves"][prop] = curves[child]
            elif ctype == "OP" and child in curve_nodes and parent in self.models:
                curve_nodes[child]["target"] = (parent, prop)
            elif ctype == "OO" and child in curve_nodes:
                layer_of_curve_node[child] = parent

        for m in self.models.values():
            if m.parent is None:
                m.parent = root_model
            m.parent.children.append(m)

        # Only the first animation layer is used: Mixamo has a single stack / layer
        layers = set(layer_of_curve_node.values())
        first_layer = min(layers) if layers else None
        for uid, cn in curve_nodes.items():
            if cn["target"] is None:
                continue
            if first_layer is not None and layer_of_curve_node.get(uid, first_layer) != first_layer and len(layers) > 1:
                continue
            model_uid, prop = cn["target"]
            if prop not in ("Lcl Translation", "Lcl Rotation", "Lcl Scaling"):
                continue
            chans = [cn["curves"].get(k) for k in ("d|X", "d|Y", "d|Z")]
            if any(chans):
                self.models[model_uid].curves[prop] = chans

    def all_models(self):
        """Models in hierarchy order (parents first), without the implicit root."""
        out = []

        def walk(m):
            for c in m.children:
                out.append(c)
                walk(c)
        walk(self.root)
        return out

    def time_range(self):
        """(first, last) key time in seconds over every animated channel, None if not animated."""
        lo, hi = None, None
        for m in self.models.values():
            for chans in m.curves.values():
                for c in chans:
                    if c is not None and c.times:
                        lo = c.times[0] if lo is None else min(lo, c.times[0])
                        hi = c.times[-1] if hi is None else max(hi, c.times[-1])
        return None if lo is None else (lo, hi)


def load_scene(path):
    return Scene(read(path))
