import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

// --- Hoisted mocks ---
const { mockNavigate, mockUseIsMobile, mockClearUnread, mockUser, mockLogout, mockGetSession } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockUseIsMobile: vi.fn(() => false),
  mockClearUnread: vi.fn(),
  mockUser: { id: 'test-user', name: 'Test User', email: 'test@example.com' },
  mockLogout: vi.fn(),
  mockGetSession: vi.fn(),
}));

vi.mock('react-router', () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock('@/app/context/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    logout: mockLogout,
    isLoading: false,
    getSession: mockGetSession,
  }),
}));

vi.mock('@/app/contexts/ThemeContext', () => ({
  useTheme: () => ({
    theme: 'light',
    toggleTheme: vi.fn(),
  }),
}));

vi.mock('@/app/context/AgentContext', () => ({
  useAgents: () => ({
    agents: [{ agentId: 'agent-1', name: 'Test Agent', description: 'A test agent' }],
    loading: false,
  }),
}));

vi.mock('@/app/context/ModelContext', () => ({
  useModels: () => ({
    models: [{ id: 'model-1', name: 'Test Model' }],
    defaultModelId: 'model-1',
  }),
}));

const stableSendMessage = vi.fn();
vi.mock('@/app/hooks/useAppSyncChat', () => ({
  useAppSyncChat: () => ({
    sendMessage: stableSendMessage,
    processingChats: new Set(),
    unreadChats: new Set(),
    clearUnread: mockClearUnread,
    connectionStatus: 'connected' as const,
    error: null,
  }),
}));

vi.mock('@/app/config/uploadConfig', () => ({
  getUploadConfig: () => {
    throw new Error('Upload not configured');
  },
}));

vi.mock('@/app/config/cognitoConfig', () => ({
  getCognitoConfig: () => ({
    userPoolId: 'test-pool',
    clientId: 'test-client',
    region: 'us-east-1',
  }),
}));

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

// Mock lucide-react with explicit lightweight stubs for every icon used by Chat.tsx
// and its transitive UI component dependencies. Avoids importOriginal which causes OOM.
vi.mock('lucide-react', () => {
  const makeIcon = (name: string, testId?: string) => {
    const Icon = React.forwardRef<SVGSVGElement, React.SVGProps<SVGSVGElement>>(
      (props, ref) => <svg data-testid={testId} data-icon={name} ref={ref} {...props} />,
    );
    Icon.displayName = name;
    return Icon;
  };
  return {
    LogOut: makeIcon('LogOut'),
    Send: makeIcon('Send'),
    Paperclip: makeIcon('Paperclip'),
    X: makeIcon('X'),
    Bot: makeIcon('Bot'),
    User: makeIcon('User'),
    Plus: makeIcon('Plus'),
    Trash2: makeIcon('Trash2'),
    RotateCcw: makeIcon('RotateCcw'),
    Copy: makeIcon('Copy'),
    RefreshCw: makeIcon('RefreshCw'),
    Moon: makeIcon('Moon'),
    Sun: makeIcon('Sun'),
    MoreVertical: makeIcon('MoreVertical'),
    Menu: makeIcon('Menu', 'icon-menu'),
    ChevronDownIcon: makeIcon('ChevronDownIcon'),
    ChevronUpIcon: makeIcon('ChevronUpIcon'),
    ChevronDown: makeIcon('ChevronDown'),
    ChevronUp: makeIcon('ChevronUp'),
    ChevronRightIcon: makeIcon('ChevronRightIcon'),
    CheckIcon: makeIcon('CheckIcon'),
    CircleIcon: makeIcon('CircleIcon'),
    XIcon: makeIcon('XIcon'),
    SearchIcon: makeIcon('SearchIcon'),
    PanelLeftIcon: makeIcon('PanelLeftIcon'),
    ChevronRight: makeIcon('ChevronRight'),
    ChevronLeft: makeIcon('ChevronLeft'),
    MoreHorizontal: makeIcon('MoreHorizontal'),
    MoreHorizontalIcon: makeIcon('MoreHorizontalIcon'),
    ChevronLeftIcon: makeIcon('ChevronLeftIcon'),
    ChevronRightIcon2: makeIcon('ChevronRightIcon2'),
    ArrowLeft: makeIcon('ArrowLeft'),
    ArrowRight: makeIcon('ArrowRight'),
    GripVerticalIcon: makeIcon('GripVerticalIcon'),
    MinusIcon: makeIcon('MinusIcon'),
  };
});

vi.mock('@/app/components/ui/use-mobile', () => ({
  useIsMobile: mockUseIsMobile,
}));

// Mock Sheet to avoid Radix Dialog animation hangs in jsdom.
// Renders children only when open=true, tracks open state via data attribute.
vi.mock('@/app/components/ui/sheet', () => {
  return {
    Sheet: ({ children, open }: { children: React.ReactNode; open: boolean; onOpenChange: (v: boolean) => void }) => (
      <div data-testid="sheet-root" data-open={String(open)}>
        {children}
      </div>
    ),
    SheetContent: ({ children, side }: { children: React.ReactNode; side?: string }) => (
      <div data-slot="sheet-content" data-side={side || 'right'}>
        {children}
      </div>
    ),
    SheetTitle: ({ children, className }: { children: React.ReactNode; className?: string }) => (
      <h2 data-slot="sheet-title" className={className}>{children}</h2>
    ),
  };
});

// Mock Radix DropdownMenu to avoid animation/portal hangs in jsdom.
vi.mock('@/app/components/ui/dropdown-menu', () => {
  return {
    DropdownMenu: ({ children }: { children: React.ReactNode }) => <div data-slot="dropdown-menu">{children}</div>,
    DropdownMenuTrigger: ({ children, asChild, ...props }: { children: React.ReactNode; asChild?: boolean; onClick?: (e: React.MouseEvent) => void }) => (
      <div data-slot="dropdown-menu-trigger" {...props}>{children}</div>
    ),
    DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div data-slot="dropdown-menu-content">{children}</div>,
    DropdownMenuItem: ({ children, ...props }: { children: React.ReactNode; className?: string; onClick?: (e: React.MouseEvent) => void }) => (
      <div data-slot="dropdown-menu-item" {...props}>{children}</div>
    ),
  };
});

// Mock Radix AlertDialog to avoid animation/portal hangs in jsdom.
vi.mock('@/app/components/ui/alert-dialog', () => {
  return {
    AlertDialog: ({ children }: { children: React.ReactNode }) => <div data-slot="alert-dialog">{children}</div>,
    AlertDialogAction: ({ children, ...props }: { children: React.ReactNode; onClick?: () => void }) => <button {...props}>{children}</button>,
    AlertDialogCancel: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
    AlertDialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    AlertDialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
    AlertDialogFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    AlertDialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    AlertDialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  };
});

// Mock Radix Select to avoid animation/portal hangs in jsdom.
vi.mock('@/app/components/ui/select', () => {
  return {
    Select: ({ children }: { children: React.ReactNode }) => <div data-slot="select">{children}</div>,
    SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    SelectItem: ({ children }: { children: React.ReactNode; value: string }) => <div>{children}</div>,
    SelectTrigger: ({ children }: { children: React.ReactNode }) => <button>{children}</button>,
    SelectValue: () => <span />,
  };
});

// Mock Radix ScrollArea to avoid potential jsdom issues.
vi.mock('@/app/components/ui/scroll-area', () => {
  return {
    ScrollArea: React.forwardRef<HTMLDivElement, { children: React.ReactNode; className?: string }>(
      ({ children, className }, ref) => <div ref={ref} className={className} data-slot="scroll-area-viewport">{children}</div>
    ),
  };
});

// Stub Element.prototype.scrollTo for jsdom
Element.prototype.scrollTo = vi.fn();

import { Chat } from './Chat';

describe('Chat mobile layout unit tests', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
    const store: Record<string, string> = {};
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => store[key] ?? null);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key, value) => {
      store[key] = String(value);
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('4.1 Sidebar not rendered inline on mobile (viewport < 768px)', () => {
    it('should not render the inline sidebar div when isMobile is true', () => {
      mockUseIsMobile.mockReturnValue(true);
      const { container, unmount } = render(<Chat />);

      const inlineSidebar = container.querySelector('.w-80.border-r');
      expect(inlineSidebar).toBeNull();

      unmount();
    });
  });

  describe('4.2 Hamburger/menu button rendered on mobile (viewport < 768px)', () => {
    it('should render a hamburger menu button when isMobile is true', () => {
      mockUseIsMobile.mockReturnValue(true);
      const { container, unmount } = render(<Chat />);

      const menuIcon = container.querySelector('[data-testid="icon-menu"]');
      expect(menuIcon).not.toBeNull();

      unmount();
    });
  });

  describe('4.3 Clicking hamburger button opens sidebar as Sheet overlay', () => {
    it('should open the Sheet overlay when the hamburger button is clicked', () => {
      mockUseIsMobile.mockReturnValue(true);
      const { container, unmount } = render(<Chat />);

      // Verify Sheet starts closed
      const sheetRoot = container.querySelector('[data-testid="sheet-root"]');
      expect(sheetRoot).not.toBeNull();
      expect(sheetRoot!.getAttribute('data-open')).toBe('false');

      // Find and click the hamburger button
      const menuIcon = container.querySelector('[data-testid="icon-menu"]');
      const hamburgerButton = menuIcon!.closest('button');
      expect(hamburgerButton).not.toBeNull();

      act(() => {
        fireEvent.click(hamburgerButton!);
      });

      // After clicking, the Sheet should be open
      expect(sheetRoot!.getAttribute('data-open')).toBe('true');

      // Verify SheetContent is rendered with side="left"
      const sheetContent = container.querySelector('[data-slot="sheet-content"]');
      expect(sheetContent).not.toBeNull();
      expect(sheetContent!.getAttribute('data-side')).toBe('left');

      unmount();
    });
  });

  describe('4.4 Selecting a chat on mobile closes the sidebar overlay', () => {
    it('should close the sidebar overlay when a chat is selected on mobile', () => {
      vi.useRealTimers();
      mockUseIsMobile.mockReturnValue(true);

      const now = '2025-01-01T00:00:00.000Z';
      const storedChats = [
        {
          id: 'chat-1',
          title: 'Test Chat',
          agentId: 'agent-1',
          modelId: 'model-1',
          messages: [],
          createdAt: now,
          updatedAt: now,
        },
      ];

      const getItemMock = vi.fn((key: string) => {
        if (key === 'ai-agent-chats') return JSON.stringify(storedChats);
        return null;
      });
      const setItemMock = vi.fn();
      vi.spyOn(Storage.prototype, 'getItem').mockImplementation(getItemMock);
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(setItemMock);

      const { container, unmount } = render(<Chat />);

      // Open the sidebar via hamburger button
      const menuIcon = container.querySelector('[data-testid="icon-menu"]');
      expect(menuIcon).not.toBeNull();
      const hamburgerButton = menuIcon!.closest('button');
      expect(hamburgerButton).not.toBeNull();

      fireEvent.click(hamburgerButton!);

      const sheetRoot = container.querySelector('[data-testid="sheet-root"]');
      expect(sheetRoot).not.toBeNull();
      expect(sheetRoot!.getAttribute('data-open')).toBe('true');

      // Find the chat item inside the sheet and click it
      const sheetContent = container.querySelector('[data-slot="sheet-content"]')!;
      expect(sheetContent).not.toBeNull();
      const chatItems = sheetContent.querySelectorAll('[class*="cursor-pointer"]');
      expect(chatItems.length).toBeGreaterThan(0);

      fireEvent.click(chatItems[0]);

      // After selecting a chat on mobile, the Sheet should close
      expect(sheetRoot!.getAttribute('data-open')).toBe('false');

      unmount();
    });
  });

  describe('4.5 Desktop: sidebar renders inline with no hamburger button (viewport >= 768px)', () => {
    it('should render the sidebar inline with w-80 class and no hamburger button on desktop', () => {
      mockUseIsMobile.mockReturnValue(false);
      const { container, unmount } = render(<Chat />);

      const inlineSidebar = container.querySelector('.w-80.border-r');
      expect(inlineSidebar).not.toBeNull();

      const menuIcon = container.querySelector('[data-testid="icon-menu"]');
      expect(menuIcon).toBeNull();

      const sheetRoot = container.querySelector('[data-testid="sheet-root"]');
      expect(sheetRoot).toBeNull();

      unmount();
    });
  });
});
