"""Subject3D 本地生成(HEVI-ARCHITECTURE.md v3.0 §5.7 主路A的落地,2026-07-13 探路)。

图生3D 摄入(HEVI 总纲的"生成能力全部外采"这条原则原本指向云端 provider——阿里云百炼
的 Tripo-3D API 实测通:workspace 专属端点未开通该模型,公共账户能连通但产品本身要在
百炼控制台手动激活,尚未打通)。soffy 拍板改走本地自建(TripoSR,MIT 协议),不等云端
激活。GPU 显存被同机其他租户的进程占满(见 nvidia-smi,不可挪用),只能走 CPU 推理。

跟 hevi 主环境完全隔离的独立 venv(Python 3.11 + transformers==4.35.0,TripoSR 的
checkpoint 权重命名跟新版 transformers 不兼容),用 subprocess 调用,不 import——
`hevi/video/wan_local_service.py` 调用 Wan2GP 独立 venv 是同一个模式,这里照抄。

产出两样东西,职责不同:
- GLB mesh:身份的"结构真值"(HEVI-ARCHITECTURE.md §5.7.3,verdict 未来可用它当
  identity_distance 的可靠基准,而不是拿 2D 参考图近似)。
- 多机位 2D 渲染帧(front/left/right/back):喂给现有 i2v 管线当 ref_image 来源
  (`hevi/tongjian/scene_render_avatar.py::_canonical()` 的 ref_image 参数,今天早些
  时候已经打通"直接复用真实参考图"这条路,3D 渲染帧只是这条路的另一种输入)。

**已知的真实质量特征(2026-07-13 真实生成 + 真实短剧镜头对比验证过,不是猜测)**:
TripoSR 是速度优先的 feed-forward 重建模型,NeRF 渲染出的 2D 关键帧比原始 2D 照片糊
得多,细节丢失明显——喂进短剧生成管线后,身份一致性 CLIP 分实测低于直接用原始 2D 照片
(0.61 vs 0.77-0.84),真实跑出来认错过人(五官细节不够,下游模型"脑补"出了不同长相)。
`mc_resolution` 参数只影响 GLB 网格精度,不影响 2D 渲染帧清晰度——调这个参数救不了这个
问题,是 render() 本身的渲染分辨率/质量特征。
生产上目前只应该把 3D 渲染帧当"补充候选"(如非正面机位、2D 照片没有对应视角时的兜底),
不应该无条件优先于清晰的 2D 正面参考图——见 tongjian_bridge.py 的来源选择逻辑。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_TRIPOSR_DIR = Path(os.getenv("TRIPOSR_DIR", "/home/soffy/models/triposr"))
_TRIPOSR_PYTHON = _TRIPOSR_DIR / ".venv" / "bin" / "python"
_TRIPOSR_SCRIPT = _TRIPOSR_DIR / "render_views.py"
_TIMEOUT_S = 280.0  # 实测 CPU 端到端(4 机位 + mc_resolution=256)约 172s,留够余量


class Subject3DError(Exception):
    """本地 Subject3D 生成失败(进程非0退出/超时/产物缺失)。"""


async def generate_subject3d(
    image_path: Path,
    *,
    output_dir: Path,
    mc_resolution: int = 256,
    views: tuple[str, ...] = ("front", "left", "right", "back"),
    timeout_s: float = _TIMEOUT_S,
) -> dict[str, str]:
    """单张参考图 → GLB + 多机位渲染帧。返回 `{"glb_path": ..., "views": {"front": ..., ...}}`。

    独立 venv 子进程,CPU 推理(见模块顶部注释:GPU 被同机其他租户占满)。失败/超时
    抛 Subject3DError,不静默降级——3D 生成失败时调用方应该退回 2D 参考图,但那是
    调用方的决策(见 tongjian_bridge.py),这里只如实报告成功或失败。
    """
    if not _TRIPOSR_PYTHON.exists():
        raise Subject3DError(f"TripoSR venv 不存在: {_TRIPOSR_PYTHON}")
    if not image_path.exists():
        raise Subject3DError(f"输入参考图不存在: {image_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(_TRIPOSR_PYTHON),
        str(_TRIPOSR_SCRIPT),
        str(image_path),
        "--output-dir",
        str(output_dir),
        "--mc-resolution",
        str(mc_resolution),
        "--views",
        ",".join(views),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        logger.error("subject3d_local: 子进程超时(%.0fs),kill 掉,不留孤儿进程", timeout_s)
        proc.kill()
        await proc.wait()
        raise Subject3DError(f"TripoSR 子进程超时({timeout_s:.0f}s)") from None

    if proc.returncode != 0:
        raise Subject3DError(
            f"TripoSR 子进程失败(exit {proc.returncode}): {stderr.decode(errors='replace')[:500]}"
        )

    # render_views.py 的最后一行是结果 JSON(前面几行是 torch/transformers 的
    # FutureWarning,混在 stdout 里,只取最后一行非空行)。
    lines = [ln for ln in stdout.decode(errors="replace").splitlines() if ln.strip()]
    if not lines:
        raise Subject3DError("TripoSR 子进程无输出")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise Subject3DError(f"TripoSR 子进程输出不是合法 JSON: {lines[-1][:300]}") from e

    glb_path = result.get("glb_path")
    view_paths = result.get("views") or {}
    if not glb_path or not Path(glb_path).exists():
        raise Subject3DError(f"TripoSR 产出缺 GLB: {result}")
    missing = [v for v, p in view_paths.items() if not Path(p).exists()]
    if missing:
        raise Subject3DError(f"TripoSR 产出缺渲染帧: {missing}")

    logger.info("subject3d_local: %s -> glb=%s views=%s", image_path, glb_path, list(view_paths))
    return result
