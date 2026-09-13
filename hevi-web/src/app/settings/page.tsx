'use client';

import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';
import { SystemStatus } from '@/components/SystemStatus';

export default function SettingsPage() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page settings-page">
          <div className="product-page__intro">
            <p className="product-page__eyebrow">设置</p>
            <h1>系统状态</h1>
            <p>查看服务连接与能力可用性。技术详情只在这里显示。</p>
          </div>
          <section className="status-card">
            <SystemStatus />
            <div className="status-card__capabilities">
              <h2>能力状态</h2>
              <div className="status-card__grid">
                <span>语言模型</span><strong>已连接</strong>
                <span>故事与场景规划</span><strong>可用</strong>
                <span>分镜规划</span><strong>可用</strong>
                <span>视频核心分析</span><strong>可用</strong>
                <span>高级视觉理解</span><strong className="is-muted">稍后开放</strong>
              </div>
            </div>
          </section>
        </main>
      </RequireAuth>
    </>
  );
}
