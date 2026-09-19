'use client';

/**
 * D6-A/B 角色库 — product surface over persistent identities.
 * Consumes canonical identityApi only; no local version maths.
 */
import { useEffect, useMemo, useState } from 'react';
import { identityApi } from '@/lib/api-client';
import { PRODUCT_COPY as C } from '@/lib/product-copy';
import type { IdentitySummary } from '@/types/api';
import { ActionButton, Card, FormField, SectionHeader } from '@/components/shared/ui';

export function CharacterLibrary({ projectId = '' }: { projectId?: string }) {
  const [items, setItems] = useState<IdentitySummary[]>([]);
  const [query, setQuery] = useState('');
  const [name, setName] = useState('');
  const [selected, setSelected] = useState<IdentitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      setItems(await identityApi.list());
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '角色库加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      item =>
        item.canonical_name.toLowerCase().includes(q) ||
        item.aliases.some(a => a.toLowerCase().includes(q)),
    );
  }, [items, query]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await fn();
      setMessage(ok);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setBusy(false);
    }
  };

  const create = () =>
    act(async () => {
      if (!name.trim()) throw new Error('请填写角色名称');
      await identityApi.create(name.trim());
      setName('');
    }, '已保存到角色库');

  const useInProject = (identityId: string) => {
    if (!projectId.trim()) {
      setError('请先填写当前项目 ID');
      return;
    }
    void act(() => identityApi.bind(projectId.trim(), identityId), '已用于当前项目（固定当前版本）');
  };

  const upgrade = (identity: IdentitySummary) =>
    act(async () => {
      const detail = await identityApi.inspect(identity.identity_id);
      const stale = (detail.bindings ?? []).filter(
        (b: { pinned_identity_version: number }) =>
          b.pinned_identity_version < detail.identity_version,
      );
      for (const binding of stale) {
        await identityApi.upgrade(binding.binding_id);
      }
    }, '已升级到当前版本');

  return (
    <section className="product-lib" data-testid="character-library" aria-busy={loading}>
      <SectionHeader icon="🎭" title={C.characterLibrary.title} subtitle={C.characterLibrary.subtitle} />

      <FormField label="搜索角色">
        <input
          aria-label="搜索角色"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="输入名称或别名"
        />
      </FormField>

      <FormField label="新建角色">
        <input
          aria-label="角色名称"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={C.characterLibrary.createPlaceholder}
        />
      </FormField>
      <ActionButton onClick={create} loading={busy}>
        {C.characterLibrary.saveToLibrary}
      </ActionButton>

      {message && <p role="status" data-testid="library-message">{message}</p>}
      {error && <p role="alert" data-testid="library-error">{error}</p>}

      {loading && <p data-testid="library-loading">加载中…</p>}
      {!loading && filtered.length === 0 && (
        <p data-testid="library-empty">{C.characterLibrary.empty}</p>
      )}

      <ul data-testid="library-list" aria-label="角色列表">
        {filtered.map(identity => (
          <li key={identity.identity_id} data-testid={`identity-${identity.identity_id}`}>
            <Card
              title={identity.canonical_name}
              subtitle={`v${identity.identity_version} · ${identity.voice_id}`}
              headerRight={
                identity.upgrade_available ? (
                  <span className="badge" data-testid={`upgrade-available-${identity.identity_id}`}>
                    {C.characterLibrary.upgradeAvailable}
                  </span>
                ) : undefined
              }
            >
              <p>
                {C.characterLibrary.appearances}×{identity.appearance_count} ·{' '}
                {C.characterLibrary.projectsUsing}: {identity.projects_using.join('、') || '—'}
              </p>
              <div className="actions">
                <ActionButton
                  variant="secondary"
                  size="sm"
                  onClick={() => setSelected(identity)}
                >
                  查看
                </ActionButton>
                <ActionButton
                  variant="secondary"
                  size="sm"
                  onClick={() => useInProject(identity.identity_id)}
                >
                  {C.characterLibrary.useInProject}
                </ActionButton>
                {identity.upgrade_available && (
                  <ActionButton size="sm" onClick={() => upgrade(identity)} loading={busy}>
                    {C.characterLibrary.upgrade}
                  </ActionButton>
                )}
                <ActionButton
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    act(() => identityApi.archive(identity.identity_id), '已归档（历史项目不受影响）')
                  }
                >
                  {C.characterLibrary.archive}
                </ActionButton>
              </div>
              {selected?.identity_id === identity.identity_id && (
                <div data-testid={`identity-detail-${identity.identity_id}`}>
                  <h4>{C.characterLibrary.appearances}</h4>
                  <ul>
                    {identity.appearances.map(a => (
                      <li key={a.appearance_id}>
                        {a.label} · v{a.version}
                      </li>
                    ))}
                  </ul>
                  <p>
                    {C.characterLibrary.voice}: {identity.voice_id}
                  </p>
                </div>
              )}
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}
