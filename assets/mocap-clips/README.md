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
