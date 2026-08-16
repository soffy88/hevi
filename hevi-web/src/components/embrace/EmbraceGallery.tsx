/**
 * EmbraceGallery — 3O 内化资产画廊(镜头配方卡 / 审美准则 / 失败模式)
 *
 * 数据源: hevi-web/public/embrace/*.json(scripts/export_embrace_assets.py 导出,
 * 零 API 依赖,构建前跑一次即可)。三切签:
 *   🎴 镜头配方卡 —— 类别过滤 + 关键词搜索 + 卡详情(参数/已知坑/实现要点)+ 复制卡名
 *   📜 审美准则   —— 族切签(R/Q/S/C/P)+ 规则/判例/自检
 *   🩹 失败模式   —— 层过滤 + 负向子句(自我校正闭环的负向侧)
 */
'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { storePickedCard } from '@/lib/recipe-card-bridge';
import type {
  CanonFamily,
  CanonRule,
  CardCategory,
  FailureLayer,
  FailureMode,
  ShotRecipeCard,
} from '@/types/embrace';
import {
  CANON_FAMILY_LABEL,
  CARD_CATEGORY_LABEL,
  CARD_ENERGY_LABEL,
  FAILURE_LAYER_LABEL,
} from '@/types/embrace';

type Tab = 'cards' | 'canon' | 'failures';

const TABS: { key: Tab; label: string }[] = [
  { key: 'cards', label: '🎴 镜头配方卡' },
  { key: 'canon', label: '📜 审美准则' },
  { key: 'failures', label: '🩹 失败模式' },
];

async function loadJson<T>(url: string): Promise<T[]> {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`加载失败 ${url}: ${res.status}`);
  return res.json() as Promise<T[]>;
}

export function EmbraceGallery() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('cards');
  const [cards, setCards] = useState<ShotRecipeCard[]>([]);
  const [canon, setCanon] = useState<CanonRule[]>([]);
  const [failures, setFailures] = useState<FailureMode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 卡片页状态
  const [category, setCategory] = useState<CardCategory | 'all'>('all');
  const [query, setQuery] = useState('');
  const [openCard, setOpenCard] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  // 准则页状态
  const [family, setFamily] = useState<CanonFamily | 'all'>('all');
  // 失败模式页状态
  const [layer, setLayer] = useState<FailureLayer | 'all'>('all');

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [c, cn, f] = await Promise.all([
          loadJson<ShotRecipeCard>('/embrace/cards.json'),
          loadJson<CanonRule>('/embrace/canon.json'),
          loadJson<FailureMode>('/embrace/failure_modes.json'),
        ]);
        if (!live) return;
        setCards(c);
        setCanon(cn);
        setFailures(f);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
  }, []);

  const categories = useMemo(
    () => Array.from(new Set(cards.map(c => c.category))),
    [cards],
  );
  const families = useMemo(
    () => Array.from(new Set(canon.map(r => r.code[0] as CanonFamily))),
    [canon],
  );
  const layers = useMemo(
    () => Array.from(new Set(failures.map(f => f.layer))),
    [failures],
  );

  const filteredCards = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cards.filter(c =>
      (category === 'all' || c.category === category) &&
      (q === '' ||
        c.name.toLowerCase().includes(q) ||
        c.purpose.toLowerCase().includes(q) ||
        c.known_pitfalls.some(p => p.toLowerCase().includes(q))),
    );
  }, [cards, category, query]);

  const filteredCanon = useMemo(
    () => canon.filter(r => family === 'all' || r.code.startsWith(family)),
    [canon, family],
  );

  const filteredFailures = useMemo(
    () => failures.filter(f => layer === 'all' || f.layer === layer),
    [failures, layer],
  );

  const copyCardName = async (name: string) => {
    try {
      await navigator.clipboard.writeText(name);
      setCopied(name);
      setTimeout(() => setCopied(v => (v === name ? null : v)), 1200);
    } catch {
      // clipboard 不可用(非 https/iframe)时静默
    }
  };

  const useCard = (card: ShotRecipeCard) => {
    storePickedCard(card);
    router.push('/director');
  };

  return (
    <div className="embr">
      <header className="embr__hero">
        <p className="embr__eyebrow">3O 内化资产 · EMBRACE</p>
        <h1>镜头配方卡画廊</h1>
        <p>
          可执行的运镜/动效词汇表 + 判例式审美准则 + 失败模式负向子句。
          来源: claude-video / story-to-handdrawn / dramaclaw / video-shotcraft 方法论内化。
        </p>
      </header>

      <nav className="embr__tabs">
        {TABS.map(t => (
          <button
            key={t.key}
            type="button"
            className="embr__tab"
            data-active={tab === t.key ? 'true' : undefined}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {loading && <p className="embr__empty">加载中…</p>}
      {error && <p className="embr__error">{error}</p>}

      {!loading && !error && tab === 'cards' && (
        <section>
          <div className="embr__filters">
            <select
              aria-label="按类别过滤"
              value={category}
              onChange={e => setCategory(e.target.value as CardCategory | 'all')}
            >
              <option value="all">全部类别</option>
              {categories.map(cat => (
                <option key={cat} value={cat}>{CARD_CATEGORY_LABEL[cat]}</option>
              ))}
            </select>
            <input
              type="search"
              placeholder="搜索卡名 / 目的 / 已知坑…"
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            <span className="embr__count">{filteredCards.length} 张卡</span>
          </div>

          <div className="embr__grid">
            {filteredCards.map(card => (
              <article
                key={card.name}
                className="embr__card"
                data-open={openCard === card.name ? 'true' : undefined}
              >
                <button
                  type="button"
                  className="embr__card-head"
                  onClick={() => setOpenCard(openCard === card.name ? null : card.name)}
                >
                  <span className="embr__card-cat">{CARD_CATEGORY_LABEL[card.category]}</span>
                  <strong>{card.name}</strong>
                  <em data-energy={card.energy}>{CARD_ENERGY_LABEL[card.energy]}</em>
                  <span className="embr__card-dur">{card.suggested_duration_s}s</span>
                </button>
                <p className="embr__card-purpose">{card.purpose}</p>
                {openCard === card.name && (
                  <div className="embr__card-detail">
                    {Object.keys(card.params).length > 0 && (
                      <div className="embr__params">
                        {Object.entries(card.params).map(([k, v]) => (
                          <span key={k}><i>{k}</i> = {String(v)}</span>
                        ))}
                      </div>
                    )}
                    {card.implementation_notes && (
                      <p className="embr__notes">{card.implementation_notes}</p>
                    )}
                    {card.known_pitfalls.length > 0 && (
                      <ul className="embr__pitfalls">
                        {card.known_pitfalls.map(pit => (
                          <li key={pit}>⚠ {pit}</li>
                        ))}
                      </ul>
                    )}
                    {card.demo_ref && (
                      <code className="embr__demoref">{card.demo_ref}</code>
                    )}
                  </div>
                )}
                <div className="embr__card-actions">
                  <button
                    type="button"
                    className="embr__copy"
                    onClick={() => copyCardName(card.name)}
                  >
                    {copied === card.name ? '✓ 已复制' : '⧉ 复制卡名'}
                  </button>
                  <button
                    type="button"
                    className="embr__use"
                    onClick={() => useCard(card)}
                  >
                    🎬 用此卡出片
                  </button>
                  <button
                    type="button"
                    className="embr__toggle"
                    onClick={() => setOpenCard(openCard === card.name ? null : card.name)}
                  >
                    {openCard === card.name ? '收起' : '详情'}
                  </button>
                </div>
              </article>
            ))}
          </div>
          {filteredCards.length === 0 && (
            <p className="embr__empty">没有匹配的卡(搜索词或类别过窄?)</p>
          )}
        </section>
      )}

      {!loading && !error && tab === 'canon' && (
        <section>
          <div className="embr__filters">
            {families.map(f => (
              <button
                key={f}
                type="button"
                className="embr__chip"
                data-active={family === f ? 'true' : undefined}
                onClick={() => setFamily(family === f ? 'all' : f)}
              >
                {CANON_FAMILY_LABEL[f]}
              </button>
            ))}
            <span className="embr__count">{filteredCanon.length} 条</span>
          </div>
          <div className="embr__list">
            {filteredCanon.map(rule => (
              <article key={rule.code} className="embr__rule">
                <header>
                  <strong>{rule.code}</strong>
                  <span>{rule.rule}</span>
                  {rule.allow_violation && <em>允许有意违反</em>}
                </header>
                {rule.precedent && (
                  <p className="embr__precedent">判例: {rule.precedent}</p>
                )}
                <p className="embr__selfcheck">自检: {rule.self_check}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      {!loading && !error && tab === 'failures' && (
        <section>
          <div className="embr__filters">
            {layers.map(l => (
              <button
                key={l}
                type="button"
                className="embr__chip"
                data-active={layer === l ? 'true' : undefined}
                onClick={() => setLayer(layer === l ? 'all' : l)}
              >
                {FAILURE_LAYER_LABEL[l]}
              </button>
            ))}
            <span className="embr__count">{filteredFailures.length} 条</span>
          </div>
          <div className="embr__list">
            {filteredFailures.map(f => (
              <article key={f.code} className="embr__failure">
                <header>
                  <strong>{f.code}</strong>
                  <span>{FAILURE_LAYER_LABEL[f.layer]}</span>
                </header>
                <p>{f.description}</p>
                <code>负向子句: {f.negative_clause}</code>
                {f.keywords.length > 0 && (
                  <div className="embr__keywords">
                    {f.keywords.map(k => <span key={k}>{k}</span>)}
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
