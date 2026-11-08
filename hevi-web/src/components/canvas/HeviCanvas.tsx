/**
 * HeviCanvas — 无限画布工作台(完整版)
 * 集成:5类节点+连线校验、主体库/创意辅助/资产库侧栏、
 * 节点右键菜单、`/` 快捷键唤起创意辅助、保存/执行+SSE进度回填。
 */
'use client';

import { useCallback, useState, useEffect, useRef } from 'react';
import ReactFlow, {
  Background, Controls, MiniMap,
  addEdge, useNodesState, useEdgesState,
  type Connection, type Node,
  ReactFlowProvider,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { HeviNode, type HeviNodeData } from './HeviNode';
import { NodePalette } from './NodePalette';
import { NodeContextMenu, type ContextMenuState } from './NodeContextMenu';
import { SubjectLibrary } from '../panels/SubjectLibrary';
import { CreativePanel } from '../panels/CreativePanel';
import { AssetLibrary } from '../panels/AssetLibrary';
import { validateEdge, NODE_META } from '@/lib/canvas-rules';
import { canvasApi, USE_MOCK } from '@/lib/api-client';
import type { NodeType } from '@/types/api';
import { NodeInspector } from './NodeInspector';
import { BetaQuota } from '../home/BetaQuota';
import type { StudioLine, StudioTool } from './NodePalette';

const nodeTypes = { hevi: HeviNode };
let idCounter = 0;
const newId = () => `node-${++idCounter}-${Date.now().toString(36)}`;

type SidePanel = 'subjects' | 'creative' | 'assets';

function CanvasInner() {
  const [nodes, setNodes, onNodesChange] = useNodesState<HeviNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [toast, setToast] = useState<string | null>(null);
  const [panel, setPanel] = useState<SidePanel>('subjects');
  const [ctxMenu, setCtxMenu] = useState<ContextMenuState | null>(null);
  const [executing, setExecuting] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [graphId, setGraphId] = useState<string | null>(null);
  const [nodeBusy, setNodeBusy] = useState<string | null>(null);
  const packFileRef = useRef<HTMLInputElement | null>(null);

  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 2400); };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const toFlowNodes = useCallback((graph: any) => {
    const list = graph.nodes ?? [];
    return list.map((n: Record<string, any>) => {
      const nodeType = String(n.node_type) as NodeType;
      return {
        id: String(n.node_id),
        type: 'hevi' as const,
        position: (n.position as { x: number; y: number }) ?? { x: 0, y: 0 },
        data: {
          nodeType,
          label: String(n.label ?? n.node_id),
          config: (n.config as Record<string, unknown>) ?? {},
          status: n.status as HeviNodeData['status'],
          revision: typeof n.revision === 'number' ? n.revision : undefined,
          locked: Boolean(n.locked),
          review: (n.review as HeviNodeData['review']) ?? null,
          artifacts: (n.artifacts as HeviNodeData['artifacts']) ?? [],
        },
      };
    });
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const toFlowEdges = useCallback((graph: any) => {
    return (graph.edges ?? []).map((e: Record<string, any>, i: number) => ({
      id: String(e.edge_id ?? e.id ?? `e-${i}`),
      source: String(e.from_node_id ?? e.source),
      target: String(e.to_node_id ?? e.target),
      animated: true,
      data: { kind: e.kind, status: e.status },
    }));
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const openGraph = useCallback((graph: any) => {
    const id = String(graph.id ?? graph.graph_id ?? '');
    setGraphId(id || null);
    setNodes(toFlowNodes(graph) as never[]);
    setEdges(toFlowEdges(graph) as never[]);
  }, [setNodes, setEdges, toFlowNodes, toFlowEdges]);

  const reloadGraph = useCallback(async (id: string) => {
    if (USE_MOCK) return;
    try {
      const graph = await canvasApi.load(id);
      openGraph(graph);
    } catch { /* keep the in-memory graph */ }
  }, [openGraph]);

  const onNodeClick = useCallback((_e: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const onPaneClick = useCallback(() => setSelectedNodeId(null), []);

  const updateNodeConfig = useCallback((nodeId: string, patch: Record<string, unknown>) => {
    setNodes(ns => ns.map(n => n.id === nodeId
      ? { ...n, data: { ...n.data, config: { ...n.data.config, ...patch } } }
      : n));
  }, [setNodes]);

  const selectedNode = nodes.find(n => n.id === selectedNodeId) ?? null;

  // 材料包映射:选一个材料包/ manifest JSON 文件,后端映射成画布图后打开。
  // 节点带 prompt 摘要/状态/门徽章,Inspector 可改 prompt 字段。
  const onLoadMaterialPackFile = useCallback(async (file: File) => {
    try {
      const pack = JSON.parse(await file.text()) as Record<string, unknown>;
      const { graph } = await canvasApi.materialPackGraph(pack);
      openGraph(graph);
      flash('材料包图已打开（执行时会先保存）');
    } catch {
      flash('材料包映射失败');
    }
  }, [openGraph]);

  const onConnect = useCallback((conn: Connection) => {
    const f = nodes.find(n => n.id === conn.source);
    const t = nodes.find(n => n.id === conn.target);
    if (!f || !t) return;
    const r = validateEdge(f.data.nodeType, t.data.nodeType);
    if (!r.valid) { flash(r.reason ?? '非法连接'); return; }
    setEdges(eds => addEdge({ ...conn, animated: true }, eds));
  }, [nodes, setEdges]);

  const addNode = useCallback((type: NodeType) => {
    setNodes(ns => [...ns, {
      id: newId(), type: 'hevi',
      position: { x: 140 + Math.random() * 220, y: 90 + Math.random() * 220 },
      data: { nodeType: type, label: NODE_META[type].label },
    }]);
  }, [setNodes]);

  const addToolNode = useCallback((tool: StudioTool) => {
    const nodeType: NodeType = tool.kind === 'tts' || tool.kind === 'publish' ? 'audio'
      : tool.kind === 'watch' || tool.kind === 'nle' ? 'video'
        : tool.kind === 'explainer' || tool.kind === 'script' ? 'script'
          : 'text';
    setNodes((ns) => [...ns, {
      id: newId(), type: 'hevi',
      position: { x: 80 + ns.length * 40, y: 80 + (ns.length % 4) * 80 },
      data: {
        nodeType,
        label: tool.id,
        config: { tool_id: tool.id, content: tool.summary },
      },
    }]);
  }, [setNodes]);

  const applyLine = useCallback((line: StudioLine) => {
    const tools = line.tools.slice(0, 10);
    const ids = tools.map(() => newId());
    setNodes(tools.map((toolId, i) => ({
      id: ids[i]!,
      type: 'hevi' as const,
      position: { x: 80 + i * 200, y: 160 },
      data: {
        nodeType: 'script' as NodeType,
        label: toolId,
        config: { tool_id: toolId, content: line.product, topic: line.product },
      },
    })));
    setEdges(ids.slice(1).map((id, i) => ({
      id: `e-${ids[i]}-${id}`,
      source: ids[i]!,
      target: id,
      animated: true,
    })));
    flash(`已展开产线 ${line.product}`);
  }, [setNodes, setEdges]);

  const onNodeContextMenu = useCallback((e: React.MouseEvent, node: Node) => {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY, nodeId: node.id });
  }, []);

  const onCtxAction = useCallback((action: string, nodeId: string) => {
    if (action === 'delete') {
      setNodes(ns => ns.filter(n => n.id !== nodeId));
      setEdges(es => es.filter(e => e.source !== nodeId && e.target !== nodeId));
    } else if (action === 'duplicate') {
      setNodes(ns => {
        const src = ns.find(n => n.id === nodeId);
        if (!src) return ns;
        return [...ns, { ...src, id: newId(),
          position: { x: src.position.x + 40, y: src.position.y + 40 } }];
      });
    } else if (action === 'execute') {
      const node = nodes.find((n) => n.id === nodeId);
      const toolId = typeof node?.data.config?.tool_id === 'string' ? node.data.config.tool_id : '';
      if (graphId && !USE_MOCK) {
        void rerunNode(nodeId);
        return;
      }
      if (!toolId) {
        flash('画布尚未保存，先点“保存”再重做节点');
        return;
      }
      setNodes((ns) => ns.map((n) => n.id === nodeId
        ? { ...n, data: { ...n.data, status: 'running' } }
        : n));
      import('@/lib/api-client').then(({ studioApi }) =>
        studioApi.invoke(toolId, (node?.data.config ?? {}) as Record<string, unknown>)
          .then((out) => {
            setNodes((ns) => ns.map((n) => n.id === nodeId
              ? {
                  ...n,
                  data: {
                    ...n.data,
                    status: out.status === 'ok' ? 'completed' : 'failed',
                    config: { ...n.data.config, last_result: out.payload },
                  },
                }
              : n));
            flash(`${toolId} ${out.status}`);
          })
          .catch(() => {
            setNodes((ns) => ns.map((n) => n.id === nodeId
              ? { ...n, data: { ...n.data, status: 'failed' } }
              : n));
            flash('工具执行失败');
          }),
      );
    }
  }, [nodes, setNodes, setEdges, graphId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && !(e.target as HTMLElement).matches('input,textarea')) {
        e.preventDefault();
        setPanel('creative');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const saveGraph = async (): Promise<string | null> => {
    if (USE_MOCK) { flash('画布已保存(mock)'); return null; }
    try {
      // 字段名必须匹配后端 oprim.CanvasNode/CanvasEdge(config/edge_id/from_node_id/
      // to_node_id),否则执行阶段的 model_validate 会静默丢配置或直接报错缺字段。
      const saved = await canvasApi.save({ name: '未命名画布',
        nodes: nodes.map(n => ({
          node_id: n.id, node_type: n.data.nodeType, label: n.data.label ?? '',
          config: n.data.config ?? {}, position: n.position,
        })),
        edges: edges.map(e => ({ edge_id: e.id, from_node_id: e.source, to_node_id: e.target,
          kind: (e.data as Record<string, unknown> | undefined)?.kind ?? 'data' })) });
      const id = String(saved.id ?? '');
      if (id) setGraphId(id);
      flash('画布已保存');
      return id || null;
    } catch { flash('保存失败'); return null; }
  };

  const onSave = () => { void saveGraph(); };

  const onExecute = async () => {
    if (nodes.length === 0) { flash('画布为空'); return; }
    setExecuting(true);
    if (USE_MOCK) {
      let i = 0;
      const iv = setInterval(() => {
        if (i >= nodes.length) { clearInterval(iv); setExecuting(false); flash('执行完成'); return; }
        const id = nodes[i]!.id;
        setNodes(ns => ns.map(n => n.id === id ? { ...n, data: { ...n.data, status: 'completed' } } : n));
        i++;
      }, 600);
      return;
    }
    try {
      const id = graphId ?? await saveGraph();
      if (!id) { setExecuting(false); return; }
      const selected = nodes.filter((n) => n.selected).map((n) => n.id);
      const result = await canvasApi.execute(id, {
        scope: selected.length > 0 ? 'selected' : 'dirty',
        selected_ids: selected,
        max_retries: 1,
      });
      const ran = Array.isArray(result.ran) ? result.ran.length : 0;
      const retries = (result.retries as Record<string, number> | undefined) ?? {};
      const retried = Object.keys(retries).length;
      flash(`执行 ${String(result.status ?? 'done')}：跑 ${ran} 个节点${retried ? `，自动重试 ${retried} 个` : ''}`);
      await reloadGraph(id);
    } catch { flash('执行失败'); } finally { setExecuting(false); }
  };

  const rerunNode = async (nodeId: string) => {
    if (USE_MOCK) { flash('节点重做(mock)'); return; }
    const id = graphId ?? await saveGraph();
    if (!id) return;
    setNodeBusy(nodeId);
    try {
      const result = await canvasApi.executeNode(id, nodeId, { max_retries: 1 });
      const ran = Array.isArray(result.ran) ? result.ran.length : 0;
      flash(`已重做 ${nodeId} 及下游 ${Math.max(0, ran - 1)} 个节点`);
      await reloadGraph(id);
    } catch { flash('节点重做失败'); } finally { setNodeBusy(null); }
  };

  const reviewNode = async (nodeId: string) => {
    if (!graphId || USE_MOCK) { flash('请先保存画布'); return; }
    setNodeBusy(nodeId);
    try {
      const out = await canvasApi.reviewNode(graphId, nodeId);
      flash(`自检：${String(out.status ?? '')}`);
      await reloadGraph(graphId);
    } catch { flash('自检失败'); } finally { setNodeBusy(null); }
  };

  const toggleLock = async (nodeId: string) => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!graphId) { flash('请先保存画布'); return; }
    try {
      await canvasApi.patchNode(graphId, nodeId, { locked: !node?.data.locked });
      await reloadGraph(graphId);
    } catch { flash('锁定切换失败'); }
  };

  const onLoadKoubo = async () => {
    const topic = window.prompt('口播主题 / 脚本（留空用示例）', 'AI 视频创作的未来已来');
    if (topic === null) return;
    try {
      const graph = await canvasApi.kouboTemplate({
        topic,
        script_text: topic,
        duration_s: 8,
        engine: 'livliv',
        character_id: 'd03ft',
      });
      openGraph(graph);
      const nodeCount = Array.isArray(graph.nodes) ? graph.nodes.length : 0;
      flash(`koubo_cut 默认图已创建：${nodeCount} 个节点（每句并行分支）`);
    } catch { flash('创建默认图失败'); }
  };

  return (
    <div className="hevi-canvas">
      <NodePalette onAdd={addNode} onAddTool={addToolNode} onApplyLine={applyLine} />

      <div className="hevi-canvas__flow">
        <div className="hevi-canvas__topbar">
          <a href="/" className="hevi-canvas__home-link">← 首页</a>
          <a href="/studio/timeline" className="hevi-canvas__home-link">时间线</a>
          <button type="button" className="hevi-topbar-btn" onClick={onSave}>保存</button>
          <button type="button" className="hevi-topbar-btn" onClick={onLoadKoubo}>新建口播默认图</button>
          <button type="button" className="hevi-topbar-btn" onClick={() => packFileRef.current?.click()}>导入材料包 JSON</button>
          <input
            ref={packFileRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (file) void onLoadMaterialPackFile(file);
            }}
          />
          <button type="button" className="hevi-topbar-btn hevi-topbar-btn--primary"
            onClick={onExecute} disabled={executing}>
            {executing ? '执行中…' : '▷ 执行画布'}
          </button>
          <span className="hevi-topbar-hint">按 / 唤起创意辅助</span>
          <BetaQuota />
        </div>

        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onConnect={onConnect} onNodeContextMenu={onNodeContextMenu}
          onNodeClick={onNodeClick} onPaneClick={onPaneClick}
          nodeTypes={nodeTypes} fitView
          proOptions={{ hideAttribution: true }}>
          <Background gap={16} size={1} />
          <Controls />
          <MiniMap nodeColor={(n) => NODE_META[(n.data as HeviNodeData).nodeType].color} />
        </ReactFlow>

        {toast && <div className="hevi-canvas__toast" role="alert">{toast}</div>}
        <NodeContextMenu menu={ctxMenu} onAction={onCtxAction} onClose={() => setCtxMenu(null)} />
        {selectedNode && (
          <NodeInspector
            node={selectedNode}
            onChange={(patch) => updateNodeConfig(selectedNode.id, patch)}
            onError={flash}
            onRerun={() => { void rerunNode(selectedNode.id); }}
            onReview={() => { void reviewNode(selectedNode.id); }}
            onToggleLock={() => { void toggleLock(selectedNode.id); }}
            busy={nodeBusy === selectedNode.id}
          />
        )}
      </div>

      <div className="hevi-sidebar">
        <div className="hevi-sidebar__switch">
          <button type="button" data-active={panel === 'subjects' ? 'true' : undefined}
            onClick={() => setPanel('subjects')}>主体</button>
          <button type="button" data-active={panel === 'creative' ? 'true' : undefined}
            onClick={() => setPanel('creative')}>创意</button>
          <button type="button" data-active={panel === 'assets' ? 'true' : undefined}
            onClick={() => setPanel('assets')}>素材</button>
        </div>
        <div className="hevi-sidebar__body">
          {panel === 'subjects' && <SubjectLibrary onPick={() => flash('主体已选,可拖入节点')} />}
          {panel === 'creative' && <CreativePanel />}
          {panel === 'assets'   && <AssetLibrary />}
        </div>
      </div>
    </div>
  );
}

export function HeviCanvas() {
  return <ReactFlowProvider><CanvasInner /></ReactFlowProvider>;
}
