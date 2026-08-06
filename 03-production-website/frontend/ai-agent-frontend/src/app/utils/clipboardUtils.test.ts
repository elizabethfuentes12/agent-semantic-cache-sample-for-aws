import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { copyFormattedToClipboard, copyPlainTextToClipboard } from './clipboardUtils';

describe('copyFormattedToClipboard', () => {
  let writeMock: ReturnType<typeof vi.fn>;
  let writeTextMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writeMock = vi.fn().mockResolvedValue(undefined);
    writeTextMock = vi.fn().mockResolvedValue(undefined);

    Object.defineProperty(navigator, 'clipboard', {
      value: {
        write: writeMock,
        writeText: writeTextMock,
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls clipboard.write() with a ClipboardItem containing both MIME types when ClipboardItem is available', async () => {
    const mockClipboardItem = vi.fn();
    vi.stubGlobal('ClipboardItem', mockClipboardItem);

    const html = '<p>Hello</p>';
    const plainText = 'Hello';

    await copyFormattedToClipboard(html, plainText);

    expect(mockClipboardItem).toHaveBeenCalledTimes(1);
    const constructorArg = mockClipboardItem.mock.calls[0][0];
    expect(constructorArg['text/html']).toBeInstanceOf(Blob);
    expect(constructorArg['text/plain']).toBeInstanceOf(Blob);

    const htmlBlob: Blob = constructorArg['text/html'];
    const textBlob: Blob = constructorArg['text/plain'];
    expect(htmlBlob.type).toBe('text/html');
    expect(textBlob.type).toBe('text/plain');
    expect(await htmlBlob.text()).toBe(html);
    expect(await textBlob.text()).toBe(plainText);

    expect(writeMock).toHaveBeenCalledTimes(1);
    expect(writeTextMock).not.toHaveBeenCalled();
  });

  it('falls back to clipboard.writeText() when ClipboardItem is not available', async () => {
    vi.stubGlobal('ClipboardItem', undefined);

    const html = '<p>Hello</p>';
    const plainText = 'Hello';

    await copyFormattedToClipboard(html, plainText);

    expect(writeTextMock).toHaveBeenCalledWith(plainText);
    expect(writeMock).not.toHaveBeenCalled();
  });

  it('propagates errors when clipboard.write() rejects', async () => {
    const mockClipboardItem = vi.fn();
    vi.stubGlobal('ClipboardItem', mockClipboardItem);

    const error = new Error('Write failed');
    writeMock.mockRejectedValue(error);

    await expect(copyFormattedToClipboard('<p>Hi</p>', 'Hi')).rejects.toThrow('Write failed');
  });

  it('propagates errors when clipboard.writeText() rejects in fallback path', async () => {
    vi.stubGlobal('ClipboardItem', undefined);

    const error = new Error('WriteText failed');
    writeTextMock.mockRejectedValue(error);

    await expect(copyFormattedToClipboard('<p>Hi</p>', 'Hi')).rejects.toThrow('WriteText failed');
  });
});

describe('copyPlainTextToClipboard', () => {
  let writeTextMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writeTextMock = vi.fn().mockResolvedValue(undefined);

    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: writeTextMock,
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls clipboard.writeText() with the provided text', async () => {
    const text = '# Hello World\n\nSome **bold** text.';

    await copyPlainTextToClipboard(text);

    expect(writeTextMock).toHaveBeenCalledWith(text);
    expect(writeTextMock).toHaveBeenCalledTimes(1);
  });

  it('propagates errors when clipboard.writeText() rejects', async () => {
    const error = new Error('Permission denied');
    writeTextMock.mockRejectedValue(error);

    await expect(copyPlainTextToClipboard('test')).rejects.toThrow('Permission denied');
  });
});
