import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { AgentDefinition } from '@/app/config/agentConfig';
import { getAgents as getAgentsFromEnv, filterVisibleAgents } from '@/app/config/agentConfig';
import { fetchAgentsFromSSM } from '@/app/services/agentService';
import { useAuth } from './AuthContext';

interface AgentContextValue {
  agents: AgentDefinition[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const AgentContext = createContext<AgentContextValue>({
  agents: [],
  loading: true,
  error: null,
  refresh: () => {},
});

export function AgentProvider({ children }: { children: React.ReactNode }) {
  const { getSession, user } = useAuth();
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const userGroups = user?.groups ?? [];
  // Stable key so the load effect only re-runs when group membership actually changes.
  const groupsKey = userGroups.join(',');

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const getIdToken = async () => {
        const session = await getSession();
        return session.getIdToken().getJwtToken();
      };
      const result = await fetchAgentsFromSSM(getIdToken);
      setAgents(filterVisibleAgents(result, userGroups));
    } catch (ssmError) {
      console.warn('Failed to load agents from SSM, falling back to env config:', ssmError);
      try {
        const envAgents = getAgentsFromEnv();
        setAgents(filterVisibleAgents(envAgents, userGroups));
      } catch (envError) {
        setError('Failed to load agents');
        console.error('Failed to load agents from env fallback:', envError);
      }
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getSession, groupsKey]);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  return (
    <AgentContext.Provider value={{ agents, loading, error, refresh: loadAgents }}>
      {children}
    </AgentContext.Provider>
  );
}

export function useAgents() {
  return useContext(AgentContext);
}
