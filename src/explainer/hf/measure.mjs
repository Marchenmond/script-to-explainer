// Measures the real layout of the composition: for sampled times, the box of every visible piece of text
// (slide text and captions) and how far it is from each edge of the 1920x1080 frame.
// usage: node measure.mjs <project dir> <chrome executable> [step seconds]
import puppeteer from "puppeteer-core";
import { pathToFileURL } from "node:url";
import path from "node:path";

const [dir, chrome, stepArg] = process.argv.slice(2);
const step = Number(stepArg || 0.2);
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--allow-file-access-from-files", "--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080 });
await page.goto(pathToFileURL(path.resolve(dir, "index.html")).href, { waitUntil: "load" });
await page.waitForFunction("window.__stageReady === true", { timeout: 30000 });
const duration = await page.evaluate("window.STAGE.duration");
const out = [];
for (let t = 0; t <= duration - 0.05; t += step) {
  const boxes = await page.evaluate((t) => {
    window.__timelines.explainer.time(t);
    const res = [];
    const walker = document.createTreeWalker(document.getElementById("root"), NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (!n.textContent.trim()) continue;
      const el = n.parentElement;
      let op = 1, vis = true;
      for (let e = el; e && e.id !== "root"; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.display === "none" || cs.visibility === "hidden") { vis = false; break; }
        op *= parseFloat(cs.opacity);
      }
      if (!vis || op < 0.6) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      const b = r.getBoundingClientRect();
      if (b.width < 1) continue;
      res.push({ text: n.textContent.trim().slice(0, 40), l: b.left, r: b.right, t: b.top, b: b.bottom });
    }
    return res;
  }, t);
  for (const b of boxes) out.push({ time: Math.round(t * 100) / 100, ...b });
}
await browser.close();
console.log(JSON.stringify(out));
