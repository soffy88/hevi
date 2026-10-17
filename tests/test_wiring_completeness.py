"""接线完整性检查(2026-07-23)——把"建了没接"这个病做成自动化门,别再靠人肉在排查别的
问题时偶然撞见(已第五次:style_manifesto / §6 三字段 / world[].negative_list / 对白时长 lint)。
那条对白 lint 没接是真金白银:每个超时段白烧两次重掷。

两道检查:
1. **lint_* / enforce_* 函数**:必须从生产入口(路由 handler / main 等 roots)**可达**(传递闭包,
   不是"有任意调用方"——对白 lint 的唯一调用方是同样没接的 lint_beat_and_dialogue_boundary,
   靠"有调用方"根本抓不到)。不可达 → FAIL,除非进 `_FUNC_WHITELIST` 并写明理由。
2. **schema 字段**:必须在生产代码里(schema 定义文件之外)被引用(属性访问或字符串键)。纯死字段
   (定义了从没被任何代码读)→ FAIL,除非进 `_FIELD_WHITELIST` 并写明理由。

名字级调用图(同名跨模块合并),对 lint_/enforce_ 这类独特命名足够;是过近似(可能漏报个别
真死代码),但对"从没接进生产"这个目标够用——它至少保证以后新增的 lint/enforce/字段被强制表态。
"""

from __future__ import annotations

import ast
from pathlib import Path

_HEVI = Path(__file__).resolve().parent.parent / "hevi"

# ── 白名单:确属"暂不接生产"的,写明理由。空理由不允许(值必须非空)。────────────────
_FUNC_WHITELIST: dict[str, str] = {
    # 以下经逐一排查确属"生产路径不可达"(2026-07-23),留档不删,将来接回时从这里移除即可:
    "lint_scene_stage": "仅 scene_stage_extract.py 注释里提到可以喂它,无任何真实调用(V2 未接)",
    "lint_shot_pacing": "唯一调用方 build_narration_episode 自身零调用方(整条死),tongjian 遗留",
    "lint_performance_track": "仅经 V1 shot_list→performance_gen 链可达,而 V1 入口已死",
    "lint_audio_sync": "全代码库零引用(连注释都没有),V1 遗留",
    "lint_copyright": "全代码库零引用,V1 遗留",
}

_FIELD_WHITELIST: dict[str, str] = {
    # 纯 bookkeeping / 人审用字段,设计上就不进生成端(STATUS 字段落地三件套记录)
    "source_design_ref": "纯溯源 bookkeeping,设计上不被生成端读",
    "assumed_details": "LLM 自报推测项,人审用,不进生成",
    # 2026-07-23 接线门首跑揪出的死字段:所属明细 schema 整个没被构造,或字段设默认后从没被读。
    # 属"建了没接"同类遗留,先登记(不删避免动 schema),将来消费到时移除白名单。
    "gravity_compliant": "TearDetail 字段,该 schema 生产零构造,整个未用",
    "transition_from": "PropContactState 字段,该 schema 生产零构造,整个未用",
    "moves_out_of_frame": "PropFramePresence 字段,该 schema 生产零构造,整个未用",
    "evolution_start_s": "AudioAmbient 字段,该 schema 生产零构造,整个未用",
    "evolution_end_s": "AudioAmbient 字段,该 schema 生产零构造,整个未用",
    "base_setup_ref": "CameraCurve 字段,构造时设默认但从没被读",
    "preset_id": "PerformancePreset 字段,构造时设默认但从没被读",
    "scalable_to_duration": "PerformancePreset 字段,构造时设默认但从没被读",
    "duration_hint": "SceneBeat 字段,构造时设默认但从没被读",
    # SPEC-005-V2 史实溯源审计字段:由 tongjian_v2_bridge 设置 + director_works 序列化透传,
    # 设计上不被生成端读(纯审计标签,成片对白反查史料出处用)。同 assumed_details 类。
    "quote_id": "SPEC-005-V2 史实溯源审计字段,桥接设置+序列化透传,设计上不进生成端",
    "dramatized": "SPEC-005-V2 戏剧化改编标注,审计透传,设计上不进生成端",
}

# 生产入口 roots 里,除路由 handler / main 外的显式补充(非 HTTP 入口:worker/cron/CLI)
_EXTRA_ROOTS: set[str] = {
    "run_task",  # 任务 worker 消费入口
    "run_v2_produce",  # 由 produce 路由 handler 触发,显式列入防 handler 检测漏
    "resume_task",
}


def _iter_py_files() -> list[Path]:
    out = []
    for p in _HEVI.rglob("*.py"):
        parts = p.parts
        if "__pycache__" in parts or "alembic" in parts:
            continue
        out.append(p)
    return out


def _is_router_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        src = ast.unparse(dec)
        if "router." in src and any(
            m in src for m in (".get(", ".post(", ".put(", ".patch(", ".delete(")
        ):
            return True
    return False


def _build_graph() -> tuple[dict[str, set[str]], set[str]]:
    """返回 (name -> 它引用的名字集合, roots 名字集合)。"""
    graph: dict[str, set[str]] = {}
    roots: set[str] = set(_EXTRA_ROOTS)
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            refs: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name):
                    refs.add(sub.id)
                elif isinstance(sub, ast.Attribute):
                    refs.add(sub.attr)
            graph.setdefault(node.name, set()).update(refs)
            # roots = 真实生产入口:HTTP 路由 handler + main + _EXTRA_ROOTS(worker/produce 等)。
            # **刻意不把 run_*/_run_* 一律当 root**——那会把 `_run_director_via_tongjian` 这类
            # 已死的 V1 入口也当活入口,反而把死代码"救活"、掩盖真断链。新的活入口(cron/worker)
            # 显式加进 _EXTRA_ROOTS。
            if node.name == "main" or _is_router_handler(node):
                roots.add(node.name)
    return graph, roots


def _reachable(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, ()))
    return seen


def _all_target_funcs() -> set[str]:
    names: set[str] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
                node.name.startswith(("lint_", "enforce_"))
            ):
                names.add(node.name)
    return names


def test_all_lint_and_enforce_funcs_reachable_from_production() -> None:
    graph, roots = _build_graph()
    reachable = _reachable(graph, roots)
    targets = _all_target_funcs()
    unwired = sorted(t for t in targets if t not in reachable and t not in _FUNC_WHITELIST)
    assert not unwired, (
        f"这些 lint_/enforce_ 函数建了但生产路径不可达(接进去,或加进 _FUNC_WHITELIST 并写明理由): "
        f"{unwired}"
    )
    # 白名单不许留空理由,也不许给已接线的函数挂白名单(白名单会腐烂)
    assert all(_FUNC_WHITELIST.values()), "_FUNC_WHITELIST 每条必须写理由"
    stale = sorted(t for t in _FUNC_WHITELIST if t in reachable)
    assert not stale, f"这些函数已接进生产,从 _FUNC_WHITELIST 移除: {stale}"


def _schema_fields() -> dict[str, list[str]]:
    """pipeline_schemas.py 里每个 BaseModel 的字段名 → [模型名]。"""
    schema_file = _HEVI / "director" / "pipeline_schemas.py"
    tree = ast.parse(schema_file.read_text(encoding="utf-8"))
    fields: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(
            isinstance(b, ast.Name) and b.id.endswith(("BaseModel", "Model")) for b in node.bases
        ):
            continue
        for stmt in node.body:
            # 形如 `field: Type = ...` 的注解赋值
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fname = stmt.target.id
                if fname.startswith("_") or fname == "model_config":
                    continue
                fields.setdefault(fname, []).append(node.name)
    return fields


def _prod_references_outside_schema() -> str:
    """schema 定义文件之外的全部生产代码文本(用于查字段是否被引用)。"""
    schema_file = _HEVI / "director" / "pipeline_schemas.py"
    chunks = []
    for path in _iter_py_files():
        if path == schema_file:
            continue
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_all_schema_fields_referenced_in_production() -> None:
    fields = _schema_fields()
    haystack = _prod_references_outside_schema()
    dead: list[str] = []
    for fname in fields:
        if fname in _FIELD_WHITELIST:
            continue
        # 命中任一即算被引用:属性访问 `.field`、字符串键 "field"/'field'、构造/关键字 `field=`。
        # `field=` 捕获 `Model(field=...)` 构造写入(否则只写不读的字段会假报死)。
        if any(tok in haystack for tok in (f".{fname}", f'"{fname}"', f"'{fname}'", f"{fname}=")):
            continue
        dead.append(fname)
    dead.sort()
    assert not dead, (
        f"这些 schema 字段定义了但生产代码(schema 文件外)从没引用(接进去消费,或加进 "
        f"_FIELD_WHITELIST 并写明理由): {dead}"
    )
    assert all(_FIELD_WHITELIST.values()), "_FIELD_WHITELIST 每条必须写理由"
