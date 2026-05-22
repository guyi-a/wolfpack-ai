/**
 * Wolfpack preload 脚本.
 *
 * 在 Renderer 拿到 window 对象之前跑, 用 contextBridge 把 Main 进程发现的
 * 后端 apiBase 暴露到 window.__WOLFPACK__.apiBase. 前端 lib/api.ts 优先读它.
 *
 * apiBase 通过 BrowserWindow webPreferences.additionalArguments 传进来,
 * 形如 `--wolfpack-api-base=http://127.0.0.1:8083`. dev 模式传空字符串
 * (前端走 Vite proxy /api, 不读这个值).
 */

import { contextBridge } from 'electron';

const PREFIX = '--wolfpack-api-base=';

function readApiBase(): string {
  const arg = process.argv.find((a) => a.startsWith(PREFIX));
  return arg ? arg.slice(PREFIX.length) : '';
}

contextBridge.exposeInMainWorld('__WOLFPACK__', {
  apiBase: readApiBase(),
});
