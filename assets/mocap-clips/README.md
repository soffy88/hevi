# Mocap clips — provenance

Every `clips/<name>.json` is a **2-D joint track derived from the CMU Graphics
Lab Motion Capture Database** (http://mocap.cs.cmu.edu), which is free for all
uses, research and commercial.

* Source: the `una-dinosauria/cmu-mocap` BVH mirror of the CMU database.
* Conversion: `hevi/studio/cmumocap.py` (our own clean-room BVH parser +
  forward kinematics + 2-D projection + normalisation).  No third-party
  converter is used.
* Per-clip source trial: each file records `"source": "CMU <trial>"`.

The CMU database requests the following acknowledgement:

> This data was created with funding from NSF EIA-0196217. The database was
> compiled by the CMU Graphics Lab.

## Format

```json
{
  "name": "walk", "source": "CMU 02_01", "plane": "zy", "fps": 30.0,
  "frameCount": 87, "label": "它走起来了", "height": 1.0,
  "frames": [{"hips": [x, y], "chest": [x, y], "...": [x, y]}, ...]
}
```

`x` is horizontal, `y` is height above the ground; both are normalised so the
standing figure is 1.0 tall.  Joints: `hips chest neck head shR elR haR shL
elL haL hipR knR ftR hipL knL ftL`.

## Regenerate

```bash
PYTHONPATH=. .venv/bin/python -m hevi.studio.cmumocap [name ...]
```

BVH trials are cached under `~/.cache/hevi-cmu-mocap/` and fetched through the
`ghfast.top` mirror when GitHub is unreachable.

## Clip catalogue

A machine-readable catalogue lives in `manifest.json` (name, Chinese name,
category, file, skeleton, fps, frames, source trial, CMU trial description,
label, licence).  Regenerate it after adding clips:

```bash
PYTHONPATH=. .venv/bin/python -m hevi.studio.mocap_manifest
```

Trial table: `hevi/studio/cmumocap.py::TRIALS` (clip name → CMU subject/trial,
projection plane, spoken label).  Studio code reads the library through
`hevi/studio/mocap.py::list_mocap()` (scans `clips/`) — adding a clip JSON plus
a `TRIALS` entry registers it; no other code changes needed.

| name | 中文 | category | source | 时长 |
|---|---|---|---|---|
| walk | 走路 | locomotion | CMU 02_01 | 2.9s |
| run | 跑步 | locomotion | CMU 09_01 | 1.3s |
| sprint | 冲刺 | locomotion | CMU 127_03 (Run) | 2.8s |
| march | 原地踏步 | locomotion | CMU 15_01 | 46.1s |
| shuffle | 悄悄挪动 | locomotion | CMU 77_29 | 17.6s |
| jump | 跳跃 | locomotion | CMU 13_11 | 3.5s |
| kick | 踢腿 | combat | CMU 10_01 | 6.7s |
| punch | 拳击 | combat | CMU 13_17 (boxing) | 40.4s |
| roll | 翻滚 | stunt | CMU 111_21 (Roll over) | 19.0s |
| knockdown | 被击倒 | stunt | CMU 90_16 (fall on face) | 6.1s |
| getup | 起身 | stunt | CMU 111_06 (Get up from floor) | 12.7s |
| victory | 欢呼跳跃 | celebration | CMU 16_03 (high jump) | 3.4s |
| sit | 坐下 | pose | CMU 13_01 | 19.3s |
| wave | 挥手 | gesture | CMU 141_16 | 2.5s |
| twist | 扭动身体 | dance | CMU 141_12 | 4.8s |
| dance_spin | 转圈舞 | dance | CMU 05_02 | 9.4s |
| dance_glide | 滑步舞 | dance | CMU 05_10 | 6.8s |

Rows with a parenthetical note use a CMU trial whose recorded description is
shown; the clip name/category reflect how hevi uses it.

