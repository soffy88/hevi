/**
 * Provider Status Detail Page - P5: Detailed provider status view
 * 
 * Shows detailed information about a specific provider including configuration, status, and diagnostic information
 */
'use client';

import { useParams } from 'next/navigation';
import { useState, useEffect } from 'react';

interface ProviderDetail {
  id: string;
  name: string;
  capability: string;
  runtimeType: string;
  status: 'READY' | 'DEGRADED' | 'BLOCKED' | 'OFFLINE' | 'UNCONFIGURED' | 'UNVERIFIED';
  configuration?: Record<string, string>;
  lastProbeTime?: string;
  healthEndpoint?: string;
  diagnosticInfo?: string;
  errorMessage?: string;
}

// Mock data for demonstration
const mockProviderDetails: Record<string, ProviderDetail> = {
  'wan_local': {
    id: 'wan_local',
    name: 'Wan Local',
    capability: '视频生成',
    runtimeType: '本地',
    status: 'READY',
    configuration: {
      endpoint: 'http://127.0.0.1:8000',
      model: 'wan-2.1-i2v-turbo',
    },
    lastProbeTime: new Date().toLocaleString(),
    healthEndpoint: 'http://127.0.0.1:8000/api/health',
    diagnosticInfo: '服务运行正常，可以生成短视频和动态图片',
    errorMessage: undefined,
  },
  'longcat': {
    id: 'longcat',
    name: 'LongCat',
    capability: '数字人',
    runtimeType: '云端',
    status: 'BLOCKED',
    configuration: {},
    lastProbeTime: new Date().toLocaleString(),
    healthEndpoint: 'https://api.longcat.ai/health',
    diagnosticInfo: '尚未配置服务端点或认证凭据',
    errorMessage: 'Missing endpoint configuration',
  },
  'joyai': {
    id: 'joyai',
    name: 'JoyAI',
    capability: '视频生成',
    runtimeType: '云端',
    status: 'DEGRADED',
    configuration: {},
    lastProbeTime: new Date().toLocaleString(),
    healthEndpoint: 'https://api.joyai.ai/health',
    diagnosticInfo: '控制平面就绪，但实际视频生成服务暂时不可用',
    errorMessage: '视频生成服务暂时不可用',
  },
  'voicebox': {
    id: 'voicebox',
    name: 'Voicebox',
    capability: '语音合成',
    runtimeType: '云端',
    status: 'OFFLINE',
    configuration: {},
    lastProbeTime: new Date().toLocaleString(),
    healthEndpoint: 'https://api.voicebox.ai/health',
    diagnosticInfo: '已配置的服务端点无法访问',
    errorMessage: 'Endpoint unreachable',
  },
  'pexels': {
    id: 'pexels',
    name: 'Pexels',
    capability: '免费图片素材',
    runtimeType: '云端',
    status: 'BLOCKED',
    configuration: {},
    lastProbeTime: new Date().toLocaleString(),
    healthEndpoint: 'https://api.pexels.com/v1/search',
    diagnosticInfo: '尚未提供 Pexels API 密钥，素材库不可用',
    errorMessage: 'Missing API key',
  },
};

export default function ProviderStatusDetailPage() {
  const params = useParams();
  const providerId = params.id as string;
  const [provider, setProvider] = useState<ProviderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const mockData = mockProviderDetails[providerId];
        if (mockData) {
          if (alive) setProvider(mockData);
        } else {
          if (alive) setError(`Provider "${providerId}" not found`);
        }
      } catch (err) {
        if (alive) {
          setError('无法加载提供商详情');
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [providerId]);

  if (loading) {
    return (
      <div className="provider-detail-page">
        <div className="provider-detail-page__loading">加载中...</div>
      </div>
    );
  }

  if (error || !provider) {
    return (
      <div className="provider-detail-page">
        <div className="provider-detail-page__error">
          <h2>提供商不存在</h2>
          <p>{error || '请选择有效的提供商'}</p>
        </div>
      </div>
    );
  }

  const getStatusColor = (status: ProviderDetail['status']) => {
    switch (status) {
      case 'READY': return 'status-ready';
      case 'DEGRADED': return 'status-degraded';
      case 'BLOCKED': return 'status-blocked';
      case 'OFFLINE': return 'status-offline';
      case 'UNCONFIGURED': return 'status-unconfigured';
      case 'UNVERIFIED': return 'status-unverified';
      default: return 'status-unknown';
    }
  };

  const getStatusLabel = (status: ProviderDetail['status']) => {
    const labels = {
      'READY': '就绪',
      'DEGRADED': '降级',
      'BLOCKED': '被挡',
      'OFFLINE': '离线',
      'UNCONFIGURED': '未配置',
      'UNVERIFIED': '未验证',
    };
    return labels[status] || status;
  };

  return (
    <div className="provider-detail-page">
      <div className="provider-detail-page__header">
        <h1 className="provider-detail-page__name">{provider.name}</h1>
        <span className={`provider-detail-page__status ${getStatusColor(provider.status)}`}>{getStatusLabel(provider.status)}</span>
      </div>

      <div className="provider-detail-page__content">
        <section className="provider-detail-page__section">
          <h2 className="provider-detail-page__section-title">基本信息</h2>
          <div className="provider-detail-page__info-grid">
            <div className="provider-detail-page__info-item">
              <span className="provider-detail-page__info-label">提供商 ID:</span>
              <span className="provider-detail-page__info-value">{provider.id}</span>
            </div>
            <div className="provider-detail-page__info-item">
              <span className="provider-detail-page__info-label">能力:</span>
              <span className="provider-detail-page__info-value">{provider.capability}</span>
            </div>
            <div className="provider-detail-page__info-item">
              <span className="provider-detail-page__info-label">运行时类型:</span>
              <span className="provider-detail-page__info-value">{provider.runtimeType}</span>
            </div>
            {provider.lastProbeTime && (
              <div className="provider-detail-page__info-item">
                <span className="provider-detail-page__info-label">最后检测:</span>
                <span className="provider-detail-page__info-value">{provider.lastProbeTime}</span>
              </div>
            )}
          </div>
        </section>

        {provider.configuration && (
          <section className="provider-detail-page__section">
            <h2 className="provider-detail-page__section-title">配置信息</h2>
            <div className="provider-detail-page__config-grid">
              {Object.entries(provider.configuration).map(([key, value]) => (
                <div key={key} className="provider-detail-page__config-item">
                  <span className="provider-detail-page__config-key">{key}:</span>
                  <span className="provider-detail-page__config-value">{value}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {(provider.diagnosticInfo || provider.errorMessage) && (
          <section className="provider-detail-page__section">
            <h2 className="provider-detail-page__section-title">状态信息</h2>
            <div className="provider-detail-page__status-info">
              {provider.diagnosticInfo && (
                <div className="provider-detail-page__info-item">
                  <span className="provider-detail-page__info-label">诊断:</span>
                  <span className="provider-detail-page__info-value">{provider.diagnosticInfo}</span>
                </div>
              )}
              {provider.errorMessage && (
                <div className="provider-detail-page__info-item">
                  <span className="provider-detail-page__info-label">错误:</span>
                  <span className="provider-detail-page__info-value">{provider.errorMessage}</span>
                </div>
              )}
            </div>
          </section>
        )}

        {provider.healthEndpoint && (
          <section className="provider-detail-page__section">
            <h2 className="provider-detail-page__section-title">健康检查端点</h2>
            <div className="provider-detail-page__health-endpoint">
              <a href={provider.healthEndpoint} target="_blank" rel="noopener noreferrer">
                {provider.healthEndpoint}
              </a>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}