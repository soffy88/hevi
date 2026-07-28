"""INC-003 P0 修复验证:启动一个打了桩的真实 API 进程,三个视频生成函数(happyhorse_animate/
i2v_animate/alibaba_maas_keyframe_generate,见 STATUS.md 六函数清单)全部打桩成瞬时返回——不碰
外部付费视频调用。走完整真实①→⑤链路(真实 REST 端点、真实锁定流程、真实 SubjectService/DB),
到⑤生成的关键帧阶段(本地 SDXL,免费)为止,验证 expected_character_count 判据在**真实链路**
里是否生效(而不是只在本地脚本复现层面成立——上次的教训)。

打桩必须在 uvicorn 真正 import app 之前生效(patch 目标是 scene_render_avatar.py 里已绑定的
名字,不是原始定义模块),否则 app 导入时已经绑好了原始函数引用,后打桩不生效。

用法:python scripts/inc003_p0_verify_server.py [port]  (默认 8124,不冲突已在跑的 8123)
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import uvicorn


async def _stub_video(*, output_path, **_kw):
    Path(output_path).write_bytes(b"stub-video-not-really-called")
    return output_path


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8124

    # 必须在 import hevi.api.main 之前打桩生效——patch() 会按需先 import 目标模块,
    # 之后 app 导入链里任何地方 `from hevi.tongjian.scene_render_avatar import happyhorse_animate`
    # 拿到的都是同一个已打桩的模块属性(sys.modules 缓存,不会重复原始绑定)。
    with (
        patch(
            "hevi.tongjian.scene_render_avatar.happyhorse_animate",
            AsyncMock(side_effect=_stub_video),
        ),
        patch("hevi.tongjian.scene_render_avatar.i2v_animate", AsyncMock(side_effect=_stub_video)),
        patch(
            "hevi.tongjian.scene_render_avatar.alibaba_maas_keyframe_generate",
            AsyncMock(side_effect=_stub_video),
        ),
    ):
        from hevi.api.main import app

        print(
            f"=== INC-003 P0 验证服务器:port={port},三个视频函数已打桩,零花费(除 sdxl 内部中英翻译文本调用)===",
            flush=True,
        )
        uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
