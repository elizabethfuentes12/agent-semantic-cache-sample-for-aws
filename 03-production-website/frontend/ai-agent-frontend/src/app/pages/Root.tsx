import { Outlet } from "react-router";
import { AuthProvider } from "../context/AuthContext";
import { ThemeProvider } from "../contexts/ThemeContext";
import { Toaster } from "../components/ui/sonner";

export function Root() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <div className="min-h-screen bg-background">
          <Outlet />
          <Toaster />
        </div>
      </AuthProvider>
    </ThemeProvider>
  );
}
