/**
 * NodeContextMenu — 节点右键菜单(1.10)
 * 执行/复制/删除。
 */
'use client';

export interface ContextMenuState {
  x: number;
  y: number;
  nodeId: string;
}

export function NodeContextMenu({
  menu, onAction, onClose,
}: {
  menu: ContextMenuState | null;
  onAction: (action: 'execute' | 'duplicate' | 'delete', nodeId: string) => void;
  onClose: () => void;
}) {
  if (!menu) return null;
  return (
    <>
      <div className="hevi-ctx-backdrop" onClick={onClose} />
      <div className="hevi-ctx-menu" style={{ left: menu.x, top: menu.y }}>
        <button type="button" className="hevi-ctx-item"
          onClick={() => { onAction('execute', menu.nodeId); onClose(); }}>▷ 执行此节点</button>
        <button type="button" className="hevi-ctx-item"
          onClick={() => { onAction('duplicate', menu.nodeId); onClose(); }}>⎘ 复制</button>
        <button type="button" className="hevi-ctx-item hevi-ctx-item--danger"
          onClick={() => { onAction('delete', menu.nodeId); onClose(); }}>✕ 删除</button>
      </div>
    </>
  );
}
