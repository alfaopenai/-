import { chromium } from "playwright";
import { resolve } from "path";

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const fileUrl = `file://${resolve('index.html').replace(/\\/g,'/')}`;
  await page.goto(fileUrl);
  await page.waitForSelector('#deck .deck-card');
  await page.click('[data-card-id="AS"]');
  await page.click('[data-card-id="KS"]');
  await page.click('[data-card-id="Ah"]');
  await page.click('[data-card-id="Kh"]');
  await page.click('[data-card-id="Qd"]');
  await page.click('[data-card-id="Js"]');
  await page.click('#mode-toggle');
  await page.waitForSelector('#solver-results .solver-summary', { timeout: 5000 });
  const summaryText = await page.$eval('#solver-results .solver-summary', el => el.textContent);
  console.log(summaryText);
  await browser.close();
}

main().catch(err => {
  console.error(err);
  process.exitCode = 1;
});
