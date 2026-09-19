/**
 * D7-K browser-level product E2E (Playwright).
 *
 * NOT executed during the local D7 qualification (no browser harness in that
 * environment). Run with:
 *   npx playwright install chromium
 *   NEXT_PUBLIC_API_BASE=<api> npx playwright test e2e/product.spec.ts
 *
 * Requires a running RC2 API + web stack. Demo/qualification providers are
 * acceptable for expensive stages; UI/API/runtime must be real.
 */
import { test, expect } from '@playwright/test';

const API = process.env.E2E_API_BASE || 'http://localhost:8001';
const WEB = process.env.E2E_WEB_BASE || 'http://localhost:3000';

async function loginAs(page: import('@playwright/test').Page, email: string) {
  await page.goto(`${WEB}/login`);
  // Uses the standard login form; the RC2 demo environment seeds this user.
  await page.getByLabel(/邮箱|email/i).fill(email);
  await page.getByLabel(/密码|password/i).fill(process.env.E2E_PASSWORD || 'test-password');
  await page.getByRole('button', { name: /登录|sign in/i }).click();
  await expect(page).toHaveURL(/workspace|studio/);
}

test('BROWSER-E2E-1 Quick Start', async ({ page }) => {
  await loginAs(page, 'e2e1@hevi.test');
  await page.goto(`${WEB}/workspace`);
  await page.getByLabel('项目类型').selectOption('short-video');
  await page.getByRole('button', { name: '开始创建' }).click();
  await expect(page.getByTestId('quickstart-message')).toBeVisible();
});

test('BROWSER-E2E-2 character library cross-project reuse', async ({ page }) => {
  await loginAs(page, 'e2e2@hevi.test');
  await page.goto(`${WEB}/workspace`);
  await page.getByRole('tab', { name: '角色库' }).click();
  await page.getByLabel('角色名称').fill('E2E Anna');
  await page.getByRole('button', { name: '保存到角色库' }).click();
  await expect(page.getByText('E2E Anna')).toBeVisible();
});

test('BROWSER-E2E-3 continuity WARN/BLOCK', async ({ page }) => {
  await loginAs(page, 'e2e3@hevi.test');
  await page.goto(`${WEB}/workspace`);
  await page.getByLabel('当前项目 ID').fill('e2e-continuity');
  await page.getByRole('tab', { name: '连续性' }).click();
  await expect(page.getByTestId('continuity-panel')).toBeVisible();
});

test('BROWSER-E2E-4 repair confirm/refuse', async ({ page }) => {
  await loginAs(page, 'e2e4@hevi.test');
  await page.goto(`${WEB}/workspace`);
  await page.getByLabel('当前项目 ID').fill('e2e-repair');
  await page.getByRole('tab', { name: '制作问题' }).click();
  await expect(page.getByTestId('production-issues')).toBeVisible();
});

test('BROWSER-E2E-5 tenant isolation', async ({ page, request }) => {
  await loginAs(page, 'e2e5a@hevi.test');
  const created = await request.post(`${API}/api/identities`, {
    data: { canonical_name: 'Private', voice_id: 'v' },
  });
  const identityId = (await created.json()).identity_id;
  await page.evaluate(() => window.localStorage.clear());
  await loginAs(page, 'e2e5b@hevi.test');
  await page.goto(`${WEB}/workspace`);
  await page.getByRole('tab', { name: '角色库' }).click();
  await expect(page.getByText('Private')).toHaveCount(0);
});
