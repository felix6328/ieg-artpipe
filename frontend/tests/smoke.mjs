import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright';

const base = process.env.ASSETGATE_URL || 'http://127.0.0.1:8765';
const source = process.argv[2];
assert(source, 'Pass the generated missing_uv.glb fixture. Use a disposable ASSETGATE_STORAGE for this test.');
const browser = await chromium.launch({
  executablePath: process.env.ASSETGATE_CHROME || undefined,
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
});
const failures = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(45000);
  page.on('pageerror', error => failures.push(error.message));
  await page.goto(base + '/workbench');
  await page.getByRole('heading', { name: '资产总览' }).waitFor();
  await page.locator('.ag-app-bar').getByRole('button', { name: /上传模型/ }).click();
  await page.locator('input[type=file]').setInputFiles(source);
  await page.getByLabel('资产名称').fill('验收模型 · 运输箱');
  await page.getByRole('button', { name: '上传并检查' }).click();
  await page.getByRole('heading', { name: '验收模型 · 运输箱' }).waitFor();
  const grid = page.getByRole('button', { name: '网格', exact: true });
  const box = page.getByRole('button', { name: '包围盒', exact: true });
  await page.waitForFunction(() => Array.from(document.querySelectorAll('.ag-viewer button')).every(button => !button.disabled));
  const canvas = page.getByLabel('交互式三维预览');
  assert(await canvas.evaluate(element => !!element.getContext('webgl2')));
  await grid.click();
  assert.equal(await grid.getAttribute('aria-pressed'), 'false');
  await box.click();
  assert.equal(await box.getAttribute('aria-pressed'), 'true');
  const surface = await canvas.boundingBox();
  assert(surface && surface.width > 200);
  await page.mouse.move(surface.x + surface.width / 2, surface.y + surface.height / 2);
  await page.mouse.down();
  await page.mouse.move(surface.x + surface.width / 2 + 55, surface.y + surface.height / 2 - 35, { steps: 5 });
  await page.mouse.up();
  await page.mouse.wheel(0, -200);
  await page.mouse.down({ button: 'right' });
  await page.mouse.move(surface.x + surface.width / 2 + 105, surface.y + surface.height / 2 - 20, { steps: 5 });
  await page.mouse.up({ button: 'right' });
  await page.getByRole('button', { name: '复位视角' }).click();
  if (process.env.ASSETGATE_SCREENSHOT) await page.screenshot({ path: process.env.ASSETGATE_SCREENSHOT });

  await page.getByRole('button', { name: 'QA 报告', exact: true }).click();
  const uv = page.getByRole('row').filter({ hasText: 'UV_LAYER' });
  await uv.getByText('提醒', { exact: true }).waitFor();
  await page.getByRole('button', { name: '审核与导出', exact: true }).click();
  assert(await page.getByRole('button', { name: '生成 ZIP' }).isDisabled());

  await page.getByRole('button', { name: '模型处理', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Smart UV Project' }).check();
  await page.getByLabel('目标格式').selectOption('GLB');
  await page.getByRole('button', { name: '开始处理' }).click();
  await page.getByText('2 个版本', { exact: false }).waitFor();
  await page.getByRole('button', { name: 'QA 报告', exact: true }).click();
  await page.getByRole('columnheader', { name: '处理前' }).waitFor();
  await uv.getByText('提醒', { exact: true }).waitFor();
  await uv.getByText('通过', { exact: true }).waitFor();

  await page.getByRole('button', { name: '版本历史', exact: true }).click();
  await page.getByText('原始模型', { exact: true }).waitFor();
  await page.getByText('当前版本', { exact: true }).waitFor();
  await page.getByRole('button', { name: '审核与导出', exact: true }).click();
  await page.getByLabel('审核人').fill('浏览器验收');
  await page.getByRole('button', { name: '保存审核' }).click();
  await page.getByText('审核通过', { exact: true }).waitFor();
  await page.getByRole('button', { name: '生成 ZIP' }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: /下载 ZIP/ }).click();
  const zip = await readFile(await (await download).path());
  assert.equal(zip.subarray(0, 2).toString(), 'PK');

  await page.getByRole('link', { name: '任务队列', exact: true }).click();
  await page.getByText('生成 ZIP', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('link', { name: '资产库', exact: true }).click();
  await page.getByRole('heading', { name: '全部资产' }).waitFor();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.getByRole('link', { name: '入库预检', exact: true }).click();
  await page.getByRole('heading', { name: /入库预检/ }).waitFor();
  assert.deepEqual(failures, []);
  console.log('PASS · upload, WebGL camera/grid/bounds, QA comparison, version history, review, ZIP download, jobs, mobile layout and legacy workbench');
} finally {
  await browser.close();
}
