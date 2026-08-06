import type { SubscriptionCallbacks, Subscription } from '@/app/types/appSyncEvents';
import { validateEvent } from '@/app/services/eventValidator';

export interface AppSyncEventsServiceConfig {
  endpoint: string;
  getToken: () => Promise<string>;
}

export interface PublishAcknowledgment {
  successful: Array<{ identifier: string; index: number }>;
  failed: Array<unknown>;
}

export class AppSyncEventsService {
  private endpoint: string;
  private getToken: () => Promise<string>;
  private ws: WebSocket | null = null;

  constructor(config: AppSyncEventsServiceConfig) {
    this.endpoint = config.endpoint;
    this.getToken = config.getToken;
  }

  /**
   * Publish an event to the given channel via HTTP POST.
   * Wraps the payload in the AppSync Events envelope format.
   * Returns the publish acknowledgment containing event identifiers.
   */
  async publish(channel: string, payload: Record<string, unknown>): Promise<PublishAcknowledgment> {
    const token = await this.getToken();
    // endpoint should already end with /event (e.g. https://xxx.appsync-api.region.amazonaws.com/event)
    const url = this.endpoint.endsWith('/event') ? this.endpoint : this.endpoint + '/event';

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: token,
      },
      body: JSON.stringify({
        channel,
        events: [JSON.stringify(payload)],
      }),
    });

    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error('Publish failed: ' + response.status + ' ' + errorBody);
    }

    return response.json();
  }

  /**
   * Publish an event and wait for the response via WebSocket subscription.
   *
   * AppSync Events REQUEST_RESPONSE channels broadcast the Lambda response
   * to subscribers, not in the HTTP response. This method:
   * 1. Opens a temporary WebSocket and subscribes to the channel
   * 2. Publishes the event via HTTP POST
   * 3. Waits for the first data event on the subscription
   * 4. Cleans up the WebSocket and returns the parsed response
   *
   * @param channel - The channel to subscribe to and publish on
   * @param payload - The event payload to publish
   * @param timeoutMs - Timeout in milliseconds (default: 15000)
   */
  async publishWithResponse(
    channel: string,
    payload: Record<string, unknown>,
    timeoutMs = 15000,
  ): Promise<unknown> {
    const token = await this.getToken();

    // Build the realtime URL
    const realtimeUrl = this.endpoint
      .replace('https://', 'wss://')
      .replace('appsync-api', 'appsync-realtime-api')
      .replace('/event', '/event/realtime');

    const httpHost = new URL(this.endpoint).host;
    const headerEncoded = AppSyncEventsService.base64UrlEncode({
      host: httpHost,
      Authorization: token,
    });

    const wsUrl = `${realtimeUrl}?header=${headerEncoded}&payload=e30=`;

    return new Promise<unknown>((resolve, reject) => {
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | null = null;

      const ws = new WebSocket(wsUrl, [
        'aws-appsync-event-ws',
        `header-${headerEncoded}`,
      ]);

      const cleanup = () => {
        if (timer) clearTimeout(timer);
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      };

      const settle = (fn: () => void) => {
        if (settled) return;
        settled = true;
        fn();
        cleanup();
      };

      timer = setTimeout(() => {
        settle(() => reject(new Error('publishWithResponse timed out after ' + timeoutMs + 'ms')));
      }, timeoutMs);

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'connection_init' }));
      };

      ws.onmessage = async (frame) => {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(frame.data as string);
        } catch {
          return;
        }

        switch (data.type) {
          case 'connection_ack': {
            // Subscribe to the channel
            const subscribeId = crypto.randomUUID();
            ws.send(
              JSON.stringify({
                type: 'subscribe',
                id: subscribeId,
                channel,
                authorization: { Authorization: token },
              }),
            );
            break;
          }

          case 'subscribe_success': {
            // Now publish the event via HTTP
            try {
              await this.publish(channel, payload);
            } catch (err) {
              settle(() => reject(err));
            }
            break;
          }

          case 'data': {
            // This is an event broadcast to subscribers.
            let event: unknown;
            try {
              event = typeof data.event === 'string' ? JSON.parse(data.event) : data.event;
            } catch {
              return; // Ignore malformed events, wait for a valid one
            }

            console.log('[publishWithResponse] Received data event:', JSON.stringify(event).substring(0, 500));

            // Skip echoed request events — they contain the 'action' field we published
            // but NOT response fields like 'conversations', 'messages', 'conversation_id', 'statusCode', 'deleted'
            const evt = event as Record<string, unknown>;
            const isEchoedRequest =
              evt &&
              typeof evt === 'object' &&
              'action' in evt &&
              !('conversations' in evt) &&
              !('messages' in evt) &&
              !('conversation_id' in evt) &&
              !('statusCode' in evt) &&
              !('deleted' in evt);

            if (isEchoedRequest) {
              console.log('[publishWithResponse] Skipping echoed request event with action:', evt.action);
              return;
            }

            settle(() => resolve(event));
            break;
          }

          case 'error': {
            settle(() => reject(new Error(JSON.stringify(data.errors))));
            break;
          }

          // Ignore ka (keep-alive) and other frame types
        }
      };

      ws.onerror = () => {
        settle(() => reject(new Error('WebSocket error during publishWithResponse')));
      };

      ws.onclose = () => {
        settle(() => reject(new Error('WebSocket closed before receiving response')));
      };
    });
  }

  /**
   * Encode an object as Base64URL (per AppSync Events WebSocket protocol).
   */
  private static base64UrlEncode(obj: Record<string, string>): string {
    return btoa(JSON.stringify(obj))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  }

  /**
   * Subscribe to a channel via WebSocket.
   * Returns a Promise that resolves with a Subscription after subscribe_success is received.
   */
  async subscribe(
    channel: string,
    callbacks: SubscriptionCallbacks,
  ): Promise<Subscription> {
    const token = await this.getToken();

    // Build the realtime URL: wss://xxx.appsync-realtime-api.region.amazonaws.com/event/realtime
    const realtimeUrl = this.endpoint
      .replace('https://', 'wss://')
      .replace('appsync-api', 'appsync-realtime-api')
      .replace('/event', '/event/realtime');

    // host must be the HTTP API host (not the realtime host)
    const httpHost = new URL(this.endpoint).host;

    // Base64URL-encode the auth header per AppSync Events protocol
    const headerEncoded = AppSyncEventsService.base64UrlEncode({
      host: httpHost,
      Authorization: token,
    });

    const wsUrl = `${realtimeUrl}?header=${headerEncoded}&payload=e30=`;

    return new Promise<Subscription>((resolve, reject) => {
      const ws = new WebSocket(wsUrl, [
        'aws-appsync-event-ws',
        `header-${headerEncoded}`,
      ]);
      this.ws = ws;

      const subscription: Subscription = {
        unsubscribe: () => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.close();
          }
        },
      };

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'connection_init' }));
      };

      ws.onmessage = (frame) => {
        console.log('[WS] Raw frame:', frame.data);
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(frame.data as string);
        } catch {
          console.log('[WS] Malformed JSON frame dropped:', frame.data);
          return;
        }
        console.log('[WS] Parsed:', data.type, data);

        switch (data.type) {
          case 'connection_ack': {
            const subscribeId = crypto.randomUUID();
            ws.send(
              JSON.stringify({
                type: 'subscribe',
                id: subscribeId,
                channel,
                authorization: { Authorization: token },
              }),
            );
            break;
          }

          case 'subscribe_success':
            // Subscription confirmed — resolve the promise
            resolve(subscription);
            break;

          case 'data': {
            let event: unknown;
            try {
              event = JSON.parse(data.event as string);
            } catch {
              console.log('Malformed event JSON dropped:', data.event);
              return;
            }

            const validated = validateEvent(event);
            if (validated) {
              callbacks.onEvent(validated);
            }
            break;
          }

          case 'ka':
            // Keep-alive, silently ignore
            break;

          case 'error':
            callbacks.onError(new Error(JSON.stringify(data.errors)));
            reject(new Error(JSON.stringify(data.errors)));
            break;

          default:
            // Unknown frame type, ignore
            break;
        }
      };

      ws.onerror = () => {
        callbacks.onError(new Error('WebSocket error'));
        reject(new Error('WebSocket error'));
      };

      ws.onclose = () => {
        if (callbacks.onClose) {
          callbacks.onClose();
        }
      };
    });
  }

  /**
   * Disconnect the current WebSocket connection.
   */
  disconnect(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
    this.ws = null;
  }
}
