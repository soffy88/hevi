"""ComfyUI 客户端 —— H3 / FlashVSR / RIFE 工作流共用(串行队列 + 占位符填参)。

设计:
  - 工作流模板是 API 格式 JSON(node_id → {class_type, inputs}),允许用户直接改/换
    (约定文件 `h3_w4a8_zh.json` 等)。客户端只做两件事:占位符替换 + 按 class_type
    的输入填参/清参,不做节点图的领域假设——模板缺节点时给清晰报错而不是猜。
  - 占位符约定:`__TOKEN__`(字符串值里出现即替换;整值占位自动转类型)。
  - 参考图:模板里放显式 `LoadImage` 节点(值 = `__REF_0__`/`__REF_1__`/…),客户端
    上传图片后把占位符换成 ComfyUI 侧文件名;多余的 ref 节点与对应链接自动裁剪。
  - 串行:模块级 asyncio.Lock(`H3_SERIAL=1` 默认开)。调用方(provider)另持
    GpuScheduler 锁,两条纪律叠加,与 hevi 现网"一次只跑一个本地生成"一致。
  - 下载:history 里任一节点输出出现第一个 .mp4 就取(兼容 VHS_VideoCombine /
    SaveVideo 两种产物结构)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8188"
_DEFAULT_TIMEOUT_S = 1800.0  # H3 W4A8 单镜 5~8s 在 8GB 卡上可达十几分钟
_POLL_INTERVAL_S = 2.0
#: 生成帧数按 17k+5 网格对齐(H3 训练网格,节点 tooltip 原文)。
_GRID_K = 17
_GRID_REMAINDER = 5
_PLACEHOLDER_RE = re.compile(r"__[A-Z0-9_]+__")


class H3ComfyError(Exception):
    """ComfyUI 调用失败(不可达/校验失败/执行失败/超时/产物缺失)。"""


def h3_length_for_duration(duration_s: float, *, fps: int = 24) -> int:
    """目标秒数 → H3 length(帧数)。24fps,对齐 17k+5 网格:
        5s → 124(17×7+5),6s → 158? 否——144 → 158(144%17=8,(5-8)%17=14)。
    与官方模板 ComfyMathExpression 同式:max(5, round(a*24)) + (5 - …%17) % 17。
    """
    frames = max(5, round(max(0.0, float(duration_s)) * fps))
    snapped = frames + (_GRID_REMAINDER - frames % _GRID_K) % _GRID_K
    return min(snapped, 3600)


def _coerce(value: Any, placeholder: str) -> Any:
    """占位符替换后的类型转换:整值占位转 int,其余保留原类型(JSON 数字/字符串直传)。"""
    if placeholder in (
        "__LENGTH__",
        "__SEED__",
        "__WIDTH__",
        "__HEIGHT__",
        "__MULTIPLIER__",
        "__DURATION__",
        "__STEPS__",
    ):
        return int(value)
    return value


def _fill_value(value: Any, fills: dict[str, Any]) -> Any:
    if isinstance(value, str):
        match = _PLACEHOLDER_RE.search(value)
        if match and value == match.group(0) and match.group(0) in fills:
            return _coerce(fills[match.group(0)], match.group(0))
        for ph in sorted(fills, key=len, reverse=True):
            if ph in value:
                value = value.replace(ph, str(fills[ph]))
        return value
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
        # 图链接 ["node_id", slot] —— 递归填节点名(模板里链接也可能用占位)
        return [_fill_value(v, fills) for v in value]
    if isinstance(value, dict):
        return {k: _fill_value(v, fills) for k, v in value.items()}
    return value


class ComfyClient:
    """线程安全的 ComfyUI HTTP 客户端(串行队列)。"""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float | None = None,
        serial: bool | None = None,
        workflows_dir: Path | None = None,
    ) -> None:
        self.base_url = str(base_url or os.getenv("H3_COMFY_URL") or _DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = float(
            timeout_s
            if timeout_s is not None
            else os.getenv("H3_SHOT_TIMEOUT_S", str(_DEFAULT_TIMEOUT_S))
        )
        # H3_SERIAL=1(默认):串行队列,一次一个任务(8GB 纪律)。
        self.serial = bool(os.getenv("H3_SERIAL", "1") == "1") if serial is None else serial
        self.workflows_dir = Path(
            workflows_dir or os.getenv("H3_WORKFLOWS_DIR", "")
            or (Path(__file__).resolve().parent / "workflows")
        )
        self._lock = asyncio.Lock()

    # ── 健康 ────────────────────────────────────────────────────────────────

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{self.base_url}/system_stats")
                r.raise_for_status()
                return True
        except Exception as e:
            logger.warning("ComfyUI health check failed (%s): %s", self.base_url, e)
            return False

    # ── 工作流模板 ──────────────────────────────────────────────────────────

    def load_workflow(self, name: str) -> dict[str, Any]:
        """加载 API 格式工作流模板(JSON)。name 可带 .json 后缀。"""
        path = self.workflows_dir / (name if name.endswith(".json") else f"{name}.json")
        if not path.exists():
            raise H3ComfyError(f"H3 workflow 模板不存在: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise H3ComfyError(f"H3 workflow 模板不是合法 JSON: {path}: {e}") from e
        if not isinstance(data, dict) or not all(
            isinstance(n, dict) and "class_type" in n for n in data.values()
        ):
            raise H3ComfyError(
                f"H3 workflow 模板必须是 API 格式(node_id → {{class_type, inputs}}): {path}"
            )
        return data

    @staticmethod
    def _ref_nodes(workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """模板里的参考图节点:(node_id, node) —— class_type=LoadImage 且 image 是
        `__REF_N__` 占位符(按 N 排序)。"""
        nodes: list[tuple[str, dict[str, Any]]] = []
        for nid, node in workflow.items():
            if node.get("class_type") == "LoadImage":
                img = (node.get("inputs") or {}).get("image", "")
                m = re.fullmatch(r"__REF_(\d+)__", str(img))
                if m:
                    nodes.append((nid, node))
        nodes.sort(
            key=lambda kv: int(
                re.fullmatch(r"__REF_(\d+)__", str(kv[1]["inputs"]["image"])).group(1)  # type: ignore[union-attr]
            )
        )
        return nodes

    def build_workflow(
        self,
        template: dict[str, Any] | str,
        *,
        prompt: str = "",
        length: int = 124,
        width: int = 768,
        height: int = 1344,
        seed: int | None = None,
        output_prefix: str = "h3",
        ref_images: Sequence[Path | str] = (),
        extra_fills: dict[str, Any] | None = None,
        workflows_dir: Path | None = None,
    ) -> dict[str, Any]:
        """模板 + 填参 → 可提交的 API workflow。

        - 参考图:按 `__REF_0__…__REF_N__` 节点顺序填入(不足 N 的裁剪节点与链接)。
        - 占位符:__PROMPT__/__LENGTH__/__WIDTH__/__HEIGHT__/__SEED__/__OUTPUT__/…
        - seed 未给 → 时间随机(与 omodul 每变体换种子的哲学一致,保证重试不同)。
        """
        import copy

        if isinstance(template, str):
            if workflows_dir is not None:
                prev = self.workflows_dir
                self.workflows_dir = workflows_dir
                try:
                    workflow = self.load_workflow(template)
                finally:
                    self.workflows_dir = prev
            else:
                workflow = self.load_workflow(template)
        else:
            workflow = copy.deepcopy(template)

        ref_nodes = self._ref_nodes(workflow)
        ref_paths = [Path(p) for p in ref_images]
        # 裁剪多余的 ref 节点:保留前 len(ref_paths) 个,移除其余 + 解链。
        drop = {nid for nid, _ in ref_nodes[len(ref_paths) :]}
        for node in workflow.values():
            if node.get("class_type") == "MiniMaxH3ReferenceToVideo":
                inputs = node.setdefault("inputs", {})
                for key in [k for k in inputs if k.startswith("ref_image_")]:
                    link = inputs[key]
                    if isinstance(link, list) and link and link[0] in drop:
                        inputs.pop(key, None)
        for nid in drop:
            workflow.pop(nid, None)

        fills: dict[str, Any] = {
            "__PROMPT__": prompt,
            "__LENGTH__": length,
            "__WIDTH__": int(width),
            "__HEIGHT__": int(height),
            "__SEED__": int(seed) if seed is not None else int.from_bytes(os.urandom(4), "big"),
            "__OUTPUT__": output_prefix,
        }
        for i, p in enumerate(ref_paths[: len(ref_nodes)]):
            fills[f"__REF_{i}__"] = str(p)
        fills.update(extra_fills or {})

        return cast(dict[str, Any], _fill_value(workflow, fills))

    # ── 上传 ────────────────────────────────────────────────────────────────

    async def upload_input(
        self, file_path: Path | str, *, mime: str = "application/octet-stream"
    ) -> str:
        """上传任意文件到 ComfyUI input 目录(图/音频共用 /upload/image)。"""
        path = Path(file_path)
        if not path.exists():
            raise H3ComfyError(f"上传文件不存在: {path}")
        async with httpx.AsyncClient(timeout=120.0) as client:
            with path.open("rb") as f:
                r = await client.post(
                    f"{self.base_url}/upload/image",
                    data={"overwrite": "true"},
                    files={"image": (path.name, f, mime)},
                )
            r.raise_for_status()
            data = r.json()
        name = data.get("name")
        subfolder = data.get("subfolder") or ""
        if not name:
            raise H3ComfyError(f"上传失败(无 name): {path} → {data}")
        return f"{subfolder}/{name}" if subfolder else name

    async def upload_image(self, image_path: Path | str) -> str:
        """上传参考图,返回 ComfyUI 侧文件名(可带 subfolder 前缀,直接填 LoadImage.image)。"""
        return await self.upload_input(image_path, mime="image/png")

    # ── 队列与轮询 ─────────────────────────────────────────────────────────

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        """提交 workflow → prompt_id。校验失败抛 H3ComfyError(带 node_errors)。"""
        payload = {"prompt": workflow}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{self.base_url}/prompt", json=payload)
        if r.status_code != 200:
            try:
                body = r.json()
                err = body.get("error", {})
                node_errors = body.get("node_errors", {})
                raise H3ComfyError(
                    f"ComfyUI 校验失败: {err.get('message', r.text)} "
                    f"nodes={list(node_errors or {})}"
                )
            except ValueError:
                raise H3ComfyError(
                    f"ComfyUI 提交失败 HTTP {r.status_code}: {r.text[:300]}"
                ) from None
        return str(r.json()["prompt_id"])

    async def wait_prompt(
        self, prompt_id: str, timeout_s: float | None = None
    ) -> dict[str, Any]:
        """轮询 /history/{prompt_id} 直到完成/失败,返回 history 条目。"""
        deadline = asyncio.get_event_loop().time() + (timeout_s or self.timeout_s)
        # 单请求 60s:Comfy 推理时 event loop 会堵,/history 经常 >15s 才回
        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                try:
                    r = await client.get(f"{self.base_url}/history/{prompt_id}")
                except httpx.ReadTimeout:
                    if asyncio.get_event_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(_POLL_INTERVAL_S)
                    continue
                r.raise_for_status()
                hist = r.json()
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed") or status.get("status_str") == "success":
                        return cast(dict[str, Any], entry)
                    if status.get("status_str") in ("error", "failed") or entry.get("error"):
                        raise H3ComfyError(
                            f"ComfyUI 执行失败: {json.dumps(entry.get('error') or status)[:500]}"
                        )
                if asyncio.get_event_loop().time() >= deadline:
                    raise H3ComfyError(
                        f"ComfyUI 任务超时({timeout_s or self.timeout_s:.0f}s): {prompt_id}"
                    )
                await asyncio.sleep(_POLL_INTERVAL_S)
    @staticmethod
    def find_video_output(entry: dict[str, Any]) -> dict[str, Any] | None:
        """history 条目里找第一个 mp4 输出。

        兼容三种产物结构:VHS_VideoCombine 的 videos/gifs、新 io 节点 SaveVideo 的
        images(带 animated=true)、以及个别节点的 video 键。
        """
        outputs = entry.get("outputs", {})
        for node_out in outputs.values():
            for key in ("videos", "gifs", "images"):
                for item in node_out.get(key, []) or []:
                    if str(item.get("filename", "")).lower().endswith(".mp4"):
                        return cast(dict[str, Any], item)
        for node_out in outputs.values():
            vid = node_out.get("video")
            if isinstance(vid, str) and vid.lower().endswith(".mp4"):
                return {"filename": Path(vid).name, "subfolder": "", "type": "output"}
            if isinstance(vid, list) and vid:
                first = vid[0]
                if isinstance(first, str) and first.lower().endswith(".mp4"):
                    return {"filename": Path(first).name, "subfolder": "", "type": "output"}
                if isinstance(first, dict) and str(first.get("filename", "")).endswith(".mp4"):
                    return cast(dict[str, Any], first)
        return None

    async def download_output(self, item: dict[str, Any], dest: Path) -> Path:
        """按 history 输出条目下载产物到 dest。"""
        params = {
            "filename": item.get("filename"),
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        }
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=600.0) as client:
            r = await client.get(f"{self.base_url}/view", params=params)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return dest

    async def run_workflow(
        self,
        workflow: dict[str, Any],
        *,
        output_path: Path,
        timeout_s: float | None = None,
    ) -> Path:
        """串行跑一个 workflow,把第一个 mp4 产物下载到 output_path。

        整个调用持有模块级串行锁(H3_SERIAL);provider 层再叠 GpuScheduler 锁。
        """
        async with self._lock:
            prompt_id = await self.queue_prompt(workflow)
            logger.info("ComfyUI task queued: %s → %s", prompt_id, output_path.name)
            entry = await self.wait_prompt(prompt_id, timeout_s=timeout_s)
            item = self.find_video_output(entry)
            if item is None:
                raise H3ComfyError(f"ComfyUI 任务完成但无 mp4 产物: {prompt_id}")
            return await self.download_output(item, output_path)
