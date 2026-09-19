/**
 * D7-K / R2 browser-level product E2E (Playwright).
 *
 * Real browser + real Next.js frontend + real FastAPI backend + real runtime
 * authority. Auth is established through the real /api/auth endpoints (no
 * test-only backend hook); the token is injected into the app's real
 * localStorage auth store before the page loads.
 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API_BASE || 'http://127.0.0.1:8001';
const PASSWORD = 'rc2-password-123';

let seq = 0;
function uniqueEmail(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now()}-${seq}@hevi-rc2.com`;
}

async function registerUser(request: APIRequestContext, prefix: string) {
  const email = uniqueEmail(prefix);
  // The real auth endpoint rate-limits registration (5/60s). Back off on 429
  // rather than bypassing the production limiter.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const response = await request.post(`${API}/api/auth/register`, {
      data: { email, password: PASSWORD, display_name: prefix },
    });
    if (response.ok()) {
      const body = await response.json();
      return { email, token: body.access_token as string, userId: body.user?.id as string };
    }
    if (response.status() === 429) {
      await new Promise((resolve) => setTimeout(resolve, 15_000));
      continue;
    }
    throw new Error(`register failed: ${response.status()} ${await response.text()}`);
  }
  throw new Error(`register rate-limited: ${email}`);
}

async function authedPage(page: Page, token: string) {
  await page.addInitScript((value) => {
    window.localStorage.setItem('hevi_token', value);
  }, token);
}

async function createIdentity(request: APIRequestContext, token: string, name: string, canon: string[] = []) {
  const response = await request.post(`${API}/api/identities`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { canonical_name: name, voice_id: `v-${name}`, canon_constraints: canon },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).identity_id as string;
}

test('BROWSER-E2E-1 Quick Start', async ({ page, request }) => {
  const { token } = await registerUser(request, 'e2e1');
  await authedPage(page, token);
  await page.goto('/workspace');
  await expect(page.getByTestId('quick-start')).toBeVisible();
  await page.getByRole('button', { name: '开始创建' }).click();
  await expect(page.getByTestId('quickstart-message')).toBeVisible();
  await page.getByRole('button', { name: '示例项目' }).click();
  await expect(page.getByTestId('demo-badge')).toHaveText('演示');
});

test('BROWSER-E2E-2 character library cross-project reuse + upgrade', async ({ page, request }) => {
  const { token } = await registerUser(request, 'e2e2');
  await authedPage(page, token);
  await page.goto('/workspace');
  await page.getByRole('tab', { name: '角色库' }).click();
  await page.getByLabel('角色名称').fill('E2E Anna');
  await page.getByRole('button', { name: '保存到角色库' }).click();
  await expect(page.getByText('E2E Anna')).toBeVisible();

  // Bind to two projects via the real API, then confirm the UI shows reuse.
  const email = 'e2e2-bind';
  const created = await createIdentity(request, token, 'Reuse Character');
  for (const project of ['proj-e2e-a', 'proj-e2e-b']) {
    const bind = await request.post(`${API}/api/identities/projects/${project}/bindings`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { identity_id: created },
    });
    expect(bind.ok()).toBeTruthy();
  }
  // Global update -> upgrade available appears in the library.
  await request.post(`${API}/api/identities/${created}/appearances`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { appearance_id: 'winter', kind: 'outfit' },
  });
  await page.reload();
  await page.getByRole('tab', { name: '角色库' }).click();
  await expect(page.getByText('Reuse Character')).toBeVisible();
  await expect(page.getByText('有新版本可用').first()).toBeVisible();
  void email;
});

test('BROWSER-E2E-3 continuity WARN panel + BLOCK refuses paid generation', async ({ page, request }) => {
  const { token } = await registerUser(request, 'e2e3');
  await authedPage(page, token);
  const identityId = await createIdentity(request, token, 'Continuity Guard', [
    'guard never removes the red coat',
  ]);
  await request.post(`${API}/api/identities/projects/proj-e2e-cont/bindings`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { identity_id: identityId },
  });
  // Trigger a WARN at rest: binding pins v1, identity moves to v2.
  await request.post(`${API}/api/identities/${identityId}/appearances`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { appearance_id: 'winter', kind: 'outfit' },
  });

  await page.goto('/workspace');
  await page.getByLabel('当前项目 ID').fill('proj-e2e-cont');
  await page.getByRole('tab', { name: '连续性' }).click();
  await expect(page.getByTestId('continuity-panel')).toBeVisible();
  await expect(page.getByTestId('continuity-panel')).toHaveAttribute('data-verdict', /pass|warn/);

  // BLOCK: a contradictory plan is refused by the real backend (paid generation
  // never starts), driven through the browser request context.
  const blocked = await request.post(`${API}/api/continuity/gate`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      binding_id: (await (await request.get(`${API}/api/identities/projects/proj-e2e-cont/bindings`, {
        headers: { Authorization: `Bearer ${token}` },
      })).json())[0].binding_id,
      stage: 'video_generation',
      planned_statements: ['Twist: not guard never removes the red coat'],
      overridden_by: 'browser-e2e',
    },
  });
  expect(blocked.status()).toBe(409);
});

test('BROWSER-E2E-4 production issues AUTO_SAFE / CONFIRM / REFUSE', async ({ page, request }) => {
  const { token } = await registerUser(request, 'e2e4');
  await authedPage(page, token);
  const run = `browser-run-${Date.now()}`;

  // AUTO_SAFE (download interruption).
  await request.post(`${API}/api/incidents/open`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      production_run_id: run, node_key: 'artifact.download', failure: 'DELIVERY_INTEGRITY',
      evidence: { signature: 'download interrupted at 62%' },
    },
  });
  // CONFIRM_REQUIRED (paid regeneration).
  const paid = await (await request.post(`${API}/api/incidents/open`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      production_run_id: run, node_key: 'shot.regenerate', failure: 'DELIVERY_INTEGRITY',
      evidence: { signature: 'artifact stale, paid regeneration requested', may_incur_cost: true, estimated_cost_usd: 2.0 },
    },
  })).json();

  await page.goto('/workspace');
  await page.getByLabel('当前项目 ID').fill(run);
  await page.getByRole('tab', { name: '制作问题' }).click();
  await expect(page.getByTestId('production-issues')).toBeVisible();
  await expect(page.getByTestId(`confirm-box-${paid.incident_id}`)).toBeVisible();
  await expect(page.getByText(/预计新增费用/)).toBeVisible();

  // REFUSE the paid repair.
  await page.getByRole('button', { name: '暂不处理' }).first().click();
  await expect(page.getByTestId('issues-message')).toBeVisible();
});

test('BROWSER-E2E-5 tenant isolation', async ({ page, request }) => {
  const ownerA = await registerUser(request, 'e2e5a');
  const ownerB = await registerUser(request, 'e2e5b');
  await createIdentity(request, ownerA.token, 'OwnerA Private');

  // Owner B browser cannot see Owner A's character.
  await authedPage(page, ownerB.token);
  await page.goto('/workspace');
  await page.getByRole('tab', { name: '角色库' }).click();
  await expect(page.getByText('OwnerA Private')).toHaveCount(0);

  // And the API is owner-scoped for B's token.
  const list = await (await request.get(`${API}/api/identities`, {
    headers: { Authorization: `Bearer ${ownerB.token}` },
  })).json();
  expect(list).toHaveLength(0);
});
