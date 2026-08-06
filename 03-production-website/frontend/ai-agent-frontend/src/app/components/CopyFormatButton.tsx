import { useState, useCallback } from 'react';
import { extractMessageContent } from '@/app/utils/messageContentExtractor';
import { convertMarkdownToHtml } from '@/app/utils/markdownToHtml';
import { copyFormattedToClipboard, copyPlainTextToClipboard } from '@/app/utils/clipboardUtils';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from './ui/dropdown-menu';
import { Button } from './ui/button';
import { Copy, Check, ChevronDown, FileText, FileCode } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from './ui/utils';

interface CopyFormatButtonProps {
  /** The raw message content (JSON string for assistant, plain text for user) */
  content: string;
  /** The message role — user messages get plain copy only */
  role: 'user' | 'assistant';
  /** Optional: pre-extracted markdown (used by CompleteRenderer which already has the answer) */
  markdown?: string;
  /** Additional CSS classes for the container */
  className?: string;
}

export function CopyFormatButton({ content, role, markdown, className }: CopyFormatButtonProps) {
  const [copied, setCopied] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const showCopiedFeedback = useCallback(() => {
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  const getMarkdownContent = useCallback((): string => {
    if (markdown != null) {
      return markdown;
    }
    return extractMessageContent(content);
  }, [content, markdown]);

  const handleCopyPlainText = useCallback(async () => {
    try {
      if (role === 'user') {
        await copyPlainTextToClipboard(content);
      } else {
        const md = getMarkdownContent();
        await copyPlainTextToClipboard(md);
      }
      showCopiedFeedback();
      toast.success('Copied to clipboard');
    } catch {
      toast.error('Failed to copy to clipboard');
    }
  }, [content, role, getMarkdownContent, showCopiedFeedback]);

  const handleCopyMarkdown = useCallback(async () => {
    try {
      const md = getMarkdownContent();
      await copyPlainTextToClipboard(md);
      showCopiedFeedback();
      toast.success('Copied as Markdown');
    } catch {
      toast.error('Failed to copy to clipboard');
    }
  }, [getMarkdownContent, showCopiedFeedback]);

  const handleCopyFormatted = useCallback(async () => {
    try {
      const md = getMarkdownContent();
      const html = convertMarkdownToHtml(md);
      await copyFormattedToClipboard(html, md);
      showCopiedFeedback();
      toast.success('Copied as Formatted Text');
    } catch {
      toast.error('Failed to copy to clipboard');
    }
  }, [getMarkdownContent, showCopiedFeedback]);

  const CopyIcon = copied ? Check : Copy;

  // User messages: simple copy button, no dropdown
  if (role === 'user') {
    return (
      <Button
        variant="ghost"
        size="icon"
        className={cn('h-8 w-8', className)}
        onClick={handleCopyPlainText}
        title="Copy message"
      >
        <CopyIcon className="w-3.5 h-3.5" />
      </Button>
    );
  }

  // Assistant messages: dropdown with copy format options
  return (
    <DropdownMenu open={dropdownOpen} onOpenChange={setDropdownOpen} modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex items-center justify-center gap-1 rounded-md h-8 px-2 text-sm transition-all',
            'hover:bg-accent hover:text-accent-foreground',
            className,
            dropdownOpen && '!opacity-100',
          )}
          title="Copy options"
        >
          <CopyIcon className="w-3.5 h-3.5" />
          <ChevronDown className="w-2.5 h-2.5" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={4}>
        <DropdownMenuItem onSelect={handleCopyMarkdown}>
          <FileText className="w-4 h-4" />
          <span>Copy as Markdown</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={handleCopyFormatted}>
          <FileCode className="w-4 h-4" />
          <span>Copy as Formatted Text</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
