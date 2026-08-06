import type { AppSyncEvent } from '@/app/types/appSyncEvents';

const VALID_TYPES = ['tool_call', 'tool_result', 'message', 'complete'] as const;

/**
 * Validates an incoming event against the AppSync event schema.
 * Returns the typed event if valid, or null if the event is malformed.
 */
export function validateEvent(data: unknown): AppSyncEvent | null {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return null;
  }

  const obj = data as Record<string, unknown>;

  if (!VALID_TYPES.includes(obj.type as (typeof VALID_TYPES)[number])) {
    return null;
  }

  switch (obj.type) {
    case 'tool_call':
      if (
        typeof obj.tool !== 'string' ||
        typeof obj.input !== 'object' ||
        obj.input === null ||
        Array.isArray(obj.input)
      ) {
        return null;
      }
      return obj as unknown as AppSyncEvent;

    case 'tool_result':
      if (typeof obj.tool !== 'string' || typeof obj.result !== 'string') {
        return null;
      }
      return obj as unknown as AppSyncEvent;

    case 'message':
      if (typeof obj.content !== 'string' || obj.content.length === 0) {
        return null;
      }
      return obj as unknown as AppSyncEvent;

    case 'complete':
      if (typeof obj.answer !== 'string' || obj.answer.length === 0) {
        return null;
      }
      return obj as unknown as AppSyncEvent;

    default:
      return null;
  }
}
