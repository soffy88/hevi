#!/usr/bin/env bash
# Motion Canvas 工程脚手架（官方 create 的非交互等价命令 + 无头渲染依赖）。
# 用法: bash scaffold.sh <目标目录> [工程名]
# 零付费:仅 npm 官方 registry。node_modules 约 274MB,工程请放在仓库外。
set -euo pipefail

TARGET="${1:?usage: scaffold.sh <target-dir> [project-name]}"
NAME="${2:-$(basename "$TARGET")}"

# ubuntu26: node 在 nvm 下,登录 PATH 没有
if ! command -v node >/dev/null 2>&1; then
  for d in "$HOME"/.nvm/versions/node/*/bin; do
    [ -x "$d/node" ] && export PATH="$d:$PATH" && break
  done
fi
command -v node >/dev/null 2>&1 || { echo "FAIL: node not found (nvm?)" >&2; exit 2; }

PARENT="$(dirname "$TARGET")"
mkdir -p "$PARENT"
cd "$PARENT"

# create 3.17.2 的 prompts 可被 minimist 参数覆盖 => 全非交互
npm create @motion-canvas@latest -- \
  --name "$NAME" --path "$(basename "$TARGET")" \
  --language ts --plugins ffmpeg

cd "$TARGET"
npm install
# 代码高亮(Code + Lezer)+ 无头渲染驱动(playwright-core 只含驱动,不下浏览器)
npm i @lezer/javascript
npm i -D playwright-core

echo "OK: scaffolded Motion Canvas project at $TARGET"
echo "Render:  node <hevi>/hevi/skills/motion-canvas/tools/render.mjs $TARGET"
