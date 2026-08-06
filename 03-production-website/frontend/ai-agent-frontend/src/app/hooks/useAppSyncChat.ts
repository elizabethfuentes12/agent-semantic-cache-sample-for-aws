import { useState, useEffect, useRef, useCallback } from 'react';
import { AppSyncEventsService } from '@/app/services/appSyncEventsService';
import { ChatService } from '@/app/services/chatService';
import { useAuth } from '@/app/context/AuthContext';
import { useAgents } from '@/app/context/AgentContext';
import { useModels } from '@/app/context/ModelContext';
import type { AppSyncEvent, ConnectionStatus, Subscription } from '@/app/types/appSyncEvents';
import type { FileMetadata, MessageAttachment } from '@/app/services/uploadService';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  /** In-memory files for a just-sent message (rendered via object URLs). */
  files?: File[];
  /** Persisted attachments returned when reopening a conversation. */
  attachments?: MessageAttachment[];
}

export interface ChatSession {
  id: string;
  title: string;
  agentId: string;
  modelId: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

export interface UseAppSyncChatProps {
  currentChatId: string | null;
  chats: ChatSession[];
  setChats: React.Dispatch<React.SetStateAction<ChatSession[]>>;
  /**
   * Called when an agent response finishes (a `complete` event is received)
   * for a conversation. Used to trigger auto-rename after each response.
   */
  onResponseComplete?: (chatId: string) => void;
}

export interface UseAppSyncChatReturn {
  sendMessage: (chatId: string, content: string, files?: File[], fileMetadata?: FileMetadata[]) => Promise<void>;
  processingChats: Set<string>;
  unreadChats: Set<string>;
  clearUnread: (chatId: string) => void;
  connectionStatus: ConnectionStatus;
  error: string | null;
  subscribeToResponses: () => void;
}

/**
 * Converts an incoming AppSyncEvent into a Message object.
 */
export function eventToMessage(event: AppSyncEvent): Message {
  let content: string;

  switch (event.type) {
    case 'tool_call':
      content = JSON.stringify({ type: 'tool_call', tool: event.tool, toolUseId: event.toolUseId, input: event.input });
      break;
    case 'tool_result':
      content = JSON.stringify({ type: 'tool_result', tool: event.tool, toolUseId: event.toolUseId, result: event.result });
      break;
    case 'message':
      content = JSON.stringify({ type: 'message', content: event.content });
      break;
    case 'complete':
      content = JSON.stringify({ type: 'complete', answer: event.answer });
      break;
  }

  return {
    id: crypto.randomUUID(),
    role: 'assistant',
    content,
    timestamp: new Date(),
  };
}

function applyEventToChats(
  prev: ChatSession[],
  targetChatId: string,
  event: AppSyncEvent,
): ChatSession[] {
  const chat = prev.find((c) => c.id === targetChatId);
  if (!chat) return prev;

  // Merge tool_result into the matching tool_call message
  if (event.type === 'tool_result') {
    const idx = [...chat.messages].reverse().findIndex((m) => {
      if (m.role !== 'assistant') return false;
      try {
        const parsed = JSON.parse(m.content);
        if (parsed.type !== 'tool_call') return false;
        if (event.toolUseId && parsed.toolUseId) {
          return parsed.toolUseId === event.toolUseId;
        }
        return parsed.tool === event.tool && !parsed.result;
      } catch { return false; }
    });

    if (idx !== -1) {
      const actualIdx = chat.messages.length - 1 - idx;
      const existing = JSON.parse(chat.messages[actualIdx].content);
      const merged = { ...existing, result: event.result };
      const updatedMessages = [...chat.messages];
      updatedMessages[actualIdx] = {
        ...chat.messages[actualIdx],
        content: JSON.stringify(merged),
      };
      return prev.map((c) =>
        c.id === targetChatId
          ? { ...c, messages: updatedMessages, updatedAt: new Date() }
          : c,
      );
    }
  }

  const message = eventToMessage(event);
  const lastMsg = chat.messages[chat.messages.length - 1];
  if (lastMsg && lastMsg.role === 'assistant' && lastMsg.content === message.content) {
    return prev;
  }

  return prev.map((c) =>
    c.id === targetChatId
      ? { ...c, messages: [...c.messages, message], updatedAt: new Date() }
      : c,
  );
}

export function useAppSyncChat({ currentChatId, chats, setChats, onResponseComplete }: UseAppSyncChatProps): UseAppSyncChatReturn {
  const { user, getSession } = useAuth();
  const { agents } = useAgents();
  const { defaultModelId } = useModels();
  const [processingChats, setProcessingChats] = useState<Set<string>>(new Set());
  const [unreadChats, setUnreadChats] = useState<Set<string>>(new Set());
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const [error, setError] = useState<string | null>(null);

  const serviceRef = useRef<AppSyncEventsService | null>(null);
  const subscriptionsRef = useRef<Map<string, Subscription>>(new Map());
  const currentChatIdRef = useRef<string | null>(currentChatId);
  // Ref so the (memoized) subscription callback always calls the latest handler
  const onResponseCompleteRef = useRef<UseAppSyncChatProps['onResponseComplete']>(onResponseComplete);

  // Keep refs in sync so subscription callbacks can read the latest values
  useEffect(() => {
    currentChatIdRef.current = currentChatId;
  }, [currentChatId]);

  useEffect(() => {
    onResponseCompleteRef.current = onResponseComplete;
  }, [onResponseComplete]);

  const [serviceReady, setServiceReady] = useState(false);

  // Initialize the AppSync service once
  useEffect(() => {
    const endpoint = import.meta.env.VITE_APPSYNC_EVENTS_ENDPOINT;
    if (!endpoint) return;

    serviceRef.current = new AppSyncEventsService({
      endpoint,
      getToken: async () => {
        const session = await getSession();
        return session.getAccessToken().getJwtToken();
      },
    });

    setConnectionStatus('connected');
    setServiceReady(true);

    return () => {
      serviceRef.current?.disconnect();
      serviceRef.current = null;
      setServiceReady(false);
    };
  }, [getSession]);

  // Subscribe to a specific chat's response channel
  // Subscribe to a response channel.
  // subscriptionKey: unique key for tracking this subscription (chatId or eventId)
  // channel: optional explicit channel to subscribe to; defaults to /response/messages/{subscriptionKey}/*
  // targetChatId: optional chatId to route events to; defaults to subscriptionKey
  // Returns a promise that resolves when the subscription is confirmed.
  const subscribeTo = useCallback((subscriptionKey: string, channel?: string, targetChatId?: string): Promise<void> => {
    const service = serviceRef.current;
    if (!service || subscriptionsRef.current.has(subscriptionKey)) return Promise.resolve();

    const subscribeChannel = channel || `/response/messages/${subscriptionKey}/*`;
    const chatIdForEvents = (targetChatId && targetChatId !== 'current') ? targetChatId : '';

    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 5;

    const setupPromise = new Promise<void>((resolveSetup) => {
      const setup = async () => {
        try {
          setConnectionStatus('connecting');
          const sub = await service.subscribe(
            subscribeChannel,
            {
              onEvent: (event: AppSyncEvent) => {
                if (cancelled) return;
                reconnectAttempts = 0;

                // Route to the correct conversation using conversation_id from the event
                const resolvedChatId = event.conversation_id || chatIdForEvents || currentChatIdRef.current;
                if (!resolvedChatId) return;

                if (event.type === 'complete') {
                  setProcessingChats((prev) => {
                    const next = new Set(prev);
                    next.delete(resolvedChatId);
                    return next;
                  });
                  if (currentChatIdRef.current !== resolvedChatId) {
                    setUnreadChats((prev) => new Set(prev).add(resolvedChatId));
                  }
                  // Trigger auto-rename at the end of each agent response.
                  onResponseCompleteRef.current?.(resolvedChatId);
                  return;
                }

                setChats((prev) => applyEventToChats(prev, resolvedChatId, event));

                if (currentChatIdRef.current !== resolvedChatId) {
                  setUnreadChats((prev) => new Set(prev).add(resolvedChatId));
                }
              },
              onError: (err: Error) => {
                if (cancelled) return;
                setError(err.message);
                scheduleReconnect();
              },
              onClose: () => {
                if (cancelled) return;
                subscriptionsRef.current.delete(subscriptionKey);
                scheduleReconnect();
              },
            },
          );

          if (cancelled) {
            sub.unsubscribe();
            resolveSetup();
            return;
          }

          subscriptionsRef.current.set(subscriptionKey, sub);
          reconnectAttempts = 0;
          setConnectionStatus('connected');
          resolveSetup();
        } catch (err) {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : 'Subscription failed');
            scheduleReconnect();
          }
          resolveSetup(); // Resolve even on error so callers don't hang
        }
      };

      const scheduleReconnect = () => {
        if (cancelled || reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 30000);
        reconnectTimer = setTimeout(() => {
          if (!cancelled) setup();
        }, delay);
      };

      setup();
    });

    // Store cleanup function for later
    const cleanupFn = () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const sub = subscriptionsRef.current.get(subscriptionKey);
      if (sub) {
        sub.unsubscribe();
        subscriptionsRef.current.delete(subscriptionKey);
      }
    };
    // Attach cleanup to the subscription key for unmount
    void cleanupFn;

    return setupPromise;
  }, [setChats]);

  // No longer pre-subscribe by chatId — subscriptions are created after publish
  // using the event_id from the acknowledgment

  // Subscribe to the user's response channel — called by Chat.tsx after conversations load.
  const subscribeToResponses = useCallback(() => {
    if (!serviceReady || !user) return;
    subscribeTo(`response-${user.id}`, `/response/messages/${user.id}/*`);
  }, [serviceReady, user, subscribeTo]);

  // Clean up all subscriptions on unmount
  useEffect(() => {
    return () => {
      for (const [, sub] of subscriptionsRef.current) {
        sub.unsubscribe();
      }
      subscriptionsRef.current.clear();
    };
  }, []);

  const clearUnread = useCallback((chatId: string) => {
    setUnreadChats((prev) => {
      const next = new Set(prev);
      next.delete(chatId);
      return next;
    });
  }, []);

  const sendMessage = useCallback(
    async (
      chatId: string,
      content: string,
      files?: File[],
      fileMetadata?: FileMetadata[],
      options?: { agentId?: string; modelId?: string },
    ) => {
      if (!serviceRef.current || !user) return;

      setError(null);

      // If chatId is not a valid conversation_id, create a conversation first
      let effectiveChatId = chatId;
      if (!effectiveChatId || effectiveChatId.trim() === '') {
        try {
          const chatService = new ChatService(serviceRef.current);
          const created = await chatService.createConversation(user.id);
          effectiveChatId = created.conversation_id;
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Failed to create conversation');
          return;
        }
      }

      // Subscribe to the user's response channel BEFORE publishing.
      // Single subscription for all conversations — events include conversation_id for routing.
      await subscribeTo(
        `response-${user.id}`,
        `/response/messages/${user.id}/*`,
      );

      const userMessage: Message = {
        id: crypto.randomUUID(),
        role: 'user',
        content,
        timestamp: new Date(),
        files: files && files.length > 0 ? files : undefined,
      };

      // Optimistic UI update
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === effectiveChatId
            ? { ...chat, messages: [...chat.messages, userMessage], updatedAt: new Date() }
            : chat,
        ),
      );

      setProcessingChats((prev) => new Set(prev).add(effectiveChatId));

      try {
        const session = await getSession();
        const accessToken = session.getAccessToken().getJwtToken();

        // Prefer the agent/model resolved at the call site (options). The `chats`
        // closure can be stale for a just-created conversation (the optimistic
        // chat isn't in this callback's captured `chats` yet), which previously
        // caused the request to fall back to agents[0] — sending to the wrong
        // agent until the user toggled the selector.
        const currentChat = chats.find((c) => c.id === effectiveChatId);
        const modelId = options?.modelId ?? currentChat?.modelId ?? defaultModelId;
        const resolvedAgentId = options?.agentId ?? currentChat?.agentId;
        const agent = agents.find((a) => a.agentId === resolvedAgentId) || agents[0];

        const filesPayload = fileMetadata && fileMetadata.length > 0
          ? fileMetadata.map(m => ({
              name: m.name,
              type: m.type,
              size: m.size,
              uploadedFile: { url: m.uploadedFile.url },
            }))
          : undefined;

        const payload: Record<string, unknown> = {
          conversation_id: effectiveChatId,
          user_id: user.id,
          question: content,
          message: {
            content,
            ...(filesPayload ? { files: filesPayload } : {}),
          },
          ...(filesPayload ? { files: filesPayload } : {}),
          session_id: effectiveChatId,
          sessionId: effectiveChatId,
          userId: user.id,
          accessToken,
          agentId: agent?.agentId ?? resolvedAgentId ?? '',
          modelId,
          model_id: modelId,
          ...(agent?.target_arn ? { target_arn: agent.target_arn } : {}),
          ...(agent?.agent_arn ? { agent_arn: agent.agent_arn } : {}),
        };

        await serviceRef.current.publish(`/messages/${user.id}/${effectiveChatId}`, payload);
      } catch (err) {
        setProcessingChats((prev) => {
          const next = new Set(prev);
          next.delete(effectiveChatId);
          return next;
        });
        setError(err instanceof Error ? err.message : 'Failed to send message');
      }
    },
    [chats, user, getSession, setChats, agents, defaultModelId, subscribeTo],
  );

  return { sendMessage, processingChats, unreadChats, clearUnread, connectionStatus, error, subscribeToResponses };
}
