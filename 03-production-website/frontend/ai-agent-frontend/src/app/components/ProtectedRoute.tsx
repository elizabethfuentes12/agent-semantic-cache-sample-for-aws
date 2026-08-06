import { Navigate, Outlet } from 'react-router';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/app/context/AuthContext';
import { AgentProvider } from '@/app/context/AgentContext';
import { ModelProvider } from '@/app/context/ModelContext';

export function ProtectedRoute() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return (
    <AgentProvider>
      <ModelProvider>
        <Outlet />
      </ModelProvider>
    </AgentProvider>
  );
}
