# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Blender add-on retargeting Mixamo FBX animations (binary and ASCII) onto Jedi Academy's `_humanoid`
armature as NLA strips. Sibling of `../Blender-JA-XSI-Tools` (same NLA / `g2_sequence_prop` /
`skeleton_root` conventions, same Blender 4.1-5.x helpers) and meant to be used with the jediacademy
add-on (`../Blender-Jedi-Academy-Tools`), which it never imports.

The installed module name is `JA-Mixamo-Importer`: the folder inside the release zip
`Blender-JA-Mixamo-Importer.zip` (`PACKAGE` / `ZIP` in the Makefile, `PACKAGE` in `tests/testutil.py`).
Blender loads legacy add-ons by name, the dashes are fine; code can only `import` it through importlib.

## Commands

- `make` — builds `build/Blender-JA-Mixamo-Importer.zip` and `build/ja_mixamo_importer_doc.pdf`.
- `make pep8` / `make format` — pycodestyle check (what CI runs) / autopep8 fix, config in `.pep8`.
- Tests: `.claude/skills/blender-tests/run_blender_tests.sh 4.1 5.2` (podman), or a local Blender:
  `blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py`.
- CI (`.github/workflows/ci.yml`) is the JA dotXSI add-on's: `smoke-test` (Blender 4.1 and 5.2),
  `typecheck`, `pep8` on PRs, tags and the daily schedule; `nightly` and `release` publish the zip and manual.

## Writing comments, commit messages, PR descriptions, and issues

Keep all four succinct: state the fact/change, skip restating what the diff already shows. A comment
should carry the one thing the code alone doesn't (a non-obvious *why*), not a narration of the *what*.

## Architecture

- `fbx.py` — standard-library-only FBX reader (binary 6.x/7.x incl. 64-bit 7.5+ headers and zlib
  arrays, ASCII), Model tree, Lcl T/R/S curves, frame rate. Transform components only, no matrix math.
- `mixamo_blender_importer.py` — FBX local matrices (full pivot/pre/post formula), retargeting, bake.
- `__init__.py` — operator `import_anim.ja_mixamo_fbx`, menu "JA Mixamo NLA Import (.fbx)".

### Conventions (verified on Raven's _humanoid.gla + Mixamo downloads — don't change without re-checking)

- Mixamo files are Y-up, cm, 30 fps, facing +Z; `(x, y, z) -> (x, -z, y)` makes them face -Y like
  the jediacademy addon's `_humanoid` armature (left = +X on both). Bones are matched without namespace.
- `_humanoid` rests in an A-pose, Mixamo in a T-pose: per-bone rest correction = swing of the target
  bone's Y axis onto the Mixamo bone's aim direction (`SOURCE_AIM`, else first child), then the
  Mixamo bone's world rotation delta.
- Ghoul2 parents fingers and `*hang_tag_bone` to the forearm: `ANATOMICAL_PARENT` positions them
  from the hand. Tag bones share the hand's correction so the saber stays rigid in the hand.
- Only the pelvis is translated (scaled by the hip-height ratio); origin offset (0, 0, -24) as the XSI add-on.

### Blender version support

`bl_info["blender"]` is 4.1. Blender 4.4 introduced slotted actions and 5.0 removed `Action.fcurves`:
FCurve access goes through `get_fcurves` / `new_fcurve` with both paths. CI tests the 4.1 and 5.2 boundaries.

## Testing

`tests/run_tests.py` runs headless cases against `tests/testdata/mixamo_synth*.fbx`, one synthetic
Mixamo-like scene written as binary 7.5 (zlib), binary 7.4 and ASCII by
`tests/tools/generate_test_fbx.py` (standard library only), and a synthetic `_humanoid` armature
(`testutil.make_humanoid`). Real Mixamo downloads and `_humanoid.gla` are not committed (third-party /
proprietary): the `real_files` case uses them when `JA_HUMANOID_GLA` and `JA_MIXAMO_FBX` point to local
copies (and the jediacademy add-on is installed), and is skipped otherwise.

Comparisons are geometric: bone directions against the Mixamo bones', pelvis position, rigid
attachments, with tolerances.

## Releases

Same process as the JA dotXSI add-on (see the `release` skill): SemVer in `bl_info["version"]`;
user-facing changes add a bullet under `\subsection*{next version}` in `ja_mixamo_importer_doc.tex`'s
Changelog (not for internal changes, nor for bugs that never reached `master`); the release commit
message is the GitHub Release body; tag the version-bump commit, not a merge commit, with
`.claude/skills/release/tag_release.sh`. Dropping a Blender version is a major bump.
