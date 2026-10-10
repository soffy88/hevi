#!/bin/sh
# hevi-gen-engine entrypoint.
#
# 镜像以非 root 的 voicebox 用户运行(CI runtime security gate, 8eb134f0)。上游
# voicebox 的 rocm-entrypoint.sh 无条件 `gosu voicebox`, 非 root 下 gosu 必然
# "failed switching to voicebox: operation not permitted", 容器起不来。
# 这里: 若以 root 启动(例如 ROCm 覆盖层 user: root), 保留上游行为(加入 GPU
# 设备属组后降权); 否则已是 voicebox, 直接 exec。ROCm 非 root 运行时用
# compose 的 group_add 授予 /dev/kfd /dev/dri 属组。
set -e
if [ "$(id -u)" = "0" ]; then
    exec /usr/local/bin/rocm-entrypoint.sh "$@"
fi
exec "$@"
