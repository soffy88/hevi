/**
 * ProviderSelector — 逐步 provider 选择(§1)
 *
 * 三预设卡片(省钱/均衡/极速)+ 高级逐步自定义(展开)。
 * 实时成本 + 耗时。本地慢明确告知(§2 预期管理)。
 */
'use client';

import { useState } from 'react';
import type { GalleryCategory, StepProviders, PresetId } from '@/types/api';
import { PRESETS, PROVIDER_OPTIONS, mockEstimateV2 } from '@/lib/mock-data';

// 各类型涉及的步骤(§5)
const CATEGORY_STEPS: Record<GalleryCategory, { video: boolean; audio: boolean; avatar: boolean }> = {
  long_video:       { video: true,  audio: true,  avatar: false },
  short_video:      { video: true,  audio: true,  avatar: false },
  avatar_narration: { video: false, audio: true,  avatar: true },
  animation:        { video: true,  audio: false, avatar: false },
  image:            { video: false, audio: false, avatar: false },
};

export function ProviderSelector({
  category,
  stepProviders,
  onChange,
}: {
  category: GalleryCategory;
  stepProviders: StepProviders;
  onChange: (sp: StepProviders) => void;
}) {
  const [preset, setPreset] = useState<PresetId | null>('balanced');
  const [advanced, setAdvanced] = useState(false);

  const steps = CATEGORY_STEPS[category];
  const est = mockEstimateV2(stepProviders, steps.video, steps.audio);
  const isLocalVideo = stepProviders.video.includes('local');

  const applyPreset = (id: PresetId) => {
    const p = PRESETS.find(x => x.id === id)!;
    setPreset(id);
    onChange(p.step_providers);
  };

  const changeStep = (step: keyof StepProviders, value: string) => {
    setPreset(null); // 自定义 = 取消预设高亮
    onChange({ ...stepProviders, [step]: value });
  };

  return (
    <div className="hevi-provider">
      {/* 三预设卡片 */}
      <div className="hevi-preset-cards">
        {PRESETS.map(p => (
          <button key={p.id} type="button" className="hevi-preset-card"
            data-active={preset === p.id ? 'true' : undefined}
            onClick={() => applyPreset(p.id)}>
            <span className="hevi-preset-card__icon">{p.icon}</span>
            <span className="hevi-preset-card__label">{p.label}</span>
            <span className="hevi-preset-card__tag">{p.tagline}</span>
            <span className="hevi-preset-card__cost">
              {p.est_cost_usd === 0 ? '≈免费' : `~$${p.est_cost_usd}`}
            </span>
            <span className="hevi-preset-card__meta">
              {p.est_time_min <= 5 ? '快' : '慢'}(~{p.est_time_min}min) · {p.quality}
            </span>
          </button>
        ))}
      </div>

      {/* 高级:逐步自定义 */}
      <button type="button" className="hevi-provider__advanced-toggle"
        onClick={() => setAdvanced(a => !a)}>
        {advanced ? '▾' : '▸'} 高级:逐步选择 provider
      </button>

      {advanced && (
        <div className="hevi-provider__steps">
          <StepRow label="脚本生成" step="llm" options={PROVIDER_OPTIONS.llm!}
            value={stepProviders.llm} onChange={v => changeStep('llm', v)} />
          {steps.video && (
            <StepRow label="视频生成" step="video" options={PROVIDER_OPTIONS.video!}
              value={stepProviders.video} onChange={v => changeStep('video', v)} />
          )}
          {steps.audio && (
            <StepRow label="配音" step="audio" options={PROVIDER_OPTIONS.audio!}
              value={stepProviders.audio} onChange={v => changeStep('audio', v)} />
          )}
          {steps.avatar && (
            <StepRow label="数字人" step="avatar" options={PROVIDER_OPTIONS.avatar!}
              value={stepProviders.avatar ?? 'duix_local'} onChange={v => changeStep('avatar', v)} />
          )}
        </div>
      )}

      {/* 实时成本 + 耗时 */}
      <div className="hevi-provider__estimate">
        <div className="hevi-provider__cost">
          预估 <strong>${est.total_usd}</strong>
          <span className="hevi-provider__credits">= {est.total_credits} 积分</span>
        </div>
        <div className="hevi-provider__time">预计耗时 约 {est.est_time_min} 分钟</div>
      </div>

      {/* 逐步明细 */}
      {advanced && est.per_step.length > 0 && (
        <div className="hevi-provider__breakdown">
          {est.per_step.map((s, i) => (
            <span key={i} className="hevi-provider__breakdown-item">
              {s.step} ${s.cost_usd}
            </span>
          ))}
        </div>
      )}

      {/* 本地慢预期管理(§2 重要)*/}
      {isLocalVideo && (
        <div className="hevi-provider__local-notice">
          ⏳ 本地生成较慢,约 {est.est_time_min} 分钟。提交后进队列,可关闭页面稍后查看。
        </div>
      )}
    </div>
  );
}

function StepRow({
  label, options, value, onChange,
}: {
  label: string; step: string;
  options: { id: string; label: string; hint: string }[];
  value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="hevi-step-row">
      <span className="hevi-step-row__label">{label}</span>
      <div className="hevi-step-row__options">
        {options.map(o => (
          <button key={o.id} type="button" className="hevi-step-opt"
            data-active={value === o.id ? 'true' : undefined}
            onClick={() => onChange(o.id)}>
            <span className="hevi-step-opt__label">{o.label}</span>
            <span className="hevi-step-opt__hint">{o.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
