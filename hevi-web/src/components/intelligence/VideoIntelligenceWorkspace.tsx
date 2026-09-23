'use client';

import { useEffect, useMemo, useState } from 'react';
import { videoIntelligenceApi } from '@/lib/api-client';

type Row = Record<string, unknown>;
type Tab = 'cases' | 'benchmarks' | 'patterns' | 'templates';

const TABS: Array<{ id: Tab; label: string; description: string }> = [
  { id: 'cases', label: 'Cases', description: '外部案例与真实生产证据' },
  { id: 'benchmarks', label: 'Benchmarks', description: '冻结计划下的维度比较' },
  { id: 'patterns', label: 'Patterns', description: '正向与反向证据' },
  { id: 'templates', label: 'Templates', description: '可追溯的模板 revision' },
];

const DIMENSIONS = [
  'identity_consistency', 'action_completion', 'action_contact',
  'temporal_continuity', 'camera_adherence', 'style_adherence',
  'object_persistence', 'audio_alignment', 'lip_sync',
];

function text(row: Row, key: string, fallback = '—'): string {
  const value = row[key];
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function jsonText(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return fallback; }
}

function statusClass(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

function rows(value: unknown): Row[] {
  return Array.isArray(value)
    ? value.filter((item): item is Row => typeof item === 'object' && item !== null)
    : [];
}

function dimensionValue(entry: Row, dimension: string): string {
  const comparison = entry.dimension_comparison;
  if (!comparison || typeof comparison !== 'object') return 'NOT_OBSERVED';
  const value = (comparison as Row)[dimension];
  if (value === null || value === undefined) return 'NOT_OBSERVED';
  if (typeof value === 'object' && value !== null) {
    const record = value as Row;
    return text(record, 'status', text(record, 'score', 'NOT_OBSERVED'));
  }
  return String(value);
}

export function VideoIntelligenceWorkspace() {
  const [tab, setTab] = useState<Tab>('cases');
  const [cases, setCases] = useState<Row[]>([]);
  const [benchmarks, setBenchmarks] = useState<Row[]>([]);
  const [patterns, setPatterns] = useState<Row[]>([]);
  const [templates, setTemplates] = useState<Row[]>([]);
  const [selectedCase, setSelectedCase] = useState<Row | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      videoIntelligenceApi.cases(),
      videoIntelligenceApi.benchmarks(),
      videoIntelligenceApi.patterns(),
      videoIntelligenceApi.templates(),
    ]).then(([caseData, benchmarkData, patternData, templateData]) => {
      if (!active) return;
      setCases(caseData.cases);
      setBenchmarks(benchmarkData.benchmarks);
      setPatterns(patternData.patterns);
      setTemplates(templateData.templates);
      setError(null);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Video Intelligence 数据加载失败');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const currentTab = useMemo(() => TABS.find(item => item.id === tab) ?? TABS[0], [tab]);

  return (
    <main className="product-page video-intelligence-page" data-testid="video-intelligence">
      <div className="product-page__intro">
        <p className="product-page__eyebrow">HEVI Studio · Video Intelligence</p>
        <h1>Video Intelligence</h1>
        <p>把案例、Verdict、Pattern 与 Template 汇入同一条可审计的生产学习链。</p>
      </div>

      <nav className="vi-tabs" aria-label="Video Intelligence 工作区">
        {TABS.map(item => (
          <button
            type="button"
            key={item.id}
            className={`vi-tab${tab === item.id ? ' vi-tab--active' : ''}`}
            aria-pressed={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            <strong>{item.label}</strong>
            <span>{item.description}</span>
          </button>
        ))}
      </nav>

      {error && <div className="product-alert product-alert--error" role="alert">{error}</div>}
      {loading && <p className="panel-empty" data-testid="vi-loading">加载 Video Intelligence…</p>}

      {!loading && tab === 'cases' && (
        <CasesView cases={cases} selectedCase={selectedCase} onSelect={setSelectedCase} />
      )}
      {!loading && tab === 'benchmarks' && <BenchmarksView benchmarks={benchmarks} />}
      {!loading && tab === 'patterns' && <PatternsView patterns={patterns} />}
      {!loading && tab === 'templates' && <TemplatesView templates={templates} />}

      {!loading && !error && (
        <p className="vi-integrity-note">当前工作区：{currentTab.label} · 所有数据由认证 API 按 workspace/user ownership 返回。</p>
      )}
    </main>
  );
}

function CasesView({
  cases,
  selectedCase,
  onSelect,
}: { cases: Row[]; selectedCase: Row | null; onSelect: (value: Row) => void }) {
  return (
    <section className="vi-section" aria-label="Cases">
      <div className="vi-section-heading"><div><span className="analysis-result__kicker">CASE LIBRARY</span><h2>Cases</h2></div><span>{cases.length} cases</span></div>
      {!cases.length ? <p className="panel-empty">暂无已登记案例。Case ingest 不会在这里生成视频。</p> : (
        <div className="vi-split">
          <div className="vi-list">
            {cases.map(item => {
              const id = text(item, 'id');
              const selected = selectedCase?.id === item.id;
              const origin = text(item, 'prompt_origin', 'UNKNOWN').toUpperCase();
              return (
                <button type="button" key={id} className={`vi-list-item${selected ? ' vi-list-item--selected' : ''}`} onClick={() => onSelect(item)}>
                  <strong>{text(item, 'title', 'Untitled case')}</strong>
                  <span>{text(item, 'source_platform', text(item, 'source_url', 'local evidence'))}</span>
                  <small>{text(item, 'analysis_status', 'not_started')} · {text(item, 'reproduction_count', '0')} reproductions · {origin}</small>
                </button>
              );
            })}
          </div>
          {selectedCase && <CaseDetail item={selectedCase} />}
        </div>
      )}
    </section>
  );
}

function CaseDetail({ item }: { item: Row }) {
  const origin = text(item, 'prompt_origin', 'unknown').toUpperCase().replace('_', ' ');
  return (
    <article className="vi-detail">
      <div className="vi-section-heading"><div><span className="analysis-result__kicker">CASE DETAIL</span><h2>{text(item, 'title')}</h2></div><span className={`vi-status vi-status--${statusClass(text(item, 'provenance_status', 'unverified'))}`}>{text(item, 'provenance_status', 'unverified')}</span></div>
      <div className="vi-detail-grid">
        <span>Source</span><strong>{text(item, 'source_url', text(item, 'source_platform', 'local evidence'))}</strong>
        <span>Rights</span><strong>{text(item, 'rights_status', 'unknown')}</strong>
        <span>Analysis</span><strong>{text(item, 'analysis_status', 'not_started')}</strong>
        <span>Reproductions</span><strong>{text(item, 'reproduction_count', '0')}</strong>
        <span>Latest verdict</span><strong>{text(item, 'latest_verdict_id', 'not observed')}</strong>
      </div>
      <h3>Prompt · {origin}</h3>
      <pre className="vi-pre">{text(item, 'original_prompt', 'No prompt was provided; this is not presented as an original prompt.')}</pre>
      <h3>Provenance</h3>
      <pre className="vi-pre">{jsonText(item.provenance, 'No provenance record')}</pre>
      <h3>References / Shots</h3>
      <pre className="vi-pre">{jsonText(item.reference_assets ?? item.shots, 'No references or shots')}</pre>
    </article>
  );
}

function BenchmarksView({ benchmarks }: { benchmarks: Row[] }) {
  return (
    <section className="vi-section" aria-label="Benchmarks">
      <div className="vi-section-heading"><div><span className="analysis-result__kicker">FROZEN PLAN COMPARISON</span><h2>Benchmarks</h2></div><span>{benchmarks.length} runs</span></div>
      {!benchmarks.length ? <p className="panel-empty">暂无 benchmark。单 provider 时会保留 blocked evidence，不会伪造 cross-model PASS。</p> : benchmarks.map(item => (
        <article className="vi-card" key={text(item, 'id')}>
          <div className="vi-card-heading"><strong>{text(item, 'status')}</strong><span>{text(item, 'provider_count', '0')} providers · {text(item, 'entry_count', '0')} entries</span></div>
          <p>Case: {text(item, 'case_id')} · Plan: {text(item, 'benchmark_plan_id')}</p>
          <p className="vi-muted">{text(item, 'failure_code', 'No failure')}</p>
          {rows(item.entries).map(entry => (
            <div className="vi-benchmark-entry" key={text(entry, 'id')}>
              <strong>{text(entry, 'provider_id')} / {text(entry, 'model_id')}</strong>
              <span>cost {text(entry, 'cost_amount', '—')} · latency {text(entry, 'latency_ms', '—')} ms · verdict {text(entry, 'verdict_id', 'not observed')}</span>
            </div>
          ))}
          <div className="vi-matrix">
            {DIMENSIONS.map(dimension => <span key={dimension}><b>{dimension.replaceAll('_', ' ')}</b><em>{rows(item.entries).length ? dimensionValue(rows(item.entries)[0], dimension) : 'NOT_OBSERVED'}</em></span>)}
            <span><b>cost</b><em>see entries</em></span><span><b>latency</b><em>see entries</em></span>
          </div>
        </article>
      ))}
    </section>
  );
}

function PatternsView({ patterns }: { patterns: Row[] }) {
  return (
    <section className="vi-section" aria-label="Patterns">
      <div className="vi-section-heading"><div><span className="analysis-result__kicker">EVIDENCE → STRUCTURE</span><h2>Patterns</h2></div><span>{patterns.length} patterns</span></div>
      {!patterns.length ? <p className="panel-empty">暂无 Pattern evidence。</p> : patterns.map(item => (
        <article className="vi-card" key={text(item, 'id')}>
          <div className="vi-card-heading"><strong>{text(item, 'name')}</strong><span className={`vi-status vi-status--${statusClass(text(item, 'lifecycle_status', 'candidate'))}`}>{text(item, 'lifecycle_status', 'candidate').toUpperCase()}</span></div>
          <p>{text(item, 'category')} · confidence {text(item, 'confidence', '0')}</p>
          <p>{text(item, 'expected_effect', 'No expected effect recorded.')}</p>
          <div className="vi-evidence-counts"><span>positive {text(item, 'positive_evidence_count', '0')}</span><span>negative {text(item, 'negative_evidence_count', '0')}</span><span>counter {text(item, 'counter_evidence_count', '0')}</span></div>
          <pre className="vi-pre">{jsonText(item.conditions)}{`\n`}{jsonText(item.structure)}</pre>
        </article>
      ))}
    </section>
  );
}

function TemplatesView({ templates }: { templates: Row[] }) {
  return (
    <section className="vi-section" aria-label="Templates">
      <div className="vi-section-heading"><div><span className="analysis-result__kicker">QUALIFIED STRUCTURES</span><h2>Templates</h2></div><span>{templates.length} revisions</span></div>
      {!templates.length ? <p className="panel-empty">暂无 Template revision。</p> : templates.map(item => (
        <article className="vi-card" key={text(item, 'id')}>
          <div className="vi-card-heading"><strong>{text(item, 'name')} · v{text(item, 'version')}</strong><span className={`vi-status vi-status--${statusClass(text(item, 'qualification_status', 'candidate'))}`}>{text(item, 'qualification_status', 'candidate').toUpperCase()}</span></div>
          <p>qualification runs: {text(item, 'qualification_run_count', '0')} · last: {text(item, 'last_qualified_at', 'not qualified')}</p>
          <p>source patterns: {jsonText(item.source_pattern_ids, 'none')}</p>
          <p>required slots: {jsonText(item.required_slots, 'none')}</p>
          <pre className="vi-pre">{jsonText(item.constraints, 'No constraints recorded.')}</pre>
        </article>
      ))}
    </section>
  );
}
