import { createHashRouter } from "react-router";

import HomePage from "@/pages/Home";
import LobbyPage from "@/pages/Lobby";
import GamePage from "@/pages/Game";
import SettingsPage from "@/pages/Settings";

// HashRouter: URL 走 #/ 前缀, 跟 file:// 协议兼容.
// Electron prod 模式加载 frontend-dist/index.html, pathname 是文件路径不是 "/",
// BrowserRouter 会 404. HashRouter 把路由放在 fragment, 永远从 # 开始匹配.
// dev 模式 (Vite) 也照常工作, URL 变成 http://localhost:5173/#/games/15 而已.
export const router = createHashRouter([
  { path: "/", element: <HomePage /> },
  { path: "/lobby", element: <LobbyPage /> },
  { path: "/games/:id", element: <GamePage /> },
  { path: "/settings", element: <SettingsPage /> },
]);
