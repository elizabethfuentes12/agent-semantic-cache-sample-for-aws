import { describe, it, expect, vi } from 'vitest';
import * as fc from 'fast-check';
import { render } from '@testing-library/react';
import React from 'react';

/**
 * Property 1: Bug Condition — Inline Code Detection
 *
 * **Validates: Requirements 2.2**
 *
 * For any markdown string containing single-backtick inline code (no language class,
 * no newlines in content), the fixed `code` component override SHALL render it as an
 * inline `<code>` element with monospace styling, not as a `CodeBlock` component.
 */

// Mock lucide-react icons to avoid rendering issues in test environment
vi.mock('lucide-react', () => ({
  Copy: () => <span data-testid="icon-copy" />,
  Check: () => <span data-testid="icon-check" />,
  Wrench: () => <span data-testid="icon-wrench" />,
  CheckCircle2: () => <span data-testid="icon-check-circle" />,
  MessageSquare: () => <span data-testid="icon-message-square" />,
  Sparkles: () => <span data-testid="icon-sparkles" />,
  ChevronRight: () => <span data-testid="icon-chevron-right" />,
  ChevronDown: () => <span data-testid="icon-chevron-down" />,
  Loader2: () => <span data-testid="icon-loader" />,
}));

// Mock react-syntax-highlighter to simplify rendering and detect CodeBlock usage
vi.mock('react-syntax-highlighter', () => ({
  Prism: ({ children }: { children: string }) => (
    <pre data-testid="syntax-highlighter">{children}</pre>
  ),
}));

vi.mock('react-syntax-highlighter/dist/esm/styles/prism', () => ({
  oneDark: {},
}));

// Mock mermaid to avoid dynamic import issues
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(),
  },
}));

import { MessageRenderer } from './MessageRenderer';

/**
 * Helper: renders a markdown message through MessageRenderer and returns the container.
 * Wraps the content in the JSON message format that MessageRenderer expects.
 */
function renderMarkdownMessage(markdownContent: string) {
  const messageJson = JSON.stringify({
    type: 'message',
    content: markdownContent,
  });

  return render(<MessageRenderer content={messageJson} />);
}

/**
 * Arbitrary for single-line code content strings.
 * Generates strings that:
 * - Have at least 1 character
 * - Do not contain newlines (single-line requirement)
 * - Do not contain backticks (would break markdown syntax)
 */
const singleLineCodeArb = fc
  .string({ minLength: 1, maxLength: 50 })
  .map((s) => s.replace(/[\n\r`]/g, 'x').trim())
  .filter((s) => s.length > 0);

describe('Property 1: Bug Condition — Inline Code Detection', () => {
  it('renders single-backtick inline code as <code> elements, not as CodeBlock components', () => {
    fc.assert(
      fc.property(singleLineCodeArb, (codeContent) => {
        const markdown = `Here is some inline code: \`${codeContent}\` in a sentence.`;
        const { container, unmount } = renderMarkdownMessage(markdown);

        // Find all <code> elements in the rendered output
        const codeElements = container.querySelectorAll('code');

        // There should be at least one <code> element for the inline code
        expect(codeElements.length).toBeGreaterThanOrEqual(1);

        // Find the code element that contains our inline code content
        const inlineCodeEl = Array.from(codeElements).find((el) =>
          el.textContent?.includes(codeContent),
        );
        expect(inlineCodeEl).toBeDefined();

        // The inline code element should have monospace styling classes
        expect(inlineCodeEl!.className).toContain('font-mono');

        // There should be NO syntax-highlighter elements (CodeBlock indicator)
        // for this inline code
        const syntaxHighlighters = container.querySelectorAll(
          '[data-testid="syntax-highlighter"]',
        );
        expect(syntaxHighlighters.length).toBe(0);

        unmount();
      }),
      { numRuns: 50 },
    );
  });

  it('renders diverse inline code patterns as <code> elements', () => {
    // Explicit parametrized test cases covering diverse single-line code patterns
    const testCases = [
      // Simple words
      'hello',
      'world',
      'foo',
      // Filenames with extensions
      'file.csv',
      'index.tsx',
      'config.json',
      'README.md',
      'styles.css',
      'Suporte a Farmacia.csv',
      // Special characters
      'a + b',
      'x => y',
      'key: value',
      'arr[0]',
      '{name}',
      '(a, b)',
      'a & b',
      'a < b',
      // Numbers and numeric strings
      '42',
      '3.14',
      '0xFF',
      '1e10',
      // Paths
      'src/utils/helper.ts',
      './config',
      '../parent/file',
      '/usr/bin/node',
      // Code-like snippets (single line)
      'npm install',
      'git commit -m "fix"',
      'console.log',
      'useState()',
      'Array.isArray(x)',
      // Mixed content
      'v2.0.0-beta.1',
      'user@example.com',
      'http://localhost:3000',
      'SELECT * FROM users',
    ];

    for (const codeContent of testCases) {
      const markdown = `Use \`${codeContent}\` here.`;
      const { container, unmount } = renderMarkdownMessage(markdown);

      const codeElements = container.querySelectorAll('code');
      expect(codeElements.length).toBeGreaterThanOrEqual(1);

      const inlineCodeEl = Array.from(codeElements).find((el) =>
        el.textContent?.includes(codeContent),
      );
      expect(inlineCodeEl).toBeDefined();

      // Should have inline styling, not be inside a CodeBlock
      expect(inlineCodeEl!.className).toContain('font-mono');

      // No syntax highlighter should be present
      const syntaxHighlighters = container.querySelectorAll(
        '[data-testid="syntax-highlighter"]',
      );
      expect(syntaxHighlighters.length).toBe(0);

      unmount();
    }
  });

  it('renders inline code with only whitespace-adjacent content correctly', () => {
    fc.assert(
      fc.property(singleLineCodeArb, (codeContent) => {
        // Test inline code at different positions in the markdown
        const markdownVariants = [
          `\`${codeContent}\``,                          // standalone
          `Start \`${codeContent}\``,                    // at end
          `\`${codeContent}\` end`,                      // at start
          `Before \`${codeContent}\` after`,             // in middle
          `**Bold** and \`${codeContent}\` together`,    // with other formatting
        ];

        for (const markdown of markdownVariants) {
          const { container, unmount } = renderMarkdownMessage(markdown);

          const codeElements = container.querySelectorAll('code');
          expect(codeElements.length).toBeGreaterThanOrEqual(1);

          const inlineCodeEl = Array.from(codeElements).find((el) =>
            el.textContent?.includes(codeContent),
          );
          expect(inlineCodeEl).toBeDefined();

          // Must NOT render as a CodeBlock (no syntax highlighter)
          const syntaxHighlighters = container.querySelectorAll(
            '[data-testid="syntax-highlighter"]',
          );
          expect(syntaxHighlighters.length).toBe(0);

          unmount();
        }
      }),
      { numRuns: 30 },
    );
  });
});

/**
 * Property 2: Preservation — Fenced Code Blocks
 *
 * **Validates: Requirements 3.2**
 *
 * For any markdown string containing triple-backtick fenced code blocks (with or without
 * a language identifier), the fixed `code` component override SHALL continue to render
 * them as full `CodeBlock` components with syntax highlighting, preserving the existing
 * block code rendering behavior.
 */

/**
 * Arbitrary for programming language identifiers used in fenced code blocks.
 */
const languageArb = fc.constantFrom(
  'javascript',
  'typescript',
  'python',
  'java',
  'rust',
  'go',
  'c',
  'cpp',
  'ruby',
  'php',
  'swift',
  'kotlin',
  'scala',
  'haskell',
  'sql',
  'html',
  'css',
  'json',
  'yaml',
  'bash',
  'shell',
  'text',
);

/**
 * Arbitrary for multi-line code content inside fenced code blocks.
 * Generates strings that:
 * - Have at least 1 character
 * - Do not contain triple backticks (would break fenced block syntax)
 * - May contain newlines (multi-line code)
 */
const codeBodyArb = fc
  .array(
    fc
      .string({ minLength: 1, maxLength: 40 })
      .map((s) => s.replace(/`{3,}/g, 'xxx')),
    { minLength: 1, maxLength: 5 },
  )
  .map((lines) => lines.join('\n'));

describe('Property 2: Preservation — Fenced Code Blocks', () => {
  it('renders fenced code blocks with language identifiers as CodeBlock components', () => {
    fc.assert(
      fc.property(languageArb, codeBodyArb, (language, codeBody) => {
        const markdown = `Here is a code block:\n\n\`\`\`${language}\n${codeBody}\n\`\`\`\n\nEnd of block.`;
        const { container, unmount } = renderMarkdownMessage(markdown);

        // Fenced code blocks should render through CodeBlock, which uses SyntaxHighlighter
        // Our mock renders SyntaxHighlighter as <pre data-testid="syntax-highlighter">
        const syntaxHighlighters = container.querySelectorAll(
          '[data-testid="syntax-highlighter"]',
        );
        expect(syntaxHighlighters.length).toBeGreaterThanOrEqual(1);

        // The code content should appear somewhere in the syntax highlighter output
        const highlighterTexts = Array.from(syntaxHighlighters).map(
          (el) => el.textContent || '',
        );
        const hasCodeContent = highlighterTexts.some((text) =>
          codeBody
            .split('\n')
            .some((line) => text.includes(line.trim())),
        );
        expect(hasCodeContent).toBe(true);

        unmount();
      }),
      { numRuns: 50 },
    );
  });

  it('renders fenced code blocks WITHOUT language identifiers as CodeBlock components', () => {
    fc.assert(
      fc.property(codeBodyArb, (codeBody) => {
        const markdown = `Some text before.\n\n\`\`\`\n${codeBody}\n\`\`\`\n\nSome text after.`;
        const { container, unmount } = renderMarkdownMessage(markdown);

        // Even without a language identifier, fenced code blocks should render as CodeBlock
        const syntaxHighlighters = container.querySelectorAll(
          '[data-testid="syntax-highlighter"]',
        );
        expect(syntaxHighlighters.length).toBeGreaterThanOrEqual(1);

        unmount();
      }),
      { numRuns: 30 },
    );
  });

  it('renders diverse fenced code block patterns as CodeBlock components', () => {
    // Explicit parametrized test cases covering diverse fenced code block patterns
    const testCases: Array<{ language: string; code: string; description: string }> = [
      {
        language: 'javascript',
        code: 'const x = 42;\nconsole.log(x);',
        description: 'JavaScript with multiple statements',
      },
      {
        language: 'python',
        code: 'def hello():\n    print("world")',
        description: 'Python with indentation',
      },
      {
        language: 'typescript',
        code: 'interface User {\n  name: string;\n  age: number;\n}',
        description: 'TypeScript interface',
      },
      {
        language: 'rust',
        code: 'fn main() {\n    println!("Hello");\n}',
        description: 'Rust function',
      },
      {
        language: 'sql',
        code: 'SELECT * FROM users\nWHERE active = true\nORDER BY name;',
        description: 'SQL multi-line query',
      },
      {
        language: 'json',
        code: '{\n  "key": "value",\n  "count": 42\n}',
        description: 'JSON object',
      },
      {
        language: 'bash',
        code: '#!/bin/bash\necho "Hello"\nexit 0',
        description: 'Bash script with shebang',
      },
      {
        language: '',
        code: 'plain text\nwith multiple lines',
        description: 'No language identifier',
      },
      {
        language: 'html',
        code: '<div class="container">\n  <p>Hello</p>\n</div>',
        description: 'HTML with nested tags',
      },
      {
        language: 'css',
        code: '.container {\n  display: flex;\n  gap: 1rem;\n}',
        description: 'CSS with properties',
      },
      {
        language: 'go',
        code: 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello")\n}',
        description: 'Go with imports',
      },
      {
        language: 'yaml',
        code: 'name: test\nversion: 1.0\ndependencies:\n  - react\n  - vitest',
        description: 'YAML config',
      },
    ];

    for (const { language, code, description } of testCases) {
      const markdown = language
        ? `\`\`\`${language}\n${code}\n\`\`\``
        : `\`\`\`\n${code}\n\`\`\``;
      const { container, unmount } = renderMarkdownMessage(markdown);

      // All fenced code blocks must render as CodeBlock (with syntax highlighter)
      const syntaxHighlighters = container.querySelectorAll(
        '[data-testid="syntax-highlighter"]',
      );
      expect(
        syntaxHighlighters.length,
        `Expected CodeBlock for: ${description}`,
      ).toBeGreaterThanOrEqual(1);

      // Should NOT render as inline <code> with font-mono class
      const inlineCodeElements = container.querySelectorAll('code.font-mono');
      expect(
        inlineCodeElements.length,
        `Expected no inline code for: ${description}`,
      ).toBe(0);

      unmount();
    }
  });

  it('renders fenced code blocks as CodeBlock even when mixed with inline code', () => {
    fc.assert(
      fc.property(
        languageArb,
        codeBodyArb,
        singleLineCodeArb,
        (language, codeBody, inlineContent) => {
          // Markdown with both a fenced code block AND inline code
          const markdown = `Use \`${inlineContent}\` and see:\n\n\`\`\`${language}\n${codeBody}\n\`\`\`\n\nDone.`;
          const { container, unmount } = renderMarkdownMessage(markdown);

          // The fenced code block should render as CodeBlock (syntax highlighter present)
          const syntaxHighlighters = container.querySelectorAll(
            '[data-testid="syntax-highlighter"]',
          );
          expect(syntaxHighlighters.length).toBeGreaterThanOrEqual(1);

          // The inline code should render as a <code> element with font-mono
          const inlineCodeElements = container.querySelectorAll('code.font-mono');
          expect(inlineCodeElements.length).toBeGreaterThanOrEqual(1);

          unmount();
        },
      ),
      { numRuns: 30 },
    );
  });
});
