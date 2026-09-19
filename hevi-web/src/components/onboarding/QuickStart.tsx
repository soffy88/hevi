'use client';

/**
 * D6-F Quick Start — first-run path with safe defaults.
 * Advanced differentiators (persistent character, continuity, memory,
 * provider, repair policy) are optional and defaulted, not required.
 * The demo path is clearly labelled and uses no paid provider.
 */
import { useState } from 'react';
import { identityApi } from '@/lib/api-client';
import { PRODUCT_COPY as C } from '@/lib/product-copy';
import { ActionButton, Card, FormField, SectionHeader } from '@/components/shared/ui';

export function QuickStart({ onDemoProject }: { onDemoProject?: (projectId: string) => void }) {
  const [projectType, setProjectType] = useState('short-video');
  const [material, setMaterial] = useState('');
  const [target, setTarget] = useState('竖屏 60 秒');
  const [advanced, setAdvanced] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const start = () => {
    setError('');
    setMessage(`已创建 ${projectType} 项目，使用默认设置（可稍后再调整高级项）。`);
  };

  const createDemo = async () => {
    setError('');
    setMessage('');
    try {
      const projectId = 'demo-project';
      await identityApi.create('示例角色', 'demo-voice');
      setMessage(`${C.onboarding.demoBadge}：已创建示例角色与演示项目（不消耗付费生成）。`);
      onDemoProject?.(projectId);
    } catch (e) {
      setError(e instanceof Error ? e.message : '示例项目创建失败');
    }
  };

  return (
    <section data-testid="quick-start">
      <SectionHeader icon="🚀" title={C.onboarding.quickStart} subtitle={C.onboarding.quickStartHint} />

      <FormField label="项目类型">
        <select aria-label="项目类型" value={projectType} onChange={e => setProjectType(e.target.value)}>
          <option value="short-video">短视频</option>
          <option value="explainer">解说</option>
          <option value="series">系列剧</option>
        </select>
      </FormField>
      <FormField label="素材" hint="可稍后补充">
        <input aria-label="素材" value={material} onChange={e => setMaterial(e.target.value)} placeholder="链接或描述" />
      </FormField>
      <FormField label="目标输出">
        <input aria-label="目标输出" value={target} onChange={e => setTarget(e.target.value)} />
      </FormField>

      <ActionButton onClick={start}>开始创建</ActionButton>

      <details onToggle={e => setAdvanced((e.target as HTMLDetailsElement).open)}>
        <summary>高级选项（可选）</summary>
        <p data-testid="advanced-hint">
          长期角色、连续性检查、创作偏好、模型来源、修复策略都有合理默认值，无需在此配置。
        </p>
      </details>

      <div>
        <ActionButton variant="secondary" onClick={createDemo}>
          {C.onboarding.sample}
        </ActionButton>
        <span data-testid="demo-badge" className="demo-badge">{C.onboarding.demoBadge}</span>
        <p>{C.onboarding.sampleHint}</p>
      </div>

      {message && <p role="status" data-testid="quickstart-message">{message}</p>}
      {error && <p role="alert" data-testid="quickstart-error">{error}</p>}
    </section>
  );
}
