/**
 * Assets page - P3: Assets Information Architecture
 * 
 * Shows user's assets organized by type
 * Reuses existing Gallery, Subject APIs, Presenter APIs, Voice Studio, Backlot
 */
'use client';

import { useState } from 'react';
import { ShowcaseWall } from '@/components/gallery/ShowcaseWall';
import { PresenterLibrary } from '@/components/presenters/PresenterLibrary';
import { SubjectLibrary } from '@/components/panels/SubjectLibrary';

type AssetTab = '视频' | '图片' | '角色' | '声音' | '数字人' | '素材';

export default function AssetsPage() {
  const [activeTab, setActiveTab] = useState<AssetTab>('视频');

  const tabs: AssetTab[] = ['视频', '图片', '角色', '声音', '数字人', '素材'];

  return (
    <div className="assets-page">
      <header className="assets-page__header">
        <h1 className="assets-page__title">资产</h1>
        <nav className="assets-page__tabs" role="tablist">
          {tabs.map(tab => (
            <button
              key={tab}
              type="button"
              role="tab"
              className={`assets-page__tab ${activeTab === tab ? 'assets-page__tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
              aria-selected={activeTab === tab}>
              {tab}
            </button>
          ))}
        </nav>
      </header>

      <div className="assets-page__content" role="tabpanel">
        {activeTab === '视频' && <ShowcaseWall />}
        {activeTab === '图片' && <ShowcaseWall />}
        {activeTab === '角色' && <SubjectLibrary />}
        {activeTab === '声音' && <VoiceAssets />}
        {activeTab === '数字人' && <PresenterLibrary />}
        {activeTab === '素材' && <MaterialAssets />}
      </div>
    </div>
  );
}

function VoiceAssets() {
  return (
    <div className="assets-page__voice">
      <p className="assets-page__placeholder">声音资产</p>
      {/* 复用 voice studio 相关 API */}
    </div>
  );
}

function MaterialAssets() {
  return (
    <div className="assets-page__material">
      <p className="assets-page__placeholder">素材库</p>
      {/* 复用 backlot 相关 API */}
    </div>
  );
}