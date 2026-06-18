/**
 * HeviCanvas — 无限画布工作台(完整版)
 * 集成:5类节点+连线校验、主体库/创意辅助/资产库侧栏、
 * 节点右键菜单、`/` 快捷键唤起创意辅助、保存/执行+SSE进度回填。
 */
'use client';

import { useCallback, useState, useEffect } from 'react';
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

  const flash = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 2400); };

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
      flash('已触发节点执行(mock)');
    }
  }, [setNodes, setEdges]);

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

  const onSave = async () => {
    if (USE_MOCK) { flash('画布已保存(mock)'); return; }
    try {
      await canvasApi.save({ name: '未命名画布',
        nodes: nodes.map(n => ({ node_id: n.id, node_type: n.data.nodeType, inputs: {}, upstream_ids: [] })),
        edges: edges.map(e => ({ from_id: e.source, to_id: e.target })) });
      flash('画布已保存');
    } catch { flash('保存失败'); }
  };

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
      const { task_id } = await canvasApi.execute('current');
      flash(`执行已启动 ${task_id}`);
    } catch { flash('执行失败'); setExecuting(false); }
  };

  return (
    <div className="hevi-canvas">
      <NodePalette onAdd={addNode} />

      <div className="hevi-canvas__flow">
        <div className="hevi-canvas__topbar">
          <a href="/" className="hevi-canvas__home-link">← 首页</a>
          <button type="button" className="hevi-topbar-btn" onClick={onSave}>保存</button>
          <button type="button" className="hevi-topbar-btn hevi-topbar-btn--primary"
            onClick={onExecute} disabled={executing}>
            {executing ? '执行中…' : '▷ 执行画布'}
          </button>
          <span className="hevi-topbar-hint">按 / 唤起创意辅助</span>
        </div>

        <ReactFlow
          nodes={nodes} edges={edges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onConnect={onConnect} onNodeContextMenu={onNodeContextMenu}
          nodeTypes={nodeTypes} fitView
          proOptions={{ hideAttribution: true }}>
          <Background gap={16} size={1} />
          <Controls />
          <MiniMap nodeColor={(n) => NODE_META[(n.data as HeviNodeData).nodeType].color} />
        </ReactFlow>

        {toast && <div className="hevi-canvas__toast" role="alert">{toast}</div>}
        <NodeContextMenu menu={ctxMenu} onAction={onCtxAction} onClose={() => setCtxMenu(null)} />
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
