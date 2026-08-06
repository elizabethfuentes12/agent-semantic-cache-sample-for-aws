import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { extractMessageContent } from './messageContentExtractor';

/**
 * Property 1: Content field extraction for message and complete types
 *
 * **Validates: Requirements 1.1, 1.2**
 *
 * For any valid `message`-type JSON string with an arbitrary `content` field,
 * and for any valid `complete`-type JSON string with an arbitrary `answer` field,
 * `extractMessageContent` SHALL return the value of the `content` or `answer`
 * field respectively, as a verbatim string.
 */
describe('Property 1: Content field extraction for message and complete types', () => {
  it('extracts the content field verbatim from message-type JSON', () => {
    fc.assert(
      fc.property(fc.string(), (content) => {
        const raw = JSON.stringify({ type: 'message', content });
        const result = extractMessageContent(raw);
        expect(result).toBe(content);
      }),
      { numRuns: 200 },
    );
  });

  it('extracts the answer field verbatim from complete-type JSON', () => {
    fc.assert(
      fc.property(fc.string(), (answer) => {
        const raw = JSON.stringify({ type: 'complete', answer });
        const result = extractMessageContent(raw);
        expect(result).toBe(answer);
      }),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 2: Tool summary contains tool name and data
 *
 * **Validates: Requirements 1.3, 1.4**
 *
 * For any valid `tool_call`-type JSON string with an arbitrary tool name and input object,
 * and for any valid `tool_result`-type JSON string with an arbitrary tool name and result string,
 * `extractMessageContent` SHALL return a string that contains both the tool name and the
 * relevant data (input parameters or result text).
 */
describe('Property 2: Tool summary contains tool name and data', () => {
  it('output contains the tool name and stringified input for tool_call type', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        fc.jsonValue(),
        (toolName, input) => {
          const raw = JSON.stringify({ type: 'tool_call', tool: toolName, input });
          const result = extractMessageContent(raw);
          expect(result).toContain(toolName);
          expect(result).toContain(JSON.stringify(input, null, 2));
        },
      ),
      { numRuns: 200 },
    );
  });

  it('output contains the tool name and result text for tool_result type', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        fc.string(),
        (toolName, resultText) => {
          const raw = JSON.stringify({ type: 'tool_result', tool: toolName, result: resultText });
          const result = extractMessageContent(raw);
          expect(result).toContain(toolName);
          expect(result).toContain(resultText);
        },
      ),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 3: Fallback identity for unrecognized input
 *
 * **Validates: Requirements 1.5, 1.6**
 *
 * For any string that is either not valid JSON or is valid JSON with a `type`
 * field not in `{message, complete, tool_call, tool_result}`,
 * `extractMessageContent` SHALL return the original string unchanged.
 */
describe('Property 3: Fallback identity for unrecognized input', () => {
  it('returns non-JSON strings unchanged', () => {
    const nonJsonString = fc.string().filter((s) => {
      try {
        JSON.parse(s);
        return false;
      } catch {
        return true;
      }
    });

    fc.assert(
      fc.property(nonJsonString, (input) => {
        const result = extractMessageContent(input);
        expect(result).toBe(input);
      }),
      { numRuns: 200 },
    );
  });

  it('returns JSON with unrecognized type field unchanged', () => {
    const knownTypes = ['message', 'complete', 'tool_call', 'tool_result'];
    const unrecognizedType = fc
      .string()
      .filter((t) => !knownTypes.includes(t));

    fc.assert(
      fc.property(
        unrecognizedType,
        fc.dictionary(fc.string(), fc.jsonValue()),
        (type, extraFields) => {
          const obj = { ...extraFields, type };
          const raw = JSON.stringify(obj);
          const result = extractMessageContent(raw);
          expect(result).toBe(raw);
        },
      ),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 4: Round-trip content preservation
 *
 * **Validates: Requirements 1.7**
 *
 * For any valid `message`-type or `complete`-type Internal_Message_Format string,
 * extracting the content and then wrapping it back into the same JSON structure
 * SHALL produce a string from which the same content can be extracted again
 * (i.e., `extract(wrap(extract(raw))) === extract(raw)`).
 */
describe('Property 4: Round-trip content preservation', () => {
  it('round-trips message-type: extract, wrap, extract again yields same result', () => {
    fc.assert(
      fc.property(fc.string(), (content) => {
        const raw = JSON.stringify({ type: 'message', content });
        const firstExtraction = extractMessageContent(raw);
        const rewrapped = JSON.stringify({ type: 'message', content: firstExtraction });
        const secondExtraction = extractMessageContent(rewrapped);
        expect(secondExtraction).toBe(firstExtraction);
      }),
      { numRuns: 200 },
    );
  });

  it('round-trips complete-type: extract, wrap, extract again yields same result', () => {
    fc.assert(
      fc.property(fc.string(), (answer) => {
        const raw = JSON.stringify({ type: 'complete', answer });
        const firstExtraction = extractMessageContent(raw);
        const rewrapped = JSON.stringify({ type: 'complete', answer: firstExtraction });
        const secondExtraction = extractMessageContent(rewrapped);
        expect(secondExtraction).toBe(firstExtraction);
      }),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 5: Copy path consistency for complete messages
 *
 * **Validates: Requirements 3.1, 3.2**
 *
 * For any valid `complete`-type JSON with an `answer` field,
 * `extractMessageContent(rawJson)` SHALL equal the `answer` value directly.
 * This ensures the main copy button (Chat.tsx via extractMessageContent) and
 * the CompleteRenderer copy button (which copies `answer` directly) produce
 * identical output.
 */
describe('Property 5: Copy path consistency for complete messages', () => {
  it('extractMessageContent on complete-type JSON equals the answer value directly', () => {
    fc.assert(
      fc.property(fc.string(), (answer) => {
        const rawJson = JSON.stringify({ type: 'complete', answer });
        const extractedContent = extractMessageContent(rawJson);
        // CompleteRenderer copies `answer` directly, Chat.tsx runs through extractMessageContent
        // Both paths must produce the same output
        expect(extractedContent).toBe(answer);
      }),
      { numRuns: 200 },
    );
  });
});
