#!/usr/bin/env bash
# Reuse the canonical Remotion install for the anidoodle render adapter.
#
# The adapter asks for `remotion`, `@remotion/bundler` and `@remotion/renderer`
# at one matching version.  S30 does not install a second copy: it links the
# packages the repository already builds with (hevi-remotion, 4.0.486) into the
# vendored engine's node_modules, where the adapter's require() looks.  The API
# image runs the same steps in deploy/Dockerfile.api.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="${1:-${HEVI_REMOTION_NODE_MODULES:-$root/hevi-remotion/node_modules}}"
dst="$root/third_party/anidoodle/engine/node_modules"
test -d "$src/remotion" || { echo "no remotion in $src" >&2; exit 1; }
mkdir -p "$dst/@remotion"
for pkg in remotion react react-dom; do
  ln -sfn "$src/$pkg" "$dst/$pkg"
done
for pkg in bundler renderer; do
  ln -sfn "$src/@remotion/$pkg" "$dst/@remotion/$pkg"
done
# The headless shell Remotion renders with: reuse the one hevi-remotion already
# installed, so the adapter never downloads a second browser into the engine.
if [ -e "$dst/.remotion" ] && [ ! -L "$dst/.remotion" ]; then
  echo "replacing the engine's own Remotion browser cache with a link to $src/.remotion" >&2
  rm -rf "$dst/.remotion"
fi
ln -sfn "$src/.remotion" "$dst/.remotion"
ver="?"; if command -v node >/dev/null 2>&1; then ver="$(node -p "require('$src/remotion/package.json').version")"; fi
echo "linked remotion $ver from $src"
