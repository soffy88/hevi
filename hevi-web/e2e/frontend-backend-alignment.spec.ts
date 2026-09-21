/**
 * Frontend/backend alignment qualification.  These tests use the real auth,
 * production entrypoint, task projection, and readiness probes.
 */
import { test, expect, type APIRequestContext, type Page, type Playwright } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const API = process.env.E2E_API_BASE || 'http://127.0.0.1:18080';
const COMPOSE = '../hevi/deploy/docker-compose-live.yml';
const PASSWORD = 'alignment-e2e-password-123';

let api: APIRequestContext;
let token: string;

async function registerUser(playwright: Playwright): Promise<string> {
  const request = await playwright.request.newContext();
  try {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const email = `frontend-alignment-${Date.now()}-${attempt}@hevi-e2e.com`;
      const response = await request.post(`${API}/api/auth/register`, {
        data: { email, password: PASSWORD, display_name: 'Frontend alignment' },
      });
      if (response.ok()) {
        const body = await response.json() as { access_token?: string };
        if (!body.access_token) throw new Error('register response omitted access_token');
        return body.access_token;
      }
      if (response.status() !== 429) {
        throw new Error(`register failed: ${response.status()} ${await response.text()}`);
      }
      await new Promise(resolve => setTimeout(resolve, 15_000));
    }
  } finally {
    await request.dispose();
  }
  throw new Error('register remained rate-limited');
}

async function authedPage(page: Page): Promise<void> {
  await page.addInitScript(value => {
    window.localStorage.setItem('hevi_token', value);
  }, token);
}

async function getTask(taskId: string): Promise<{ status: string; production_id?: string; revision_id?: string; config_json?: Record<string, unknown> }> {
  const response = await api.get(`${API}/api/tasks/${taskId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return await response.json() as { status: string; production_id?: string; revision_id?: string; config_json?: Record<string, unknown> };
}

test.beforeAll(async ({ playwright }) => {
  token = await registerUser(playwright);
  api = await playwright.request.newContext();
});

test.afterAll(async () => {
  await api.dispose();
});

test('real production create reaches the canonical task/artifact evidence UI', async ({ page }) => {
  await authedPage(page);
  await page.goto('/production');
  await expect(page.getByTestId('production-readiness')).toHaveText('READY', { timeout: 20_000 });

  const createResponsePromise = page.waitForResponse(response =>
    response.url().endsWith('/api/pipeline/productions') && response.request().method() === 'POST');
  await page.getByLabel('script/text').fill('Frontend backend alignment qualification path.');
  await page.getByRole('button', { name: '创建 production' }).click();
  const createResponse = await createResponsePromise;
  expect(createResponse.status()).toBe(201);
  const created = await createResponse.json() as { id?: string; task_id?: string };
  const taskId = created.task_id ?? created.id;
  expect(taskId).toBeTruthy();

  await expect(page.locator('tbody tr').filter({ hasText: `#${taskId!.slice(0, 8)}` })).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => (await getTask(taskId!)).status, {
    timeout: 120_000,
    intervals: [3_000],
  }).toBe('completed');

  await page.reload();
  const row = page.locator('tbody tr').filter({ hasText: `#${taskId!.slice(0, 8)}` });
  await expect(row).toContainText('已完成', { timeout: 20_000 });
  await row.getByRole('button', { name: '查看 evidence' }).click();
  await expect(page.getByTestId('production-evidence')).toBeVisible();
  await expect(page.getByText(taskId!)).toBeVisible();
  await expect(page.getByText('Artifact Currency authority')).toBeVisible();
  await expect(page.getByText('Quality evidence')).toBeVisible();
});

test('real RepairIncident failure is shown without frontend success inference', async ({ page }) => {
  const productionRunId = `frontend-failure-${Date.now()}`;
  const opened = await api.post(`${API}/api/incidents/open`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      production_run_id: productionRunId,
      node_key: 'artifact.registration',
      failure: 'DELIVERY_INTEGRITY',
      evidence: { signature: 'frontend alignment deterministic failure', may_incur_cost: false },
    },
  });
  expect(opened.status()).toBe(201);
  const incident = await opened.json() as { incident_id: string };

  await authedPage(page);
  await page.goto('/workspace');
  await page.getByLabel('当前项目 ID').fill(productionRunId);
  await page.getByRole('tab', { name: '制作问题' }).click();
  await expect(page.getByTestId(`issue-${incident.incident_id}`)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId(`issue-${incident.incident_id}`)).toContainText('DELIVERY_INTEGRITY');
  await expect(page.getByTestId(`issue-${incident.incident_id}`)).toContainText('已检测，待处理');
});

test('worker-down readiness is visible and recovers from the real backend', async ({ page }) => {
  await authedPage(page);
  await page.goto('/production');
  await expect(page.getByTestId('production-readiness')).toHaveText('READY', { timeout: 20_000 });

  execFileSync('docker', ['compose', '-f', COMPOSE, 'stop', 'worker'], { stdio: 'pipe' });
  try {
    await page.waitForTimeout(17_000);
    await page.reload();
    await expect(page.getByTestId('production-readiness')).toHaveText('UNAVAILABLE', { timeout: 20_000 });
    await expect(page.getByText(/worker 或其他依赖未 ready/)).toBeVisible();
  } finally {
    execFileSync('docker', ['compose', '-f', COMPOSE, 'start', 'worker'], { stdio: 'pipe' });
  }

  await page.waitForTimeout(8_000);
  await page.reload();
  await expect(page.getByTestId('production-readiness')).toHaveText('READY', { timeout: 45_000 });
});
