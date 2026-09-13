'use client';

import { useEffect, useMemo, useState } from 'react';
import { RequireAuth } from '@/components/RequireAuth';
import { TopNav } from '@/components/TopNav';
import { ActionButton } from '@/components/shared';
import { galleryApi, publishStudioApi, studioApi } from '@/lib/api-client';
import type { GalleryItem } from '@/types/api';

type ToolResult = { status: string; payload?: Record<string, unknown>; reason?: string };

function labelStatus(status: string) {
  if (status === 'ok' || status === 'completed') return '已完成';
  if (status === 'blocked') return '暂不可用';
  return '需要处理';
}

export default function AnalysisPage() {
  const [assets, setAssets] = useState<GalleryItem[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ToolResult | null>(null);
  const [referenceResult, setReferenceResult] = useState<Record<string, unknown> | null>(null);
  const [referenceRunning, setReferenceRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    galleryApi.list('long_video')
      .then(items => setAssets(items))
      .catch(err => setError(err instanceof Error ? err.message : '无法加载视频素材'))
      .finally(() => setLoading(false));
  }, []);

  const selected = useMemo(() => assets.find(item => item.item_id === selectedId), [assets, selectedId]);

  async function analyze() {
    if (!selected) return;
    const sourcePath = (selected as GalleryItem & { source_path?: string }).source_path || selected.media_url;
    if (!sourcePath || /^https?:\/\//.test(sourcePath)) {
      setError('该素材没有服务端可读路径。请先将视频保存到 HEVI 素材库。');
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const indexed = await studioApi.invoke('video.evidence.index', { source_path: sourcePath });
      setResult(indexed);
    } catch (err) {
      setError(err instanceof Error ? err.message : '分析请求失败');
    } finally {
      setRunning(false);
    }
  }

  async function analyzeReference() {
    const url = selected?.media_url;
    if (!url || !/^https?:\/\//.test(url)) {
      setError('参考片分析需要素材库中的可访问视频地址。');
      return;
    }
    setReferenceRunning(true);
    setError(null);
    try {
      setReferenceResult(await publishStudioApi.mptReference({ url }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '参考片分析请求失败');
    } finally {
      setReferenceRunning(false);
    }
  }

  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page analysis-page">
          <div className="product-page__intro">
            <p className="product-page__eyebrow">视频分析</p>
            <h1>看懂你的成片</h1>
            <p>基于真实视频素材生成镜头时间轴、节奏与质量证据。</p>
          </div>

          <section className="analysis-toolbar">
            <label htmlFor="analysis-asset">选择视频</label>
            <select id="analysis-asset" value={selectedId} onChange={event => setSelectedId(event.target.value)} disabled={loading}>
              <option value="">{loading ? '加载素材中…' : assets.length ? '选择一个视频素材' : '暂无可分析的视频素材'}</option>
              {assets.map(asset => <option key={asset.item_id} value={asset.item_id}>{asset.title}</option>)}
            </select>
            <ActionButton onClick={analyze} loading={running} disabled={!selected}>开始分析</ActionButton>
          </section>

          {error && <div className="product-alert product-alert--error">{error}</div>}

          {result && (
            <section className="analysis-result">
              <div className="analysis-result__header">
                <div><span className="analysis-result__kicker">分析结果</span><h2>{selected?.title}</h2></div>
                <span className={`analysis-status analysis-status--${result.status}`}>{labelStatus(result.status)}</span>
              </div>
              {result.reason && <p className="analysis-result__reason">{result.reason}</p>}
              <div className="analysis-result__grid">
                <div><strong>镜头时间轴</strong><span>来自真实证据索引</span></div>
                <div><strong>可追溯</strong><span>包含素材与时间戳引用</span></div>
                <div><strong>高级视觉理解</strong><span>当前未连接视觉模型</span></div>
              </div>
              <details className="technical-details">
                <summary>查看技术详情</summary>
                <pre>{JSON.stringify(result.payload ?? result, null, 2)}</pre>
              </details>
            </section>
          )}

          <section className="reference-card">
            <div>
              <span className="analysis-result__kicker">参考片分析</span>
              <h2>提取节奏与镜头结构</h2>
              <p>只提取抽象制作特征，不复制原片内容。结果可作为后续创作参考。</p>
            </div>
            <ActionButton variant="secondary" onClick={analyzeReference} loading={referenceRunning} disabled={!selected}>
              应用为创作参考
            </ActionButton>
            {referenceResult && (
              <details className="technical-details reference-card__result" open>
                <summary>查看参考特征</summary>
                <pre>{JSON.stringify(referenceResult, null, 2)}</pre>
              </details>
            )}
          </section>

          {!result && !error && (
            <section className="analysis-empty">
              <div className="analysis-empty__icon">◌</div>
              <h2>选择一个视频开始</h2>
              <p>分析结果会展示镜头边界、节奏、运镜和质量问题。没有真实素材时不会生成占位结果。</p>
            </section>
          )}
        </main>
      </RequireAuth>
    </>
  );
}
