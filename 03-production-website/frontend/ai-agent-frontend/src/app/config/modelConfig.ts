export interface ModelDefinition {
  name: string;
  id: string;
  selected: boolean;
}

const REQUIRED_STRING_FIELDS: (keyof ModelDefinition)[] = ['name', 'id'];

let cached: ModelDefinition[] | null = null;

export function getModels(): ModelDefinition[] {
  if (cached) {
    return cached;
  }

  const raw = import.meta.env.VITE_MODEL_LIST;

  if (!raw || raw.trim() === '') {
    throw new Error('VITE_MODEL_LIST environment variable is not set');
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('VITE_MODEL_LIST is not valid JSON');
  }

  const obj = parsed as Record<string, unknown>;

  if (!Array.isArray(obj.models) || obj.models.length === 0) {
    throw new Error(
      "VITE_MODEL_LIST must contain a non-empty 'models' array"
    );
  }

  for (const model of obj.models) {
    for (const field of REQUIRED_STRING_FIELDS) {
      if (
        typeof model[field] !== 'string' ||
        (model[field] as string).trim() === ''
      ) {
        throw new Error(
          `Each model must have a non-empty '${field}' field`
        );
      }
    }

    if (typeof model.selected !== 'boolean') {
      throw new Error(
        "Each model must have a boolean 'selected' field"
      );
    }
  }

  cached = obj.models as ModelDefinition[];
  return cached;
}

export function getDefaultModelId(): string {
  const models = getModels();
  const selected = models.find((m) => m.selected);
  return selected ? selected.id : models[0].id;
}

/** Reset memoization cache — exposed for testing only. */
export function _resetCache(): void {
  cached = null;
}
