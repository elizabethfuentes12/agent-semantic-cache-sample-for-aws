/**
 * Writes both HTML and plain text to the clipboard using ClipboardItem API.
 * Falls back to writeText() if ClipboardItem is not supported.
 *
 * @param html - The sanitized HTML string for rich text pasting
 * @param plainText - The plain text fallback (markdown source)
 * @returns Promise that resolves on success, rejects on failure
 */
export async function copyFormattedToClipboard(
  html: string,
  plainText: string
): Promise<void> {
  if (
    typeof ClipboardItem !== "undefined" &&
    navigator.clipboard?.write
  ) {
    const htmlBlob = new Blob([html], { type: "text/html" });
    const textBlob = new Blob([plainText], { type: "text/plain" });
    const clipboardItem = new ClipboardItem({
      "text/html": htmlBlob,
      "text/plain": textBlob,
    });
    await navigator.clipboard.write([clipboardItem]);
  } else {
    await navigator.clipboard.writeText(plainText);
  }
}

/**
 * Writes plain text to the clipboard.
 *
 * @param text - The text to copy
 * @returns Promise that resolves on success, rejects on failure
 */
export async function copyPlainTextToClipboard(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}
