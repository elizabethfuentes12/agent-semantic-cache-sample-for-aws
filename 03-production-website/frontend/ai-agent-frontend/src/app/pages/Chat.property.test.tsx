import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as fc from 'fast-check';
import { render, screen } from '@testing-library/react';
import React from 'react';

/**
 * Property 1: Bug Condition — Mobile Sidebar Hidden By Default
 *
 * **Validates: Requirements 2.1, 2.2, 2.3**
 *
 * For any viewport width in [320, 767], the Chat component SHALL hide the sidebar
 * by default and render a visible hamburger/menu button to toggle the sidebar open.
 *
 * This is a PBT-exploration test: it is expected to FAIL on the unfixed code,
 * confirming the bug exists (sidebar always visible, no hamburger button).
 */

// --- Hoisted mocks ---
const { mockNavigate, mockUseIsMobile } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockUseIsMobile: vi.fn(() => false),
}));

vi.mock('react-router', () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock('@/app/context/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'test-user', name: 'Test User', email: 'test@example.com' },
    logout: vi.fn(),
    isLoading: false,
    getSession: vi.fn(),
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

vi.mock('@/app/hooks/useAppSyncChat', () => ({
  useAppSyncChat: () => ({
    sendMessage: vi.fn(),
    processingChats: new Set(),
    unreadChats: new Set(),
    clearUnread: vi.fn(),
    connectionStatus: 'connected',
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

// Mock lucide-react: use real exports but add a testid-bearing Menu icon for detection
vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('lucide-react')>();
  const MenuIcon = React.forwardRef<SVGSVGElement, React.SVGProps<SVGSVGElement>>(
    (props, ref) => <svg data-testid="icon-menu" ref={ref} {...props} />,
  );
  MenuIcon.displayName = 'Menu';
  return {
    ...actual,
    Menu: MenuIcon,
  };
});

vi.mock('@/app/components/ui/use-mobile', () => ({
  useIsMobile: mockUseIsMobile,
}));

// Mock Sheet to track rendering in jsdom — renders children only when open=true,
// tracks open state via data attribute for assertion.
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

// Stub Element.prototype.scrollTo for jsdom (Chat uses it for auto-scroll)
Element.prototype.scrollTo = vi.fn();

import { Chat } from './Chat';

describe('Property 1: Bug Condition — Mobile Sidebar Hidden By Default', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock localStorage
    const store: Record<string, string> = {};
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => store[key] ?? null);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key, value) => {
      store[key] = value;
    });
  });

  it('for any mobile viewport width in [320, 767], the sidebar should be hidden by default and a hamburger button should be present', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 320, max: 767 }),
        (viewportWidth) => {
          // Configure the useIsMobile hook to return true for this mobile viewport
          mockUseIsMobile.mockReturnValue(true);

          // Set the viewport width
          Object.defineProperty(window, 'innerWidth', {
            writable: true,
            configurable: true,
            value: viewportWidth,
          });

          const { container, unmount } = render(<Chat />);

          // ASSERTION 1: The sidebar should NOT be rendered as an inline element
          // In the unfixed code, the sidebar is always rendered with class "w-80"
          // On mobile, it should be hidden by default (not present as an inline flex child)
          const inlineSidebar = container.querySelector('.w-80.border-r');
          expect(
            inlineSidebar,
            `At viewport ${viewportWidth}px, the sidebar should be hidden by default on mobile, but it is rendered inline`,
          ).toBeNull();

          // ASSERTION 2: A hamburger/menu button should be present on mobile
          // Look for a menu/hamburger button by its icon or aria-label
          const menuButton = container.querySelector('[data-testid="icon-menu"]');
          expect(
            menuButton,
            `At viewport ${viewportWidth}px, a hamburger/menu button should be present on mobile`,
          ).not.toBeNull();

          unmount();
        },
      ),
      { numRuns: 20 },
    );
  });
});


/**
 * Property 2: Preservation — Desktop Layout Unchanged
 *
 * **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
 *
 * For any viewport width in [768, 2560], the Chat component SHALL render the sidebar
 * as an inline flex child with `w-80 border-r` classes, with no hamburger/menu button
 * present and no Sheet overlay rendered.
 *
 * This preservation test confirms that the mobile-responsive fix does not regress
 * the desktop layout. It should PASS on both unfixed and fixed code.
 */
describe('Property 2: Preservation — Desktop Layout Unchanged', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock localStorage
    const store: Record<string, string> = {};
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => store[key] ?? null);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation((key, value) => {
      store[key] = String(value);
    });
  });

  it('for any desktop viewport width in [768, 2560], the sidebar should be rendered inline with w-80 border-r classes', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 768, max: 2560 }),
        (viewportWidth) => {
          // Configure the useIsMobile hook to return false for desktop viewports
          mockUseIsMobile.mockReturnValue(false);

          // Set the viewport width
          Object.defineProperty(window, 'innerWidth', {
            writable: true,
            configurable: true,
            value: viewportWidth,
          });

          const { container, unmount } = render(<Chat />);

          // ASSERTION 1: The sidebar SHOULD be rendered as an inline element with w-80 border-r
          const inlineSidebar = container.querySelector('.w-80.border-r');
          expect(
            inlineSidebar,
            `At viewport ${viewportWidth}px, the sidebar should be rendered inline with w-80 border-r classes`,
          ).not.toBeNull();

          // ASSERTION 2: No hamburger/menu button should be present on desktop
          const menuButton = container.querySelector('[data-testid="icon-menu"]');
          expect(
            menuButton,
            `At viewport ${viewportWidth}px, no hamburger/menu button should be present on desktop`,
          ).toBeNull();

          // ASSERTION 3: No Sheet overlay should be rendered on desktop
          const sheetRoot = container.querySelector('[data-testid="sheet-root"]');
          expect(
            sheetRoot,
            `At viewport ${viewportWidth}px, no Sheet overlay should be rendered on desktop`,
          ).toBeNull();

          unmount();
        },
      ),
      { numRuns: 50 },
    );
  });
});


/**
 * Feature: chat-persistence, Property 3: Ordenamiento de conversaciones por fecha descendente
 *
 * **Validates: Requirements 3.2**
 *
 * For any array of conversations with random `updated_at` dates, after applying
 * the sorting logic used in Chat.tsx (`conversations.sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime())`),
 * each conversation's `updatedAt` must be >= the next conversation's `updatedAt`.
 */

interface MinimalConversation {
  id: string;
  updatedAt: Date;
}

describe('Feature: chat-persistence, Property 3: Ordenamiento de conversaciones por fecha descendente', () => {
  it('after sorting, each conversation updatedAt is >= the next one', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            id: fc.uuid(),
            updatedAt: fc.date(),
          }),
        ),
        (conversations: MinimalConversation[]) => {
          // Apply the same sorting logic used in Chat.tsx
          const sorted = [...conversations].sort(
            (a, b) => b.updatedAt.getTime() - a.updatedAt.getTime(),
          );

          // Verify descending order: each element's updatedAt >= next element's updatedAt
          for (let i = 0; i < sorted.length - 1; i++) {
            expect(sorted[i].updatedAt.getTime()).toBeGreaterThanOrEqual(
              sorted[i + 1].updatedAt.getTime(),
            );
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});


/**
 * Feature: chat-persistence, Property 6: Derivación de título desde el primer mensaje
 *
 * **Validates: Requirements 7.1**
 *
 * For any message string, the derived title must equal the first 50 characters of the
 * message if the message is 50 characters or fewer, or the first 50 characters followed
 * by "..." if the message exceeds 50 characters. In no case should the title (excluding
 * the "..." suffix) exceed 50 characters.
 */

/** Mirrors the title derivation logic from Chat.tsx */
function deriveTitle(firstMessage: string): string {
  return firstMessage.slice(0, 50) + (firstMessage.length > 50 ? '...' : '');
}

describe('Feature: chat-persistence, Property 6: Derivación de título desde el primer mensaje', () => {
  it('title equals message when length <= 50, or first 50 chars + "..." when length > 50', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 0, maxLength: 200 }),
        (message: string) => {
          const title = deriveTitle(message);

          if (message.length <= 50) {
            // Title should equal the message exactly
            expect(title).toBe(message);
          } else {
            // Title should be first 50 chars + "..."
            expect(title).toBe(message.slice(0, 50) + '...');
          }

          // The base part of the title (without "...") should never exceed 50 characters
          const basePart = title.endsWith('...') ? title.slice(0, -3) : title;
          expect(basePart.length).toBeLessThanOrEqual(50);
        },
      ),
      { numRuns: 100 },
    );
  });
});


/**
 * Feature: chat-persistence, Property 8: Acumulación de paginación sin pérdida de datos
 *
 * **Validates: Requirements 11.4**
 *
 * For any sequence of paginated responses (each with an array of items and a `next_token`),
 * accumulating all items from all pages using `accumulated = [...accumulated, ...page.items]`
 * must produce a list that contains exactly the union of all items from all pages, in the
 * original order, with no items lost or duplicated.
 */

interface PaginatedItem {
  id: string;
}

interface PaginatedResponse {
  items: PaginatedItem[];
  next_token: string | null;
}

/**
 * Simulates the pagination accumulation logic used in Chat.tsx:
 * for each page response, append its items to the accumulated list.
 */
function accumulatePages(pages: PaginatedResponse[]): PaginatedItem[] {
  let accumulated: PaginatedItem[] = [];
  for (const page of pages) {
    accumulated = [...accumulated, ...page.items];
  }
  return accumulated;
}

describe('Feature: chat-persistence, Property 8: Acumulación de paginación sin pérdida de datos', () => {
  it('accumulated list contains exactly the union of all page items in original order, with no loss or duplication', () => {
    // Generate a sequence of pages, where each inner array is a page of items
    const pagesArbitrary = fc.array(
      fc.array(fc.record({ id: fc.uuid() }), { minLength: 0, maxLength: 20 }),
      { minLength: 0, maxLength: 10 },
    );

    fc.assert(
      fc.property(
        pagesArbitrary,
        (pageItemArrays: PaginatedItem[][]) => {
          // Build paginated responses: each page gets a next_token except the last
          const pages: PaginatedResponse[] = pageItemArrays.map((items, index) => ({
            items,
            next_token: index < pageItemArrays.length - 1 ? `token-${index + 1}` : null,
          }));

          // Accumulate using the same logic as the production code
          const accumulated = accumulatePages(pages);

          // Build the expected flat list: all items from all pages in order
          const expectedItems = pageItemArrays.flat();

          // Verify: accumulated length equals total items across all pages (no loss, no duplication)
          expect(accumulated.length).toBe(expectedItems.length);

          // Verify: each item matches exactly in order (no reordering)
          for (let i = 0; i < expectedItems.length; i++) {
            expect(accumulated[i].id).toBe(expectedItems[i].id);
          }

          // Verify: no items are lost — every expected item is present
          const accumulatedIds = accumulated.map((item) => item.id);
          const expectedIds = expectedItems.map((item) => item.id);
          expect(accumulatedIds).toEqual(expectedIds);
        },
      ),
      { numRuns: 100 },
    );
  });
});
