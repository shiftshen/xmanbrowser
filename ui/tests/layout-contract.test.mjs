import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const tauri = JSON.parse(readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
const releaseMac = readFileSync(new URL("../../tools/release_macos.sh", import.meta.url), "utf8");

function rule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return css.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`, "s"))?.[1] ?? "";
}

test("the application grid cannot grow wider than its viewport", () => {
  assert.match(rule(".app"), /grid-template-columns:\s*224px\s+minmax\(0,\s*1fr\)/);
  assert.match(rule(".main"), /min-width:\s*0/);
  assert.match(rule(".card"), /min-width:\s*0/);
});

test("long profile names ellipsize without pushing action controls away", () => {
  const title = rule(".card .title");
  assert.match(title, /min-width:\s*0/);
  assert.match(title, /overflow:\s*hidden/);
  assert.match(title, /text-overflow:\s*ellipsis/);
  assert.match(title, /white-space:\s*nowrap/);
  assert.match(app, /className="title" title=\{p\.name\}/);
});

test("long notes wrap safely and occupy no more than three lines", () => {
  const note = rule(".note");
  assert.match(note, /overflow-wrap:\s*anywhere/);
  assert.match(note, /-webkit-line-clamp:\s*3/);
  assert.match(note, /overflow:\s*hidden/);
  assert.match(app, /className="note" title=\{p\.note\}/);
});

test("the toolbar stays readable at the desktop minimum width", () => {
  assert.match(rule(".toolbar button"), /white-space:\s*nowrap/);
  assert.match(css, /@media\s*\(max-width:\s*1050px\)[\s\S]*?\.toolbar\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.match(css, /@media\s*\(max-width:\s*1050px\)[\s\S]*?\.search\s*\{[^}]*width:\s*150px/);
  assert.match(css, /@media\s*\(max-width:\s*1050px\)[\s\S]*?\.toolbar h1\s*\{[^}]*text-overflow:\s*ellipsis/);
});

test("the desktop window opens at a small-laptop-friendly size", () => {
  const window = tauri.app.windows[0];
  assert.ok(window.width <= 1024);
  assert.ok(window.height <= 680);
  assert.ok(window.minWidth <= 720);
  assert.ok(window.minHeight <= 520);
});

test("the app declares its favicon instead of producing a console 404", () => {
  assert.match(index, /<link\s+rel="icon"[^>]+href="\/src\/assets\/logo-shield\.png"/);
});

test("manual update checks keep their result beside the control", () => {
  assert.match(app, /type UpdateCheckState = "idle" \| "checking" \| "available" \| "latest" \| "error"/);
  assert.match(app, /className=\{`ver-status \$\{updateCheckState\}`\}/);
  assert.match(app, /role="status" aria-live="polite"/);
  assert.match(app, /t\("upd\.found", update\.version\)/);
  assert.match(app, /t\("upd\.failed"\)/);
  assert.match(rule(".ver-status"), /min-height:/);
  assert.match(rule(".ver-status.error"), /color:\s*var\(--red\)/);
});

test("update checks use a bounded retry instead of failing silently", () => {
  assert.match(app, /const UPDATE_CHECK_TIMEOUT_MS = 12_000/);
  assert.match(app, /async function requestUpdate\(attempts = 2\)/);
  assert.match(app, /checkUpdate\(\{ timeout: UPDATE_CHECK_TIMEOUT_MS/);
  assert.match(app, /if \(attempt < attempts\)/);
  assert.doesNotMatch(app, /catch\(\(\) => \{ \/\* offline \/ no update \*\/ \}\)/);
});

test("macOS updater archives exclude AppleDouble metadata that Tauri cannot unpack", () => {
  assert.match(releaseMac, /COPYFILE_DISABLE=1\s+tar czf/);
  assert.match(releaseMac, /verify_updater_archive\.py/);
});

test("install failures preserve string errors and remain visible for retry", () => {
  assert.match(app, /function updateErrorMessage\(error: unknown\)/);
  assert.match(app, /const message = updateErrorMessage\(error\)/);
  assert.match(app, /setUpdateInstallError\(message\)/);
  assert.match(app, /className="upd-error" role="alert"/);
});
