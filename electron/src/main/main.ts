/**
 * Wolfpack Electron Main 进程入口.
 *
 * 职责:
 *  1. (prod) 从 8081 起递增找一个空闲端口, spawn backend binary 注入
 *     WOLFPACK_DATA_DIR + WOLFPACK_PORT, 轮询 /healthz 探活
 *  2. 等 Electron 启动完毕, 开一个 BrowserWindow, 通过 preload + additionalArguments
 *     把后端 apiBase 喂给 Renderer (window.__WOLFPACK__.apiBase)
 *  3. dev 模式加载 http://localhost:5173 (frontend Vite dev server, 后端用户自己起 8080)
 *     prod 模式加载 frontend build 出的静态 HTML, apiBase 走动态端口
 *  4. before-quit 钩子 SIGTERM kill backend, 留 2s graceful, 否则 SIGKILL
 *
 * 端口策略:
 *  - dev: 后端固定 8080 (用户手工跑 uvicorn), Renderer 走 Vite proxy /api
 *  - prod: 后端动态端口 8081+ (避免跟 dev 撞), Renderer 走 preload 注入的 apiBase
 */

import { app, BrowserWindow } from 'electron';
import { ChildProcess, spawn } from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

// dev / prod 分支: app.isPackaged 是 Electron 注入的 boolean
// - 你跑 `pnpm start` 时 = false  (在源码目录里跑)
// - 用户双击 .app 时       = true  (在打包好的 asar 里跑)
// WOLFPACK_FORCE_PROD=1 是临时手动开关, 不打包就能跳到 prod 路径验证 loadFile + spawn
const isDev = !app.isPackaged && process.env.WOLFPACK_FORCE_PROD !== '1';

// dev 模式假设你手工开了 frontend/ 的 pnpm dev, 监听 5173
const DEV_RENDERER_URL = 'http://localhost:5173';
// dev 后端固定 8080. prod 不用这个值
const DEV_BACKEND_PORT = 8080;
// prod 后端从 8081 起递增找空闲, 避开 dev 8080
const PROD_BACKEND_PORT_START = 8081;

app.setName('Wolfpack');
if (isDev && process.platform === 'darwin') {
  const iconPath = path.join(__dirname, '../../assets/icon.png');
  app.dock?.setIcon(iconPath);
}

let mainWindow: BrowserWindow | null = null;
let backendProc: ChildProcess | null = null;
let backendPort: number | null = null;   // prod 实际拿到的端口, dev 模式留 null

/**
 * 决定 binary 路径.
 * - 打包后 (.app): electron-builder extraResources 把 binary 放到 process.resourcesPath
 * - WOLFPACK_FORCE_PROD=1 测试: 找 backend/build-dist/wolfpack-server
 */
function resolveBinaryPath(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'wolfpack-server');
  }
  return path.join(__dirname, '../../../backend/build-dist/wolfpack-server');
}

/** 单端口 bind 探活: 能 listen 就立刻 close 返回 true, 否则 false. */
function isPortFree(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

/** 从 start 起递增找一个空闲端口. 最多扫 100 个端口, 都失败抛错. */
async function findFreePort(start: number, range = 100): Promise<number> {
  for (let port = start; port < start + range; port++) {
    if (await isPortFree(port)) return port;
  }
  throw new Error(`no free port in [${start}, ${start + range})`);
}

function spawnBackend(port: number): void {
  const binPath = resolveBinaryPath();
  const dataDir = app.getPath('userData');
  console.log(`[main] spawning backend: ${binPath}`);
  console.log(`[main] data dir: ${dataDir}`);
  console.log(`[main] backend port: ${port}`);

  backendProc = spawn(binPath, [], {
    env: {
      ...process.env,
      WOLFPACK_DATA_DIR: dataDir,
      WOLFPACK_PORT: String(port),
    },
    stdio: ['ignore', 'inherit', 'inherit'],
  });

  backendProc.on('exit', (code, signal) => {
    console.log(`[main] backend exited code=${code} signal=${signal}`);
    backendProc = null;
  });
  backendProc.on('error', (err) => {
    console.error('[main] backend spawn error:', err);
  });
}

/** 轮询 /healthz 直到 200 或超时. onefile binary 冷启动慢 (解压 + uvicorn lazy import), 留 60s. */
async function waitForHealth(port: number, timeoutMs = 60_000): Promise<void> {
  const healthUrl = `http://127.0.0.1:${port}/healthz`;
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      await new Promise<void>((resolve, reject) => {
        const req = http.get(healthUrl, (res) => {
          if (res.statusCode === 200) resolve();
          else reject(new Error(`status ${res.statusCode}`));
          res.resume();
        });
        req.on('error', reject);
        req.setTimeout(1000, () => req.destroy(new Error('timeout')));
      });
      console.log(`[main] backend ready @ ${port}`);
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 300));
    }
  }
  throw new Error('backend healthz timeout');
}

/** SIGTERM kill, 留 2s graceful, 否则 SIGKILL. */
function stopBackend(): Promise<void> {
  return new Promise((resolve) => {
    if (!backendProc || backendProc.exitCode !== null) {
      resolve();
      return;
    }
    const proc = backendProc;
    const killTimer = setTimeout(() => {
      if (proc.exitCode === null) {
        console.warn('[main] backend did not exit in 2s, SIGKILL');
        proc.kill('SIGKILL');
      }
    }, 2000);
    proc.once('exit', () => {
      clearTimeout(killTimer);
      resolve();
    });
    proc.kill('SIGTERM');
  });
}

function createWindow(): void {
  // dev: apiBase 留空, 让前端用 /api 走 Vite proxy
  // prod: apiBase = http://127.0.0.1:<动态端口>, 通过 preload 注入
  const apiBase = backendPort !== null ? `http://127.0.0.1:${backendPort}` : '';
  const preloadPath = path.join(__dirname, '../preload/preload.js');

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: preloadPath,
      additionalArguments: [`--wolfpack-api-base=${apiBase}`],
      devTools: isDev,
    },
  });

  if (isDev) {
    mainWindow.loadURL(DEV_RENDERER_URL);
    mainWindow.webContents.openDevTools();
  } else {
    const indexHtml = path.join(__dirname, '../../frontend-dist/index.html');
    mainWindow.loadFile(indexHtml);
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  if (!isDev) {
    try {
      backendPort = await findFreePort(PROD_BACKEND_PORT_START);
    } catch (err) {
      console.error('[main] findFreePort failed:', err);
      backendPort = DEV_BACKEND_PORT;   // 兜底, healthz 会失败但至少能开窗看 UI
    }
    spawnBackend(backendPort);
    try {
      await waitForHealth(backendPort);
    } catch (err) {
      console.error('[main] backend boot failed:', err);
      // 这里没启起来 backend 也开窗口 — 至少能看到 UI (虽然 API 全报错)
      // TODO: 弹窗显示 "后端启动失败, 请重试"
    }
  }
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  app.quit();
});

// 退出前 kill backend
app.on('before-quit', async (e) => {
  if (backendProc && backendProc.exitCode === null) {
    e.preventDefault();
    await stopBackend();
    app.exit(0);
  }
});
