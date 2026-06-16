/**
 * CreativePanel — 创意辅助面板(9 项,从 capabilities 动态渲染)
 *
 * `/` 快捷键 / 右键菜单触发。L-029:多数返回结构化数据/prompt,
 * 面板展示数据 + "渲染成片"按钮触发视频节点。
 */
'use client';

import { useEffect, useState } from 'react';
import type { CreativeCapability } from '@/types/api';
import { creativeApi, USE_MOCK } from '@/lib/api-client';
import { MOCK_CAPABILITIES } from '@/lib/mock-data';

export function CreativePanel({
  onPick,
  onClose,
}: {
  onPick?: (cap: CreativeCapability) => void;
  onClose?: () => void;
}) {
  const [caps, setCaps] = useState<CreativeCapability[]>([]);
  const [active, setActive] = useState<CreativeCapability | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = USE_MOCK ? MOCK_CAPABILITIES : await creativeApi.capabilities();
        setCaps(data);
      } catch { setCaps(USE_MOCK ? MOCK_CAPABILITIES : []); }
    })();
  }, []);

  return (
    <div className="hevi-creative">
      <div className="hevi-creative__head">
        <span className="hevi-side-title">创意辅助</span>
        {onClose && <button type="button" className="hevi-creative__close" onClick={onClose}>✕</button>}
      </div>

      {!active ? (
        <div className="hevi-creative__grid">
          {caps.map(c => (
            <button key={c.id} type="button"
              className="hevi-creative__item"
              onClick={() => { setActive(c); onPick?.(c); }}>
              <span className="hevi-creative__item-label">{c.label}</span>
              {c.description && <span className="hevi-creative__item-desc">{c.description}</span>}
              <span className="hevi-creative__item-tag" data-returns={c.returns}>
                {c.returns === 'data' ? '结构化数据' : c.returns === 'prompt' ? 'Prompt' : '直接成片'}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="hevi-creative__detail">
          <button type="button" className="hevi-creative__back" onClick={() => setActive(null)}>← 返回</button>
          <h3 className="hevi-creative__detail-title">{active.label}</h3>
          {active.description && <p className="hevi-creative__detail-desc">{active.description}</p>}

          {/* 动态渲染输入表单(从 input_schema) */}
          {active.input_schema && (
            <div className="hevi-creative__form">
              {Object.entries(active.input_schema).map(([key, type]) => (
                <label key={key} className="hevi-creative__field">
                  <span className="hevi-creative__field-label">{key}</span>
                  <input className="hevi-creative__field-input"
                    placeholder={String(type)} />
                </label>
              ))}
            </div>
          )}

          <div className="hevi-creative__actions">
            <button type="button" className="hevi-creative__run">执行</button>
            {(active.returns === 'data' || active.returns === 'prompt') && (
              <button type="button" className="hevi-creative__render">渲染成片</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
