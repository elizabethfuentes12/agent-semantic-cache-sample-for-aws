import { describe, it, expect } from 'vitest';
import { convertMarkdownToHtml } from './markdownToHtml';

describe('convertMarkdownToHtml', () => {
  describe('heading conversion', () => {
    it('converts # Heading to <h1>', () => {
      const result = convertMarkdownToHtml('# Heading');
      expect(result).toContain('<h1>Heading</h1>');
    });

    it('converts ## Heading to <h2>', () => {
      const result = convertMarkdownToHtml('## Subheading');
      expect(result).toContain('<h2>Subheading</h2>');
    });
  });

  describe('bold conversion', () => {
    it('converts **bold** to <strong>', () => {
      const result = convertMarkdownToHtml('**bold**');
      expect(result).toContain('<strong>bold</strong>');
    });
  });

  describe('italic conversion', () => {
    it('converts *italic* to <em>', () => {
      const result = convertMarkdownToHtml('*italic*');
      expect(result).toContain('<em>italic</em>');
    });
  });

  describe('link conversion', () => {
    it('converts [text](url) to <a href="url">', () => {
      const result = convertMarkdownToHtml('[click here](https://example.com)');
      expect(result).toContain('<a href="https://example.com">click here</a>');
    });
  });

  describe('unordered list conversion', () => {
    it('converts - item to <ul><li>', () => {
      const result = convertMarkdownToHtml('- item one\n- item two');
      expect(result).toContain('<ul>');
      expect(result).toContain('<li>item one</li>');
      expect(result).toContain('<li>item two</li>');
    });
  });

  describe('ordered list conversion', () => {
    it('converts 1. item to <ol><li>', () => {
      const result = convertMarkdownToHtml('1. first\n2. second');
      expect(result).toContain('<ol>');
      expect(result).toContain('<li>first</li>');
      expect(result).toContain('<li>second</li>');
    });
  });

  describe('code block conversion', () => {
    it('converts triple backticks to <pre><code>', () => {
      const result = convertMarkdownToHtml('```\nconst x = 1;\n```');
      expect(result).toContain('<pre>');
      expect(result).toContain('<code>');
      expect(result).toContain('const x = 1;');
    });
  });

  describe('inline code conversion', () => {
    it('converts single backticks to <code>', () => {
      const result = convertMarkdownToHtml('use `npm install` to install');
      expect(result).toContain('<code>npm install</code>');
    });
  });

  describe('blockquote conversion', () => {
    it('converts > quote to <blockquote>', () => {
      const result = convertMarkdownToHtml('> This is a quote');
      expect(result).toContain('<blockquote>');
      expect(result).toContain('This is a quote');
    });
  });

  describe('table conversion', () => {
    it('converts GFM table to <table>', () => {
      const markdown = '| Header 1 | Header 2 |\n| --- | --- |\n| Cell 1 | Cell 2 |';
      const result = convertMarkdownToHtml(markdown);
      expect(result).toContain('<table>');
      expect(result).toContain('<th>Header 1</th>');
      expect(result).toContain('<td>Cell 1</td>');
    });
  });

  describe('empty input', () => {
    it('returns empty string for empty input', () => {
      const result = convertMarkdownToHtml('');
      expect(result).toBe('');
    });
  });

  describe('XSS sanitization', () => {
    it('strips script tags', () => {
      const result = convertMarkdownToHtml('<script>alert("xss")</script>');
      expect(result).not.toContain('<script');
      expect(result).not.toContain('</script>');
    });

    it('strips event handlers', () => {
      const result = convertMarkdownToHtml('<img src="x" onerror="alert(1)">');
      expect(result).not.toContain('onerror');
    });

    it('strips javascript: URLs', () => {
      const result = convertMarkdownToHtml('<a href="javascript:alert(1)">click</a>');
      expect(result).not.toContain('javascript:');
    });
  });
});
