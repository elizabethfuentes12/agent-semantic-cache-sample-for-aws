import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ModelDefinition } from '@/app/config/modelConfig';
import { getModels as getModelsFromEnv, getDefaultModelId as getDefaultModelIdFromEnv } from '@/app/config/modelConfig';
import { fetchModelsFromSSM } from '@/app/services/modelService';
import { useAuth } from './AuthContext';

interface ModelContextValue {
  models: ModelDefinition[];
  defaultModelId: string;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const ModelContext = createContext<ModelContextValue>({
  models: [],
  defaultModelId: '',
  loading: true,
  error: null,
  refresh: () => {},
});

function resolveDefaultModelId(models: ModelDefinition[]): string {
  const selected = models.find((m) => m.selected);
  return selected ? selected.id : models[0]?.id || '';
}

export function ModelProvider({ children }: { children: React.ReactNode }) {
  const { getSession } = useAuth();
  const [models, setModels] = useState<ModelDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const getIdToken = async () => {
        const session = await getSession();
        return session.getIdToken().getJwtToken();
      };
      const result = await fetchModelsFromSSM(getIdToken);
      setModels(result);
    } catch (ssmError) {
      console.warn('Failed to load models from SSM, falling back to env config:', ssmError);
      try {
        const envModels = getModelsFromEnv();
        setModels(envModels);
      } catch (envError) {
        setError('Failed to load models');
        console.error('Failed to load models from env fallback:', envError);
      }
    } finally {
      setLoading(false);
    }
  }, [getSession]);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  const defaultModelId = resolveDefaultModelId(models);

  return (
    <ModelContext.Provider value={{ models, defaultModelId, loading, error, refresh: loadModels }}>
      {children}
    </ModelContext.Provider>
  );
}

export function useModels() {
  return useContext(ModelContext);
}
