import { describe, it, expect } from 'vitest';
import { sanitizeChats } from './Chat';
import type { ChatSession } from '@/app/hooks/useAppSyncChat';

function makeChat(id: unknown, title = 't'): ChatSession {
  return {
    id: id as string,
    title,
    agentId: 'a',
    modelId: 'm',
    messages: [],
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}

describe('sanitizeChats', () => {
  it('drops entries with null/empty id (which cause duplicate-key warnings)', () => {
    const result = sanitizeChats([
      makeChat('a'),
      makeChat(null),
      makeChat(''),
      makeChat(undefined),
    ]);
    expect(result.map(c => c.id)).toEqual(['a']);
  });

  it('collapses duplicate ids to the first occurrence', () => {
    const result = sanitizeChats([
      makeChat('dup', 'first'),
      makeChat('dup', 'second'),
      makeChat('b'),
    ]);
    expect(result).toHaveLength(2);
    expect(result[0].title).toBe('first');
    expect(result.map(c => c.id)).toEqual(['dup', 'b']);
  });

  it('returns unique, non-null ids so React keys never collide', () => {
    const result = sanitizeChats([makeChat('x'), makeChat('y'), makeChat('x')]);
    const ids = result.map(c => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every(Boolean)).toBe(true);
  });
});
