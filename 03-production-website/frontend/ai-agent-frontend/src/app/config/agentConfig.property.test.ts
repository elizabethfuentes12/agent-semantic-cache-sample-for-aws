import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';
import { getAgents, _resetCache } from './agentConfig';

/** Arbitrary for a non-empty, non-whitespace-only string. */
const nonEmptyStrArb = fc
  .string({ minLength: 1 })
  .filter((s) => s.trim().length > 0 && !s.includes('"') && !s.includes('\\'));

/** Arbitrary for a single valid AgentDefinition. */
const agentDefArb = fc.record({
  path: nonEmptyStrArb,
  name: nonEmptyStrArb,
  agentId: nonEmptyStrArb,
  description: nonEmptyStrArb,
  target_arn: fc.option(nonEmptyStrArb, { nil: undefined }),
  agent_arn: fc.option(nonEmptyStrArb, { nil: undefined }),
});

/** Arbitrary for a non-empty array of valid AgentDefinitions. */
const agentArrayArb = fc.array(agentDefArb, { minLength: 1, maxLength: 5 });

/**
 * Property 6: Agent config parsing round-trip
 *
 * **Validates: Requirements 7.1, 7.4**
 *
 * For any valid array of AgentDefinition objects (each with non-empty path,
 * name, agentId, description, and optional target_arn/agent_arn), serializing to JSON
 * as { agents: [...] } and parsing with getAgents() SHALL produce an
 * equivalent array.
 */
describe('Property 6: Agent config parsing round-trip', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('getAgents() returns equivalent array after JSON round-trip', () => {
    fc.assert(
      fc.property(agentArrayArb, (agents) => {
        const json = JSON.stringify({ agents });
        vi.stubEnv('VITE_AGENT_LIST', json);
        _resetCache();

        const result = getAgents();

        expect(result).toHaveLength(agents.length);
        for (let i = 0; i < agents.length; i++) {
          expect(result[i].path).toBe(agents[i].path);
          expect(result[i].name).toBe(agents[i].name);
          expect(result[i].agentId).toBe(agents[i].agentId);
          expect(result[i].description).toBe(agents[i].description);
          if (agents[i].target_arn !== undefined) {
            expect(result[i].target_arn).toBe(agents[i].target_arn);
          } else {
            expect(result[i].target_arn).toBeUndefined();
          }
          if (agents[i].agent_arn !== undefined) {
            expect(result[i].agent_arn).toBe(agents[i].agent_arn);
          } else {
            expect(result[i].agent_arn).toBeUndefined();
          }
        }
      }),
      { numRuns: 100 },
    );
  });
});


/**
 * Property 7: Agent config rejects invalid input
 *
 * **Validates: Requirements 7.2, 7.3, 7.4**
 *
 * For any string that is not valid JSON, or valid JSON missing the agents
 * array, or containing agent entries with randomly omitted required fields,
 * getAgents() SHALL throw an Error with a descriptive message.
 */
describe('Property 7: Agent config rejects invalid input', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('throws when VITE_AGENT_LIST is missing or empty', () => {
    const emptyValueArb = fc.oneof(
      fc.constant(''),
      fc.constant('   '),
      fc.constant(undefined as unknown as string),
    );

    fc.assert(
      fc.property(emptyValueArb, (value) => {
        if (value !== undefined) {
          vi.stubEnv('VITE_AGENT_LIST', value);
        } else {
          vi.stubEnv('VITE_AGENT_LIST', '');
        }
        _resetCache();

        expect(() => getAgents()).toThrow('VITE_AGENT_LIST environment variable is not set');
      }),
      { numRuns: 20 },
    );
  });

  it('throws when VITE_AGENT_LIST is not valid JSON', () => {
    const invalidJsonArb = fc
      .string({ minLength: 1 })
      .filter((s) => {
        // Must not be whitespace-only (that triggers the "not set" error instead)
        if (s.trim().length === 0) return false;
        try {
          JSON.parse(s);
          return false;
        } catch {
          return true;
        }
      });

    fc.assert(
      fc.property(invalidJsonArb, (value) => {
        vi.stubEnv('VITE_AGENT_LIST', value);
        _resetCache();

        expect(() => getAgents()).toThrow('VITE_AGENT_LIST is not valid JSON');
      }),
      { numRuns: 100 },
    );
  });

  it('throws when agents array is missing or empty', () => {
    const noAgentsArb = fc.oneof(
      fc.constant(JSON.stringify({})),
      fc.constant(JSON.stringify({ agents: [] })),
      fc.constant(JSON.stringify({ agents: 'not-an-array' })),
      fc.constant(JSON.stringify({ other: [1, 2] })),
    );

    fc.assert(
      fc.property(noAgentsArb, (value) => {
        vi.stubEnv('VITE_AGENT_LIST', value);
        _resetCache();

        expect(() => getAgents()).toThrow("non-empty 'agents' array");
      }),
      { numRuns: 20 },
    );
  });

  it('throws when agent entries are missing required fields', () => {
    const requiredFields = ['path', 'name', 'agentId', 'description'] as const;

    const agentMissingFieldArb = fc
      .record({
        path: nonEmptyStrArb,
        name: nonEmptyStrArb,
        agentId: nonEmptyStrArb,
        description: nonEmptyStrArb,
      })
      .chain((agent) =>
        fc.subarray([...requiredFields], { minLength: 1 }).map((fieldsToRemove) => {
          const broken = { ...agent };
          for (const field of fieldsToRemove) {
            delete (broken as Record<string, unknown>)[field];
          }
          return { broken, removedFields: fieldsToRemove };
        }),
      );

    fc.assert(
      fc.property(agentMissingFieldArb, ({ broken, removedFields }) => {
        const json = JSON.stringify({ agents: [broken] });
        vi.stubEnv('VITE_AGENT_LIST', json);
        _resetCache();

        let thrownError: Error | undefined;
        try {
          getAgents();
        } catch (e) {
          thrownError = e as Error;
        }

        expect(thrownError).toBeDefined();
        // The error should mention at least one of the removed fields
        const mentionsAny = removedFields.some((f) =>
          thrownError!.message.includes(f),
        );
        expect(mentionsAny).toBe(true);
      }),
      { numRuns: 100 },
    );
  });
});
