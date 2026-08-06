import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

// --- Hoisted mocks ---
const { mockCopyFormatted, mockCopyPlainText, mockConvertMarkdownToHtml, mockExtractMessageContent, mockToast } = vi.hoisted(() => ({
  mockCopyFormatted: vi.fn().mockResolvedValue(undefined),
  mockCopyPlainText: vi.fn().mockResolvedValue(undefined),
  mockConvertMarkdownToHtml: vi.fn().mockReturnValue('<p>converted</p>'),
  mockExtractMessageContent: vi.fn().mockReturnValue('extracted markdown'),
  mockToast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/app/utils/clipboardUtils', () => ({
  copyFormattedToClipboard: mockCopyFormatted,
  copyPlainTextToClipboard: mockCopyPlainText,
}));

vi.mock('@/app/utils/markdownToHtml', () => ({
  convertMarkdownToHtml: mockConvertMarkdownToHtml,
}));

vi.mock('@/app/utils/messageContentExtractor', () => ({
  extractMessageContent: mockExtractMessageContent,
}));

vi.mock('sonner', () => ({
  toast: mockToast,
}));

import { CopyFormatButton } from './CopyFormatButton';

describe('CopyFormatButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('User messages (role="user")', () => {
    it('renders a simple copy button without dropdown trigger', () => {
      // Validates: Requirements 4.6
      render(<CopyFormatButton content="Hello world" role="user" />);

      const copyButton = screen.getByTitle('Copy message');
      expect(copyButton).toBeInTheDocument();

      // No dropdown trigger should be present
      expect(screen.queryByTitle('Copy options')).not.toBeInTheDocument();
    });

    it('copies content as plain text when clicked', async () => {
      // Validates: Requirements 4.6
      const user = userEvent.setup();
      render(<CopyFormatButton content="User typed this" role="user" />);

      await user.click(screen.getByTitle('Copy message'));

      await waitFor(() => {
        expect(mockCopyPlainText).toHaveBeenCalledWith('User typed this');
      });
    });
  });

  describe('Assistant messages (role="assistant")', () => {
    it('renders a copy button that opens a dropdown', () => {
      // Validates: Requirements 4.1
      render(<CopyFormatButton content='{"type":"complete","answer":"# Hello"}' role="assistant" />);

      expect(screen.getByTitle('Copy options')).toBeInTheDocument();
    });

    it('"Copy as Markdown" dropdown option copies plain text', async () => {
      // Validates: Requirements 4.2, 4.3, 4.4
      const user = userEvent.setup();
      render(<CopyFormatButton content='{"type":"complete","answer":"# Hello"}' role="assistant" />);

      // Open dropdown
      await user.click(screen.getByTitle('Copy options'));

      // Click "Copy as Markdown" option
      const markdownOption = await screen.findByText('Copy as Markdown');
      await user.click(markdownOption);

      await waitFor(() => {
        expect(mockExtractMessageContent).toHaveBeenCalledWith('{"type":"complete","answer":"# Hello"}');
        expect(mockCopyPlainText).toHaveBeenCalledWith('extracted markdown');
      });
    });

    it('"Copy as Formatted Text" dropdown option calls convertMarkdownToHtml and copyFormattedToClipboard', async () => {
      // Validates: Requirements 4.5
      const user = userEvent.setup();
      render(<CopyFormatButton content='{"type":"complete","answer":"# Hello"}' role="assistant" />);

      // Open dropdown
      await user.click(screen.getByTitle('Copy options'));

      // Click "Copy as Formatted Text" option
      const formattedOption = await screen.findByText('Copy as Formatted Text');
      await user.click(formattedOption);

      await waitFor(() => {
        expect(mockExtractMessageContent).toHaveBeenCalledWith('{"type":"complete","answer":"# Hello"}');
        expect(mockConvertMarkdownToHtml).toHaveBeenCalledWith('extracted markdown');
        expect(mockCopyFormatted).toHaveBeenCalledWith('<p>converted</p>', 'extracted markdown');
      });
    });

    it('uses markdown prop directly when provided (CompleteRenderer path)', async () => {
      // Validates: Requirements 5.1, 5.2
      const user = userEvent.setup();
      render(<CopyFormatButton content="" role="assistant" markdown="# Direct markdown" />);

      // Open dropdown and click formatted copy
      await user.click(screen.getByTitle('Copy options'));
      const formattedOption = await screen.findByText('Copy as Formatted Text');
      await user.click(formattedOption);

      await waitFor(() => {
        // Should NOT call extractMessageContent when markdown prop is provided
        expect(mockExtractMessageContent).not.toHaveBeenCalled();
        expect(mockConvertMarkdownToHtml).toHaveBeenCalledWith('# Direct markdown');
        expect(mockCopyFormatted).toHaveBeenCalledWith('<p>converted</p>', '# Direct markdown');
      });
    });
  });

  describe('Toast notifications', () => {
    it('shows success toast on successful copy', async () => {
      // Validates: Requirements 4.1
      const user = userEvent.setup();
      render(<CopyFormatButton content="Hello" role="user" />);

      await user.click(screen.getByTitle('Copy message'));

      await waitFor(() => {
        expect(mockToast.success).toHaveBeenCalledWith('Copied to clipboard');
      });
    });

    it('shows error toast when copy fails', async () => {
      // Validates: Requirements 4.1
      mockCopyPlainText.mockRejectedValueOnce(new Error('Clipboard write failed'));
      const user = userEvent.setup();
      render(<CopyFormatButton content="Hello" role="user" />);

      await user.click(screen.getByTitle('Copy message'));

      await waitFor(() => {
        expect(mockToast.error).toHaveBeenCalledWith('Failed to copy to clipboard');
      });
    });

    it('shows success toast for formatted copy', async () => {
      // Validates: Requirements 4.5
      const user = userEvent.setup();
      render(<CopyFormatButton content='{"type":"complete","answer":"test"}' role="assistant" />);

      await user.click(screen.getByTitle('Copy options'));
      const formattedOption = await screen.findByText('Copy as Formatted Text');
      await user.click(formattedOption);

      await waitFor(() => {
        expect(mockToast.success).toHaveBeenCalledWith('Copied as Formatted Text');
      });
    });

    it('shows error toast when formatted copy fails', async () => {
      // Validates: Requirements 4.5
      mockCopyFormatted.mockRejectedValueOnce(new Error('Clipboard write failed'));
      const user = userEvent.setup();
      render(<CopyFormatButton content='{"type":"complete","answer":"test"}' role="assistant" />);

      await user.click(screen.getByTitle('Copy options'));
      const formattedOption = await screen.findByText('Copy as Formatted Text');
      await user.click(formattedOption);

      await waitFor(() => {
        expect(mockToast.error).toHaveBeenCalledWith('Failed to copy to clipboard');
      });
    });
  });
});
