import { createBrowserRouter } from "react-router";

import HomePage from "@/pages/Home";
import LobbyPage from "@/pages/Lobby";
import GamePage from "@/pages/Game";

export const router = createBrowserRouter([
  { path: "/", element: <HomePage /> },
  { path: "/lobby", element: <LobbyPage /> },
  { path: "/games/:id", element: <GamePage /> },
]);
