# Blender JA Mixamo Importer

Blender add-on retargeting [Mixamo](https://www.mixamo.com) FBX animations onto Jedi Academy's
`_humanoid` skeleton, as NLA strips ready for the jediacademy add-on's `.gla` / `animation.cfg`
export. Companion of the JA dotXSI add-on (same NLA conventions).

- **File > Import > JA Mixamo NLA Import (.fbx)**
- Reads binary and ASCII FBX itself (Blender's own FBX importer refuses ASCII files).
- Needs a `skeleton_root` armature: import `_humanoid.gla` (or a `.glm` using it) with the
  jediacademy add-on first.

Install `Blender-JA-Mixamo-Importer.zip` from the releases page with "Install from Disk" in
Blender's add-on preferences (Blender 4.1 or newer). See `ja_mixamo_importer_doc.pdf` for the
settings and the retargeting details.
