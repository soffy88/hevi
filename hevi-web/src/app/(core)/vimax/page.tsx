/**
 * /vimax — ViMax 高级功能页面
 *
 * 对标 HKUDS/ViMax 的高级视频生成功能:
 * - Idea2Video: 一句话创意 → 完整视频
 * - Novel2Video: 长文本/小说 → 视频
 * - AutoCameo: 参考照片人物插入视频
 * - Provider Presets: 预置 provider 配置管理
 */
'use client';

import { ViMaxConsole } from '@/components/vimax/ViMaxConsole';

export default function ViMaxPage() {
  return (
    <main className="page-shell">
      <section className="page-content">
        <div className="page-intro">
          <h1>ViMax 高级功能</h1>
          <p>
            对标 HKUDS/ViMax 的高级视频生成能力，提供创意转视频、小说转视频、
            照片人物入戏等端到端管线，以及预置 Provider 配置管理。
          </p>
        </div>
        <ViMaxConsole />
      </section>
    </main>
  );
}
