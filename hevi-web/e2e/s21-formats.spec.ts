/**
 * S21：首页“出品形式”入口的浏览器验收。
 *
 * 桌面 + 手机宽度，逐个形式走一遍：卡片存在、可选、直达链接生效；
 * 受限形式显示“即将开放”且不可点；可选形式能出脚本与分镜。
 * 认证走真实 /api/auth 注册（无测试专用后门）。
 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API_BASE || 'http://127.0.0.1:8001';
const PASSWORD = 's21-password-123';

const FORMATS = [
  { id: 'history_scene', label: '历史现场' },
  { id: 'digital_human', label: '数字人口播' },
  { id: 'live_drama', label: '真人短剧' },
  { id: 'comic_drama', label: '漫剧' },
  { id: 'animation', label: '动画' },
  { id: 'explainer', label: '知识讲解' },
];

let seq = 0;
function uniqueEmail(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now()}-${seq}@hevi-s21.com`;
}

async function registerUser(request: APIRequestContext, prefix: string) {
  const email = uniqueEmail(prefix);
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const response = await request.post(`${API}/api/auth/register`, {
      data: { email, password: PASSWORD, display_name: prefix },
    });
    if (response.ok()) {
      const body = await response.json();
      return { email, token: body.access_token as string };
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

test.describe('S21 出品形式入口', () => {
  let token = '';
  let available: Record<string, boolean> = {};

  test.beforeAll(async ({ request }) => {
    ({ token } = await registerUser(request, 's21-e2e'));
    const response = await request.get(`${API}/api/studio/formats`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const body = await response.json();
    available = Object.fromEntries(
      (body.formats as Array<{ id: string; available: boolean }>).map((item) => [item.id, item.available]),
    );
    expect(Object.keys(available).length).toBeGreaterThanOrEqual(6);
  });

  test('首页展示输入框与形式卡片', async ({ page }) => {
    await authedPage(page, token);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: '先选一种出品形式，再开始' })).toBeVisible();
    await expect(page.getByLabel('创作输入')).toBeVisible();
    for (const item of FORMATS) {
      await expect(page.locator(`[data-format="${item.id}"]`)).toBeVisible();
    }
  });

  const VIEWPORTS = [
    { name: '桌面', width: 1280, height: 720 },
    { name: '手机', width: 390, height: 844 },
  ] as const;

  for (const viewport of VIEWPORTS) {
    for (const item of FORMATS) {
      test(`${viewport.name} · 直达链接 /create?format=${item.id}`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await authedPage(page, token);
        await page.goto(`/create?format=${item.id}`);
        const card = page.locator(`[data-format="${item.id}"]`);
        await expect(card).toBeVisible();
        if (!available[item.id]) {
          await expect(card).toContainText('即将开放');
          await card.click();
          await expect(page).toHaveURL(/\/create/);
          await expect(page.getByRole('alert')).toContainText('即将开放');
        } else {
          await expect(card).toHaveAttribute('aria-pressed', 'true');
          await page.getByLabel('创作输入').fill(`S21 验收：${item.label}的一分钟示例`);
          await page.getByRole('button', { name: '生成脚本与分镜' }).click();
          await expect(page.getByText('分镜确认', { exact: true })).toBeVisible({ timeout: 120_000 });
          await expect(page.getByRole('button', { name: '确认并渲染' })).toBeVisible();
          expect(await page.locator('.create-entry__shot').count()).toBeGreaterThan(0);
          const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
          expect(overflow).toBeLessThanOrEqual(2);
        }
      });
    }
  }

  test('手机宽度 390 无横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await authedPage(page, token);
    await page.goto('/create');
    for (const item of FORMATS) {
      await expect(page.locator(`[data-format="${item.id}"]`)).toBeVisible();
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(2);
  });
});
