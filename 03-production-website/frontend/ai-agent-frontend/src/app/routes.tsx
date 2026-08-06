import { createBrowserRouter, Navigate } from "react-router";
import { Root } from "./pages/Root";
import { Login } from "./pages/Login";
import { Chat } from "./pages/Chat";
import { ProtectedRoute } from "@/app/components/ProtectedRoute";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Root,
    children: [
      {
        Component: ProtectedRoute,
        children: [
          { index: true, element: <Navigate to="/chat" replace /> },
          { path: "chat", Component: Chat },
        ],
      },
      { path: "login", Component: Login },
    ],
  },
]);
