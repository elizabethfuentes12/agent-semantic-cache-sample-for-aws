import { Marked } from "marked";
import DOMPurify from "dompurify";

// Configure marked for GFM support (tables, strikethrough, autolinks)
const markedInstance = new Marked({
  gfm: true,
  async: false,
});

/**
 * Converts a markdown string to sanitized HTML.
 * Uses `marked` for markdown parsing and `DOMPurify` for XSS sanitization.
 *
 * @param markdown - The markdown source string
 * @returns Sanitized HTML string
 */
export function convertMarkdownToHtml(markdown: string): string {
  if (!markdown) {
    return "";
  }

  let rawHtml: string;

  try {
    rawHtml = markedInstance.parse(markdown) as string;
  } catch {
    // Fall back to wrapping the original string in <p> tags
    return DOMPurify.sanitize(`<p>${markdown}</p>`);
  }

  return DOMPurify.sanitize(rawHtml);
}
