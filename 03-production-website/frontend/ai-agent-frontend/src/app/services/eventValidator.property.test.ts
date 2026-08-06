import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { validateEvent } from './eventValidator';

/** Arbitrary for a non-empty string. */
const nonEmptyStrArb = fc.string({ minLength: 1 }).filter((s) => s.length > 0);

/** Arbitrary for a plain object (Record<string, unknown>). */
const plainObjectArb = fc.dictionary(fc.string(), fc.jsonValue());

/** Arbitrary for a valid ToolCallEvent. */
const toolCallArb = fc.record({
  type: fc.constant('tool_call' as const),
  tool: nonEmptyStrArb,
  input: plainObjectArb,
});

/** Arbitrary for a valid ToolResultEvent. */
const toolResultArb = fc.record({
  type: fc.constant('tool_result' as const),
  tool: nonEmptyStrArb,
  result: fc.string(),
});

/** Arbitrary for a valid MessageEvent. */
const messageArb = fc.record({
  type: fc.constant('message' as const),
  content: nonEmptyStrArb,
});

/** Arbitrary for a valid CompleteEvent. */
const completeArb = fc.record({
  type: fc.constant('complete' as const),
  answer: nonEmptyStrArb,
});

/** Arbitrary for any valid AppSyncEvent. */
const validEventArb = fc.oneof(toolCallArb, toolResultArb, messageArb, completeArb);

/**
 * Property 1: Valid events produce accepted results
 *
 * **Validates: Requirements 2.4, 3.1, 3.2, 3.3, 3.4**
 *
 * For any valid AppSync event, validateEvent returns the event (not null).
 */
describe('Property 1: Valid event acceptance', () => {
  it('validateEvent returns the event for any valid AppSyncEvent', () => {
    fc.assert(
      fc.property(validEventArb, (event) => {
        const result = validateEvent(event);
        expect(result).not.toBeNull();
        expect(result!.type).toBe(event.type);
      }),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 2: Invalid or unknown events are rejected
 *
 * **Validates: Requirements 2.5, 2.6, 3.5**
 *
 * For any frame with no type field or unknown type, validateEvent returns null.
 */
describe('Property 2: Invalid event rejection (missing/unknown type)', () => {
  it('rejects objects with no type field', () => {
    const noTypeArb = fc.dictionary(fc.string(), fc.jsonValue()).filter(
      (obj) => !('type' in obj),
    );

    fc.assert(
      fc.property(noTypeArb, (obj) => {
        expect(validateEvent(obj)).toBeNull();
      }),
      { numRuns: 100 },
    );
  });

  it('rejects objects with unknown type values', () => {
    const knownTypes = ['tool_call', 'tool_result', 'message', 'complete'];
    const unknownTypeArb = fc
      .record({
        type: fc.string().filter((s) => !knownTypes.includes(s)),
      });

    fc.assert(
      fc.property(unknownTypeArb, (obj) => {
        expect(validateEvent(obj)).toBeNull();
      }),
      { numRuns: 100 },
    );
  });

  it('rejects non-object values (null, arrays, primitives)', () => {
    const nonObjectArb = fc.oneof(
      fc.constant(null),
      fc.constant(undefined),
      fc.string(),
      fc.integer(),
      fc.boolean(),
      fc.array(fc.jsonValue()),
    );

    fc.assert(
      fc.property(nonObjectArb, (value) => {
        expect(validateEvent(value)).toBeNull();
      }),
      { numRuns: 50 },
    );
  });
});

/**
 * Property 3: Events with valid type but invalid/missing required fields are rejected
 *
 * **Validates: Requirements 8.2, 8.3, 8.4, 8.5**
 *
 * For any event with a valid type but invalid or missing required fields,
 * validateEvent returns null.
 */
describe('Property 3: Malformed event rejection (valid type, bad fields)', () => {
  it('rejects tool_call with missing or invalid tool/input', () => {
    const badToolCallArb = fc.oneof(
      // missing tool
      fc.record({ type: fc.constant('tool_call'), input: plainObjectArb }),
      // tool is not a string
      fc.record({ type: fc.constant('tool_call'), tool: fc.oneof(fc.integer(), fc.boolean(), fc.constant(null)), input: plainObjectArb }),
      // missing input
      fc.record({ type: fc.constant('tool_call'), tool: nonEmptyStrArb }),
      // input is not an object
      fc.record({ type: fc.constant('tool_call'), tool: nonEmptyStrArb, input: fc.oneof(fc.string(), fc.integer(), fc.constant(null)) }),
      // input is an array
      fc.record({ type: fc.constant('tool_call'), tool: nonEmptyStrArb, input: fc.array(fc.jsonValue()) }),
    );

    fc.assert(
      fc.property(badToolCallArb, (event) => {
        expect(validateEvent(event)).toBeNull();
      }),
      { numRuns: 100 },
    );
  });

  it('rejects tool_result with missing or invalid tool/result', () => {
    const badToolResultArb = fc.oneof(
      // missing tool
      fc.record({ type: fc.constant('tool_result'), result: fc.string() }),
      // tool is not a string
      fc.record({ type: fc.constant('tool_result'), tool: fc.oneof(fc.integer(), fc.boolean(), fc.constant(null)), result: fc.string() }),
      // missing result
      fc.record({ type: fc.constant('tool_result'), tool: nonEmptyStrArb }),
      // result is not a string
      fc.record({ type: fc.constant('tool_result'), tool: nonEmptyStrArb, result: fc.oneof(fc.integer(), fc.boolean(), fc.constant(null)) }),
    );

    fc.assert(
      fc.property(badToolResultArb, (event) => {
        expect(validateEvent(event)).toBeNull();
      }),
      { numRuns: 100 },
    );
  });

  it('rejects message with missing or empty content', () => {
    const badMessageArb = fc.oneof(
      // missing content
      fc.record({ type: fc.constant('message') }),
      // content is not a string
      fc.record({ type: fc.constant('message'), content: fc.oneof(fc.integer(), fc.boolean(), fc.constant(null)) }),
      // content is empty string
      fc.constant({ type: 'message', content: '' }),
    );

    fc.assert(
      fc.property(badMessageArb, (event) => {
        expect(validateEvent(event)).toBeNull();
      }),
      { numRuns: 50 },
    );
  });

  it('rejects complete with missing or empty answer', () => {
    const badCompleteArb = fc.oneof(
      // missing answer
      fc.record({ type: fc.constant('complete') }),
      // answer is not a string
      fc.record({ type: fc.constant('complete'), answer: fc.oneof(fc.integer(), fc.boolean(), fc.constant(null)) }),
      // answer is empty string
      fc.constant({ type: 'complete', answer: '' }),
    );

    fc.assert(
      fc.property(badCompleteArb, (event) => {
        expect(validateEvent(event)).toBeNull();
      }),
      { numRuns: 50 },
    );
  });
});
