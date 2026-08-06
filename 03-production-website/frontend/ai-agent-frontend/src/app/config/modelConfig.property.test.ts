import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';
import { getModels, getDefaultModelId, _resetCache } from './modelConfig';

/** Arbitrary for a non-empty, non-whitespace-only string (safe for JSON). */
const nonEmptyStrArb = fc
  .string({ minLength: 1 })
  .filter((s) => s.trim().length > 0 && !s.includes('"') && !s.includes('\\'));

/** Arbitrary for a single valid ModelDefinition. */
const modelDefArb = fc.record({
  name: nonEmptyStrArb,
  id: nonEmptyStrArb,
  selected: fc.boolean(),
});

/** Arbitrary for a non-empty array of valid ModelDefinitions. */
const modelArrayArb = fc.array(modelDefArb, { minLength: 1, maxLength: 5 });

/**
 * Property 1: Config Parsing Round-Trip
 *
 * **Validates: Requirement 1.1**
 *
 * For any valid `VITE_MODEL_LIST` JSON string containing a non-empty `models`
 * array with valid entries, calling `getModels()` SHALL return an array of
 * `ModelDefinition` objects whose `name`, `id`, and `selected` fields match
 * the input data exactly.
 */
describe('Property 1: Config Parsing Round-Trip', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('getModels() returns equivalent array after JSON round-trip', () => {
    fc.assert(
      fc.property(modelArrayArb, (models) => {
        const json = JSON.stringify({ models });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        const result = getModels();

        expect(result).toHaveLength(models.length);
        for (let i = 0; i < models.length; i++) {
          expect(result[i].name).toBe(models[i].name);
          expect(result[i].id).toBe(models[i].id);
          expect(result[i].selected).toBe(models[i].selected);
        }
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * Property 2: Invalid JSON Rejection
 *
 * **Validates: Requirement 1.3**
 *
 * For any string that is not valid JSON, setting it as `VITE_MODEL_LIST`
 * and calling `getModels()` SHALL throw an Error with the message
 * "VITE_MODEL_LIST is not valid JSON".
 */
describe('Property 2: Invalid JSON Rejection', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('getModels() throws for any non-JSON string', () => {
    const invalidJsonArb = fc
      .string({ minLength: 1 })
      .filter((s) => {
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
        vi.stubEnv('VITE_MODEL_LIST', value);
        _resetCache();

        expect(() => getModels()).toThrow(
          'VITE_MODEL_LIST is not valid JSON',
        );
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * Property 3: Validation Completeness
 *
 * **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
 *
 * For any model entry where `name` is not a non-empty string, or `id` is not
 * a non-empty string, or `selected` is not a boolean, calling `getModels()`
 * SHALL throw an Error identifying the invalid field.
 */
describe('Property 3: Validation Completeness', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('throws when name is not a non-empty string', () => {
    /** Arbitrary for invalid `name` values: non-strings or empty/whitespace strings. */
    const invalidNameArb = fc.oneof(
      fc.constant(undefined),
      fc.constant(null),
      fc.constant(123),
      fc.constant(true),
      fc.constant(''),
      fc.constant('   '),
      fc.array(fc.anything(), { maxLength: 2 }),
      fc.object(),
    );

    fc.assert(
      fc.property(invalidNameArb, nonEmptyStrArb, fc.boolean(), (badName, id, selected) => {
        const entry = { name: badName, id, selected };
        const json = JSON.stringify({ models: [entry] });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        expect(() => getModels()).toThrow('name');
      }),
      { numRuns: 50 },
    );
  });

  it('throws when id is not a non-empty string', () => {
    /** Arbitrary for invalid `id` values: non-strings or empty/whitespace strings. */
    const invalidIdArb = fc.oneof(
      fc.constant(undefined),
      fc.constant(null),
      fc.constant(42),
      fc.constant(false),
      fc.constant(''),
      fc.constant('   '),
      fc.array(fc.anything(), { maxLength: 2 }),
      fc.object(),
    );

    fc.assert(
      fc.property(nonEmptyStrArb, invalidIdArb, fc.boolean(), (name, badId, selected) => {
        const entry = { name, id: badId, selected };
        const json = JSON.stringify({ models: [entry] });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        expect(() => getModels()).toThrow('id');
      }),
      { numRuns: 50 },
    );
  });

  it('throws when selected is not a boolean', () => {
    /** Arbitrary for invalid `selected` values: anything that is not a boolean. */
    const invalidSelectedArb = fc.oneof(
      fc.constant(undefined),
      fc.constant(null),
      fc.constant(0),
      fc.constant(1),
      fc.constant('true'),
      fc.constant('false'),
      fc.constant(''),
      fc.object(),
    );

    fc.assert(
      fc.property(nonEmptyStrArb, nonEmptyStrArb, invalidSelectedArb, (name, id, badSelected) => {
        const entry = { name, id, selected: badSelected };
        const json = JSON.stringify({ models: [entry] });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        expect(() => getModels()).toThrow('selected');
      }),
      { numRuns: 50 },
    );
  });

  it('throws when a required field is missing entirely', () => {
    const requiredFields = ['name', 'id', 'selected'] as const;

    const modelMissingFieldArb = fc
      .record({
        name: nonEmptyStrArb,
        id: nonEmptyStrArb,
        selected: fc.boolean(),
      })
      .chain((model) =>
        fc.subarray([...requiredFields], { minLength: 1 }).map((fieldsToRemove) => {
          const broken = { ...model };
          for (const field of fieldsToRemove) {
            delete (broken as Record<string, unknown>)[field];
          }
          return { broken, removedFields: fieldsToRemove };
        }),
      );

    fc.assert(
      fc.property(modelMissingFieldArb, ({ broken, removedFields }) => {
        const json = JSON.stringify({ models: [broken] });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        let thrownError: Error | undefined;
        try {
          getModels();
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

  it('throws when wrong types are used in a model entry among valid ones', () => {
    /** A valid model followed by an invalid one should still throw. */
    const validModelArb = fc.record({
      name: nonEmptyStrArb,
      id: nonEmptyStrArb,
      selected: fc.boolean(),
    });

    const invalidModelArb = fc.oneof(
      fc.record({ name: fc.constant(123), id: nonEmptyStrArb, selected: fc.boolean() }),
      fc.record({ name: nonEmptyStrArb, id: fc.constant(null), selected: fc.boolean() }),
      fc.record({ name: nonEmptyStrArb, id: nonEmptyStrArb, selected: fc.constant('yes') }),
    );

    fc.assert(
      fc.property(validModelArb, invalidModelArb, (valid, invalid) => {
        const json = JSON.stringify({ models: [valid, invalid] });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        expect(() => getModels()).toThrow(Error);
      }),
      { numRuns: 50 },
    );
  });
});

/**
 * Property 4: Config Caching Idempotency
 *
 * **Validates: Requirement 3.1**
 *
 * For any valid `VITE_MODEL_LIST` value, calling `getModels()` twice SHALL
 * return the same cached array reference (`===`).
 */
describe('Property 4: Config Caching Idempotency', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('getModels() returns the same reference on consecutive calls', () => {
    fc.assert(
      fc.property(modelArrayArb, (models) => {
        const json = JSON.stringify({ models });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        const first = getModels();
        const second = getModels();

        expect(first).toBe(second);
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * Property 5: Default Model Determinism
 *
 * **Validates: Requirements 4.1, 4.2**
 *
 * For any valid model list, `getDefaultModelId()` SHALL return the `id` of the
 * first model with `selected: true` if one exists, or the `id` of the first
 * model in the array otherwise.
 */
describe('Property 5: Default Model Determinism', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    _resetCache();
  });

  it('returns the id of the first model with selected: true', () => {
    /** Arbitrary: non-empty model array where at least one model has selected: true. */
    const modelsWithSelectedArb = fc
      .array(modelDefArb, { minLength: 1, maxLength: 5 })
      .chain((models) =>
        fc.integer({ min: 0, max: models.length - 1 }).map((idx) => {
          const copy = models.map((m, i) => ({
            ...m,
            selected: i === idx ? true : m.selected,
          }));
          return copy;
        }),
      )
      .filter((models) => models.some((m) => m.selected));

    fc.assert(
      fc.property(modelsWithSelectedArb, (models) => {
        const json = JSON.stringify({ models });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        const result = getDefaultModelId();
        const firstSelected = models.find((m) => m.selected)!;

        expect(result).toBe(firstSelected.id);
      }),
      { numRuns: 100 },
    );
  });

  it('returns the first model id when no model has selected: true', () => {
    /** Arbitrary: non-empty model array where all models have selected: false. */
    const modelsNoneSelectedArb = fc
      .array(
        fc.record({
          name: nonEmptyStrArb,
          id: nonEmptyStrArb,
          selected: fc.constant(false as boolean),
        }),
        { minLength: 1, maxLength: 5 },
      );

    fc.assert(
      fc.property(modelsNoneSelectedArb, (models) => {
        const json = JSON.stringify({ models });
        vi.stubEnv('VITE_MODEL_LIST', json);
        _resetCache();

        const result = getDefaultModelId();

        expect(result).toBe(models[0].id);
      }),
      { numRuns: 100 },
    );
  });
});
