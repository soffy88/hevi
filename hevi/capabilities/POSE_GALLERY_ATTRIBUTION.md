# Pose gallery attribution

Method and metadata index only. No image, no upstream text, and no
upstream code is copied into hevi.

- Source repository: anhao/ai-pose-gallery-zh — Chinese edition of
  an AI pose reference gallery.
- Original author and gallery: ギア (@giaaibusi),
  https://ai-pose-gallery.pages.dev/ . The Chinese edition is a
  translation/arrangement of that gallery.
- Upstream license field: NOASSERTION (GitHub API, checked
  2026-10-30). The repository LICENSE states MIT for the source
  code only (index.html, scripts/, _headers). The images under
  img/ and thumbs/ and the original data under data/ belong to
  the original author; they are NOT covered by MIT.
- Use in hevi: non-commercial reference only. The bundled file
  `pose_gallery_data/pose_index.json` contains metadata and
  relative paths only (288 pose groups, 1439 pose-by-view records,
  4 systems, 26 categories, 5 views). Image files are never
  committed to hevi and are resolved at runtime from a gallery
  checkout configured with `HEVI_POSE_GALLERY_HOME`.
- Scope decision (owner, 2026-10-28): do not consider commercial
  licensing, do not use commercially, absorb all four systems
  including the sexy and two-person systems as reference. If the
  original author objects, remove the gallery checkout and the
  index.
- Upstream comparison (2026-10-30, foreground check): upstream
  pushed 2026-10-30 06:18 UTC (3,850 stars / 991 forks at check
  time, up from 46 stars on 2026-10-27). The pose data itself is
  unchanged: `data/pose-zh.json` (554,949 bytes), `data/pose.json`
  (525,690 bytes) and `data/meta-zh.json` match the local copy by
  git blob SHA. The intervening pushes only expanded the README
  and added `skills/pose-reference-all` (an agent skill whose
  usage note — reference the pose skeleton only, never clothing,
  hairstyle or art style — is followed here as method). The
  upstream skill itself was not installed or copied.
- Local reference copy (Mica VM): `~/workspace/references/ai-pose-gallery-zh/`
  (667 MB, 1,439 thumbs + 1,439 images, 0 missing, verified
  2026-10-28 and re-verified 2026-10-30). The upstream
  `skills/` directory is not in that copy; it is not needed for
  the index.
- Ubuntu26 checkout: the gallery was NOT present on ubuntu26 at
  configuration time. Point hevi at a copy there in one of two
  ways: (a) copy the 667 MB directory to the same relative path
  (`~/workspace/references/ai-pose-gallery-zh/` for user soffy)
  with a tarball over scp — do not use `git clone` through the
  proxy; or (b) set `HEVI_POSE_GALLERY_HOME` to the checkout path
  on that machine. Until a checkout exists there, `check_gallery`
  reports every file missing by name and strict resolution fails
  by name; the capability never claims a picture exists.
- Regeneration: after any upstream pose-data change, re-run
  `pose_gallery_data/generate_pose_index.py`, verify the new
  counts, and update this file and `tests/test_pose_library.py`.
