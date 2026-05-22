/// <reference types="vite/client" />

declare global {
  interface Window {
    /** Electron preload (electron/src/preload/preload.ts) 注入. 仅在打包后的桌面 app 里存在. */
    __WOLFPACK__?: {
      /** 后端 base URL, 形如 "http://127.0.0.1:8083". dev 模式下不存在. */
      apiBase: string;
    };
  }
}

export {};
