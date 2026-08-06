import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AppSyncEventsService } from './appSyncEventsService';

/**
 * Helper: creates a mock fetch that returns a publish acknowledgment.
 */
function createMockFetch() {
  return vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({
      successful: [{ identifier: 'test-event-id', index: 0 }],
      failed: [],
    }),
    text: () => Promise.resolve(''),
  });
}

/**
 * Creates a mock WebSocket class that simulates the AppSync Events protocol.
 */
function createMockWebSocketClass(responseEvent: unknown, options?: { skipProtocol?: boolean }) {
  let instance: MockWsInstance | null = null;

  interface MockWsInstance {
    readyState: number;
    onopen: ((ev: Event) => void) | null;
    onmessage: ((ev: MessageEvent) => void) | null;
    onerror: ((ev: Event) => void) | null;
    onclose: ((ev: CloseEvent) => void) | null;
    send: (data: string) => void;
    close: () => void;
  }

  class MockWebSocket {
    static OPEN = 1;
    static CONNECTING = 0;
    static CLOSED = 3;

    readyState = 1;
    onopen: ((ev: Event) => void) | null = null;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    onerror: ((ev: Event) => void) | null = null;
    onclose: ((ev: CloseEvent) => void) | null = null;

    constructor(_url: string, _protocols?: string[]) {
      instance = this as unknown as MockWsInstance;
      setTimeout(() => { this.onopen?.({} as Event); }, 0);
    }

    send(data: string) {
      if (options?.skipProtocol) return;
      const parsed = JSON.parse(data);
      if (parsed.type === 'connection_init') {
        setTimeout(() => {
          this.onmessage?.({ data: JSON.stringify({ type: 'connection_ack' }) } as MessageEvent);
        }, 0);
      } else if (parsed.type === 'subscribe') {
        setTimeout(() => {
          this.onmessage?.({ data: JSON.stringify({ type: 'subscribe_success', id: parsed.id }) } as MessageEvent);
        }, 0);
      }
    }

    close() { this.readyState = 3; }
  }

  const triggerData = () => {
    instance?.onmessage?.({
      data: JSON.stringify({ type: 'data', event: JSON.stringify(responseEvent) }),
    } as MessageEvent);
  };
  const triggerError = () => {
    instance?.onmessage?.({
      data: JSON.stringify({ type: 'error', errors: [{ message: 'test error' }] }),
    } as MessageEvent);
  };

  return { MockWebSocket, triggerData, triggerError };
}

describe('AppSyncEventsService', () => {
  const mockGetToken = vi.fn().mockResolvedValue('mock-token');
  const endpoint = 'https://example.appsync-api.us-east-1.amazonaws.com/event';
  let service: AppSyncEventsService;

  beforeEach(() => {
    vi.restoreAllMocks();
    service = new AppSyncEventsService({ endpoint, getToken: mockGetToken });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('publishWithResponse', () => {
    it('should subscribe to the channel, publish, and return the response event', async () => {
      const responseBody = { conversations: [], next_token: null };
      const { MockWebSocket, triggerData } = createMockWebSocketClass(responseBody);
      vi.stubGlobal('WebSocket', MockWebSocket);

      const mockFetch = createMockFetch();
      vi.stubGlobal('fetch', mockFetch);

      const resultPromise = service.publishWithResponse('chat/', {
        action: 'list_conversations',
        user_id: 'user-123',
      });

      await vi.waitFor(() => { expect(mockFetch).toHaveBeenCalled(); });

      triggerData();

      const result = await resultPromise;
      expect(result).toEqual(responseBody);
    });

    it('should reject on WebSocket error event', async () => {
      const { MockWebSocket, triggerError } = createMockWebSocketClass({});
      vi.stubGlobal('WebSocket', MockWebSocket);

      const mockFetch = createMockFetch();
      vi.stubGlobal('fetch', mockFetch);

      const resultPromise = service.publishWithResponse('chat/', { action: 'invalid' });

      await vi.waitFor(() => { expect(mockFetch).toHaveBeenCalled(); });

      triggerError();

      await expect(resultPromise).rejects.toThrow();
    });

    it('should reject on timeout', async () => {
      const { MockWebSocket } = createMockWebSocketClass({}, { skipProtocol: true });
      vi.stubGlobal('WebSocket', MockWebSocket);

      await expect(
        service.publishWithResponse('chat/', { action: 'test' }, 100),
      ).rejects.toThrow('timed out');
    });

    it('should call getToken for authentication', async () => {
      const localGetToken = vi.fn().mockResolvedValue('local-token');
      const localService = new AppSyncEventsService({
        endpoint,
        getToken: localGetToken,
      });

      const responseBody = { ok: true };
      const { MockWebSocket, triggerData } = createMockWebSocketClass(responseBody);
      vi.stubGlobal('WebSocket', MockWebSocket);

      const mockFetch = createMockFetch();
      vi.stubGlobal('fetch', mockFetch);

      const resultPromise = localService.publishWithResponse('chat/', { action: 'test' });

      await vi.waitFor(() => { expect(mockFetch).toHaveBeenCalled(); });

      triggerData();
      await resultPromise;

      expect(localGetToken).toHaveBeenCalled();
    });
  });
});
