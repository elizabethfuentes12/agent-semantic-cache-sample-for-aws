import { describe, it, expect } from 'vitest';
import { extractMessageContent } from './messageContentExtractor';

describe('extractMessageContent', () => {
  describe('message type', () => {
    it('extracts markdown content from a message-type JSON string', () => {
      const raw = JSON.stringify({
        type: 'message',
        content: '# Welcome\n\nHere is a list:\n- Item 1\n- Item 2\n\n```ts\nconst x = 42;\n```',
      });
      expect(extractMessageContent(raw)).toBe(
        '# Welcome\n\nHere is a list:\n- Item 1\n- Item 2\n\n```ts\nconst x = 42;\n```',
      );
    });

    it('returns empty string when content field is empty', () => {
      const raw = JSON.stringify({ type: 'message', content: '' });
      expect(extractMessageContent(raw)).toBe('');
    });
  });

  describe('complete type', () => {
    it('extracts a multi-paragraph answer from a complete-type JSON string', () => {
      const answer =
        'The deployment succeeded.\n\nAll 12 tests passed. The application is now running on port 3000.\n\nLet me know if you need anything else.';
      const raw = JSON.stringify({ type: 'complete', answer });
      expect(extractMessageContent(raw)).toBe(answer);
    });

    it('returns empty string when answer field is empty', () => {
      const raw = JSON.stringify({ type: 'complete', answer: '' });
      expect(extractMessageContent(raw)).toBe('');
    });
  });

  describe('tool_call type', () => {
    it('returns formatted tool name and input for a tool_call-type JSON string', () => {
      const raw = JSON.stringify({
        type: 'tool_call',
        tool: 'readFile',
        input: { path: 'src/index.ts', encoding: 'utf-8' },
      });
      const expected = `Tool: readFile\nInput:\n${JSON.stringify({ path: 'src/index.ts', encoding: 'utf-8' }, null, 2)}`;
      expect(extractMessageContent(raw)).toBe(expected);
    });

    it('uses "Unknown tool" fallback when tool field is missing', () => {
      const raw = JSON.stringify({
        type: 'tool_call',
        input: { query: 'SELECT * FROM users' },
      });
      const result = extractMessageContent(raw);
      expect(result).toContain('Tool: Unknown tool');
      expect(result).toContain(JSON.stringify({ query: 'SELECT * FROM users' }, null, 2));
    });
  });

  describe('tool_result type', () => {
    it('returns formatted tool name and result for a tool_result-type JSON string', () => {
      const raw = JSON.stringify({
        type: 'tool_result',
        tool: 'executeCommand',
        result: 'Build completed successfully in 3.2s',
      });
      expect(extractMessageContent(raw)).toBe(
        'Tool: executeCommand\nResult:\nBuild completed successfully in 3.2s',
      );
    });

    it('uses "Unknown tool" fallback when tool field is missing in tool_result', () => {
      const raw = JSON.stringify({
        type: 'tool_result',
        result: 'Operation completed',
      });
      expect(extractMessageContent(raw)).toBe('Tool: Unknown tool\nResult:\nOperation completed');
    });
  });

  describe('fallback behavior', () => {
    it('returns a non-JSON string unchanged', () => {
      const plainText = 'Hello, this is just a regular message without JSON.';
      expect(extractMessageContent(plainText)).toBe(plainText);
    });

    it('returns JSON with an unrecognized type unchanged', () => {
      const raw = JSON.stringify({ type: 'unknown_event', data: 'some payload' });
      expect(extractMessageContent(raw)).toBe(raw);
    });
  });
});
