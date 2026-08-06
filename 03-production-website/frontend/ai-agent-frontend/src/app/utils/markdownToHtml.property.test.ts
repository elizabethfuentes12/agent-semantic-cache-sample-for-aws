import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { convertMarkdownToHtml } from './markdownToHtml';
import { extractMessageContent } from './messageContentExtractor';

/**
 * Arbitrary for safe text content (no markdown syntax characters).
 * Used as content inside markdown elements.
 */
const safeTextArb = fc
  .string({ minLength: 1, maxLength: 30 })
  .map((s) => s.replace(/[#*`\[\]()>|\-\\{}_~<!\n\r]/g, 'a').trim())
  .filter((s) => s.length > 0);

/**
 * Arbitrary for a valid URL path segment.
 */
const urlArb = fc
  .string({ minLength: 1, maxLength: 20 })
  .map((s) => s.replace(/[^a-zA-Z0-9]/g, 'x'))
  .filter((s) => s.length > 0)
  .map((s) => `https://example.com/${s}`);

/**
 * Arbitrary for heading levels 1-6.
 */
const headingLevelArb = fc.integer({ min: 1, max: 6 });

/**
 * Property 1: Markdown-to-HTML produces correct HTML elements
 *
 * **Validates: Requirements 1.1**
 *
 * For any markdown string containing a known element (heading, bold, italic,
 * link, list, code block, inline code, blockquote, or table),
 * convertMarkdownToHtml SHALL produce an HTML string containing the
 * corresponding HTML tag.
 */
describe('Property 1: Markdown-to-HTML produces correct HTML elements', () => {
  it('headings produce corresponding <h1>–<h6> tags', () => {
    fc.assert(
      fc.property(headingLevelArb, safeTextArb, (level, text) => {
        const prefix = '#'.repeat(level) + ' ';
        const markdown = `${prefix}${text}`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain(`<h${level}`);
      }),
      { numRuns: 200 },
    );
  });

  it('bold text produces <strong> tags', () => {
    fc.assert(
      fc.property(safeTextArb, (text) => {
        const markdown = `**${text}**`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<strong>');
      }),
      { numRuns: 200 },
    );
  });

  it('italic text produces <em> tags', () => {
    fc.assert(
      fc.property(safeTextArb, (text) => {
        const markdown = `*${text}*`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<em>');
      }),
      { numRuns: 200 },
    );
  });

  it('links produce <a> tags', () => {
    fc.assert(
      fc.property(safeTextArb, urlArb, (text, url) => {
        const markdown = `[${text}](${url})`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<a');
        expect(html).toContain(url);
      }),
      { numRuns: 200 },
    );
  });

  it('code blocks produce <pre> or <code> tags', () => {
    fc.assert(
      fc.property(safeTextArb, (text) => {
        const markdown = `\`\`\`\n${text}\n\`\`\``;
        const html = convertMarkdownToHtml(markdown);

        const hasPreOrCode = html.includes('<pre>') || html.includes('<pre') || html.includes('<code');
        expect(hasPreOrCode).toBe(true);
      }),
      { numRuns: 200 },
    );
  });

  it('inline code produces <code> tags', () => {
    fc.assert(
      fc.property(safeTextArb, (text) => {
        const markdown = `Use \`${text}\` here`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<code>');
      }),
      { numRuns: 200 },
    );
  });

  it('blockquotes produce <blockquote> tags', () => {
    fc.assert(
      fc.property(safeTextArb, (text) => {
        const markdown = `> ${text}`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<blockquote>');
      }),
      { numRuns: 200 },
    );
  });

  it('unordered lists produce <ul> tags', () => {
    fc.assert(
      fc.property(safeTextArb, safeTextArb, (item1, item2) => {
        const markdown = `- ${item1}\n- ${item2}`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<ul>');
      }),
      { numRuns: 200 },
    );
  });

  it('ordered lists produce <ol> tags', () => {
    fc.assert(
      fc.property(safeTextArb, safeTextArb, (item1, item2) => {
        const markdown = `1. ${item1}\n2. ${item2}`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<ol>');
      }),
      { numRuns: 200 },
    );
  });

  it('tables produce <table> tags', () => {
    fc.assert(
      fc.property(safeTextArb, safeTextArb, (col1, col2) => {
        const markdown = `| ${col1} | ${col2} |\n| --- | --- |\n| val1 | val2 |`;
        const html = convertMarkdownToHtml(markdown);

        expect(html).toContain('<table>');
      }),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 2: Sanitizer removes dangerous HTML constructs
 *
 * **Validates: Requirements 1.2**
 *
 * For any input string (including strings containing `<script>` tags,
 * `onerror` attributes, `javascript:` URLs, and other XSS vectors),
 * the output of `convertMarkdownToHtml` SHALL NOT contain `<script` tags,
 * `on`-prefixed event handler attributes, or `javascript:` URL schemes.
 */
describe('Property 2: Sanitizer removes dangerous HTML constructs', () => {
  /**
   * Arbitrary that generates strings with embedded XSS payloads.
   * Mixes arbitrary text with known dangerous constructs.
   */
  const xssPayloads = [
    `<script>alert('xss')</script>`,
    `<script src="evil.js"></script>`,
    `<img onerror="alert(1)">`,
    `<img src=x onerror="alert(1)">`,
    `<a href="javascript:void(0)">click</a>`,
    `<a href="javascript:alert('xss')">link</a>`,
    `<div onmouseover="alert(1)">hover</div>`,
    `<body onload="alert(1)">`,
    `<svg onload="alert(1)">`,
    `<input onfocus="alert(1)" autofocus>`,
    `<iframe src="javascript:alert(1)">`,
    `<img src="x" onerror="fetch('http://evil.com')">`,
    `<marquee onstart="alert(1)">`,
    `<details ontoggle="alert(1)">`,
  ];

  const xssPayloadArb = fc.constantFrom(...xssPayloads);

  const arbitraryStringWithXss = fc.oneof(
    // Pure XSS payload
    xssPayloadArb,
    // Arbitrary string mixed with XSS payload
    fc.tuple(fc.string({ minLength: 0, maxLength: 50 }), xssPayloadArb, fc.string({ minLength: 0, maxLength: 50 }))
      .map(([before, payload, after]) => `${before}${payload}${after}`),
    // Arbitrary string that might accidentally contain dangerous patterns
    fc.string({ minLength: 1, maxLength: 200 }),
  );

  it('output never contains <script tags', () => {
    fc.assert(
      fc.property(arbitraryStringWithXss, (input) => {
        const html = convertMarkdownToHtml(input);
        expect(html.toLowerCase()).not.toContain('<script');
      }),
      { numRuns: 200 },
    );
  });

  it('output never contains on-prefixed event handler attributes in active HTML', () => {
    fc.assert(
      fc.property(arbitraryStringWithXss, (input) => {
        const html = convertMarkdownToHtml(input);
        // Parse the HTML and check that no element has event handler attributes.
        // We look for on-prefixed attributes inside actual HTML tags (< ... >),
        // not in escaped text content like &lt;img onerror=...&gt;
        const tagPattern = /<[a-z][^>]*>/gi;
        const tags = html.match(tagPattern) || [];
        for (const tag of tags) {
          // Check for event handler attributes within actual HTML tags
          const eventHandlerInTag = /\s+on[a-z]+\s*=/i;
          expect(eventHandlerInTag.test(tag)).toBe(false);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('output never contains javascript: URL schemes in active HTML attributes', () => {
    fc.assert(
      fc.property(arbitraryStringWithXss, (input) => {
        const html = convertMarkdownToHtml(input);
        // Check that no href or src attribute contains javascript: scheme.
        // We only care about active attributes, not escaped text content.
        const attrPattern = /(?:href|src)\s*=\s*["']?\s*javascript:/i;
        const tagPattern = /<[a-z][^>]*>/gi;
        const tags = html.match(tagPattern) || [];
        for (const tag of tags) {
          expect(attrPattern.test(tag)).toBe(false);
        }
      }),
      { numRuns: 200 },
    );
  });

  it('handles XSS payloads embedded in markdown constructs', () => {
    const markdownWithXss = fc.oneof(
      // XSS in heading
      xssPayloadArb.map((payload) => `# ${payload}`),
      // XSS in bold
      xssPayloadArb.map((payload) => `**${payload}**`),
      // XSS in link text
      xssPayloadArb.map((payload) => `[${payload}](https://example.com)`),
      // XSS in link URL
      fc.constant(`[click](javascript:alert('xss'))`),
      // XSS in code block (should be escaped)
      xssPayloadArb.map((payload) => `\`\`\`\n${payload}\n\`\`\``),
      // XSS in blockquote
      xssPayloadArb.map((payload) => `> ${payload}`),
    );

    fc.assert(
      fc.property(markdownWithXss, (input) => {
        const html = convertMarkdownToHtml(input);
        // No <script tags in output at all
        expect(html.toLowerCase()).not.toContain('<script');
        // No event handlers in active HTML tags
        const tagPattern = /<[a-z][^>]*>/gi;
        const tags = html.match(tagPattern) || [];
        for (const tag of tags) {
          const eventHandlerInTag = /\s+on[a-z]+\s*=/i;
          expect(eventHandlerInTag.test(tag)).toBe(false);
          // No javascript: in href/src attributes
          const jsInAttr = /(?:href|src)\s*=\s*["']?\s*javascript:/i;
          expect(jsInAttr.test(tag)).toBe(false);
        }
      }),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 3: Round-trip text preservation
 *
 * **Validates: Requirements 1.5**
 *
 * For any plain text string (no markdown syntax), converting it to HTML via
 * `convertMarkdownToHtml` and then extracting the text content from the
 * resulting HTML SHALL produce a string that contains the original text.
 */
describe('Property 3: Round-trip text preservation', () => {
  /**
   * Arbitrary for plain text strings that contain no markdown syntax characters
   * and no HTML-special characters (which get entity-encoded in HTML output).
   * These are safe to round-trip through markdown→HTML→text without transformation.
   */
  const plainTextArb = fc
    .string({ minLength: 1, maxLength: 100 })
    .map((s) => s.replace(/[#*`\[\]()>|\-\\{}_~<!\n\r&"'+:=]/g, 'a').trim())
    .filter((s) => s.length > 0);

  /**
   * Strips HTML tags from a string and decodes HTML entities to extract text content.
   * Simulates what a browser's `textContent` property would return.
   */
  function stripHtmlTags(html: string): string {
    return html
      .replace(/<[^>]*>/g, '')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&#x27;/g, "'")
      .replace(/&nbsp;/g, ' ')
      .trim();
  }

  it('text content is preserved after markdown-to-HTML conversion and tag stripping', () => {
    fc.assert(
      fc.property(plainTextArb, (text) => {
        const html = convertMarkdownToHtml(text);
        const extractedText = stripHtmlTags(html);

        expect(extractedText).toContain(text);
      }),
      { numRuns: 200 },
    );
  });
});

/**
 * Property 4: Copy path consistency
 *
 * **Validates: Requirements 5.3, 6.3**
 *
 * For any valid `complete`-type JSON message string with an `answer` field,
 * the HTML produced by extracting the markdown via `extractMessageContent`
 * and then converting via `convertMarkdownToHtml` SHALL be identical to the
 * HTML produced by converting the `answer` field directly via `convertMarkdownToHtml`.
 * This ensures the Chat.tsx copy button and the CompleteRenderer copy button
 * produce the same formatted output.
 */
describe('Property 4: Copy path consistency', () => {
  /**
   * Arbitrary for markdown content that can appear in an answer field.
   * Generates strings containing common markdown elements.
   */
  const markdownContentArb = fc.oneof(
    // Plain text
    fc.string({ minLength: 1, maxLength: 100 }),
    // Headings
    fc.tuple(fc.integer({ min: 1, max: 6 }), fc.string({ minLength: 1, maxLength: 30 })).map(
      ([level, text]) => `${'#'.repeat(level)} ${text}`,
    ),
    // Bold text
    fc.string({ minLength: 1, maxLength: 30 }).map((text) => `**${text}**`),
    // Italic text
    fc.string({ minLength: 1, maxLength: 30 }).map((text) => `*${text}*`),
    // Code blocks
    fc.string({ minLength: 1, maxLength: 50 }).map((text) => `\`\`\`\n${text}\n\`\`\``),
    // Inline code
    fc.string({ minLength: 1, maxLength: 20 }).map((text) => `\`${text}\``),
    // Blockquotes
    fc.string({ minLength: 1, maxLength: 50 }).map((text) => `> ${text}`),
    // Lists
    fc
      .array(fc.string({ minLength: 1, maxLength: 20 }), { minLength: 1, maxLength: 5 })
      .map((items) => items.map((item) => `- ${item}`).join('\n')),
    // Mixed content
    fc
      .array(fc.string({ minLength: 1, maxLength: 40 }), { minLength: 1, maxLength: 5 })
      .map((lines) => lines.join('\n\n')),
  );

  it('extractMessageContent + convertMarkdownToHtml produces same HTML as direct convertMarkdownToHtml on answer field', () => {
    fc.assert(
      fc.property(markdownContentArb, (answerContent) => {
        // Build a valid complete-type JSON string
        const jsonString = JSON.stringify({ type: 'complete', answer: answerContent });

        // Path 1: Extract via extractMessageContent, then convert
        const extractedMarkdown = extractMessageContent(jsonString);
        const htmlViaExtraction = convertMarkdownToHtml(extractedMarkdown);

        // Path 2: Convert the answer field directly
        const htmlDirect = convertMarkdownToHtml(answerContent);

        // Both paths must produce identical HTML
        expect(htmlViaExtraction).toBe(htmlDirect);
      }),
      { numRuns: 200 },
    );
  });
});
