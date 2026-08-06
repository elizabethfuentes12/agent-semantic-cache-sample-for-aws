import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../contexts/ThemeContext';
import { useAgents } from '@/app/context/AgentContext';
import { useModels } from '@/app/context/ModelContext';
import { useAppSyncChat } from '@/app/hooks/useAppSyncChat';
import type { Message, ChatSession } from '@/app/hooks/useAppSyncChat';
import { AppSyncEventsService } from '@/app/services/appSyncEventsService';
import { ChatService, ChatServiceError, DEFAULT_CONVERSATIONS_LIMIT, DEFAULT_MESSAGES_LIMIT } from '@/app/services/chatService';
import { Button } from '../components/ui/button';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { ScrollArea } from '../components/ui/scroll-area';
import { Skeleton } from '../components/ui/skeleton';
import { LogOut, Send, Paperclip, X, Bot, User as UserIcon, Plus, Trash2, RotateCcw, RefreshCw, Moon, Sun, MoreVertical, Menu, Sparkles, Download } from 'lucide-react';
import { toast } from 'sonner';
import { MessageRenderer } from '../components/MessageRenderer';
import { CopyFormatButton } from '../components/CopyFormatButton';
import { Avatar, AvatarFallback } from '../components/ui/avatar';
import { FileThumbnail } from '../components/FileThumbnail';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '../components/ui/alert-dialog';
import { UploadService, type UploadTask, type FileMetadata, type MessageAttachment } from '@/app/services/uploadService';
import { validateFile, classifyFile, type SessionFileCounts } from '@/app/services/fileValidation';
import { getUploadConfig } from '@/app/config/uploadConfig';
import { getCognitoConfig } from '@/app/config/cognitoConfig';
import { useIsMobile } from '@/app/components/ui/use-mobile';
import { Sheet, SheetContent, SheetTitle } from '@/app/components/ui/sheet';

/**
 * Merges tool_result messages into their matching tool_call messages by toolUseId,
 * and deduplicates when the same text appears as both a 'complete' and 'message' event.
 */
function mergeToolResults(messages: Message[]): Message[] {
  // First pass: collect all assistant text content to detect duplicates
  const contentCount = new Map<string, number>();
  for (const msg of messages) {
    try {
      const parsed = JSON.parse(msg.content);
      const text = parsed.type === 'complete' ? parsed.answer
                 : parsed.type === 'message' ? parsed.content
                 : null;
      if (text) {
        contentCount.set(text, (contentCount.get(text) || 0) + 1);
      }
    } catch { /* not JSON */ }
  }

  // Second pass: merge tool results and skip duplicate 'message' events
  const result: Message[] = [];
  const toolCallMap = new Map<string, number>();
  const emittedContent = new Set<string>();

  for (const msg of messages) {
    try {
      const parsed = JSON.parse(msg.content);

      if (parsed.type === 'tool_call' && parsed.toolUseId) {
        result.push(msg);
        toolCallMap.set(parsed.toolUseId, result.length - 1);
        continue;
      }

      if (parsed.type === 'tool_result' && parsed.toolUseId) {
        const callIdx = toolCallMap.get(parsed.toolUseId);
        if (callIdx !== undefined) {
          const callMsg = result[callIdx];
          const callParsed = JSON.parse(callMsg.content);
          callParsed.result = parsed.result;
          result[callIdx] = { ...callMsg, content: JSON.stringify(callParsed) };
          continue;
        }
      }

      // Dedup: if the same text appears as both 'complete' and 'message', keep only 'complete'
      if (parsed.type === 'complete' && parsed.answer) {
        if (emittedContent.has(parsed.answer)) continue;
        emittedContent.add(parsed.answer);
        result.push(msg);
        continue;
      }

      if (parsed.type === 'message' && parsed.content) {
        // Skip if this content is duplicated and already emitted as 'complete'
        if ((contentCount.get(parsed.content) || 0) > 1 && emittedContent.has(parsed.content)) continue;
        emittedContent.add(parsed.content);
        // Skip if a 'complete' with the same content exists (it will be emitted instead)
        if ((contentCount.get(parsed.content) || 0) > 1) continue;
        result.push(msg);
        continue;
      }
    } catch { /* not JSON — pass through */ }

    result.push(msg);
  }

  return result;
}

/**
 * Formats a conversation date for display in the sidebar.
 * Shows "Today", "Yesterday", or a locale-formatted date for older dates.
 */
export function formatConversationDate(date: Date): string {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const dateOnly = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (dateOnly.getTime() === today.getTime()) {
    return 'Today';
  }
  if (dateOnly.getTime() === yesterday.getTime()) {
    return 'Yesterday';
  }
  return date.toLocaleDateString();
}

/**
 * Returns a descriptive error message based on the ChatServiceError statusCode.
 * Falls back to the error's own message or a generic message for unknown errors.
 */
export function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ChatServiceError) {
    switch (err.statusCode) {
      case 400:
        return 'Invalid request parameters';
      case 404:
        return 'Conversation not found';
      case 500:
        return 'Server error, please try again';
      default:
        return err.message || fallback;
    }
  }
  if (err instanceof Error) {
    return err.message;
  }
  return fallback;
}

/**
 * Removes conversations without a valid id and collapses duplicates by id.
 * Corrupt entries (missing conversation_id) and duplicates produce React
 * "same key null/duplicate" warnings and, worse, make list reconciliation
 * drop or duplicate rows — which breaks deletion (the wrong row is removed).
 */
export function sanitizeChats(list: ChatSession[]): ChatSession[] {
  const byId = new Map<string, ChatSession>();
  for (const chat of list) {
    if (!chat.id) continue; // drop null/empty ids
    if (!byId.has(chat.id)) byId.set(chat.id, chat);
  }
  return Array.from(byId.values());
}

export function Chat() {
  const { user, logout, getSession } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { agents, loading: agentsLoading } = useAgents();
  const { models, defaultModelId } = useModels();
  const navigate = useNavigate();
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [currentChatId, setCurrentChatId] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [uploadTasks, setUploadTasks] = useState<UploadTask[]>([]);
  const [downloadingAttachmentUrl, setDownloadingAttachmentUrl] = useState<string | null>(null);
  const [sessionFileCounts, setSessionFileCounts] = useState<SessionFileCounts>({ images: 0, documents: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [chatToDelete, setChatToDelete] = useState<string | null>(null);
  const [renamingChatId, setRenamingChatId] = useState<string | null>(null);
  const isMobile = useIsMobile();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [defaultAgentId, setDefaultAgentId] = useState<string>('');

  // Initialize default agent when agents load
  useEffect(() => {
    if (agents.length > 0 && !defaultAgentId) {
      setDefaultAgentId(agents[0].agentId);
    }
  }, [agents, defaultAgentId]);
  const [isLoadingConversations, setIsLoadingConversations] = useState(false);
  const [loadConversationsError, setLoadConversationsError] = useState<string | null>(null);
  const [conversationsNextToken, setConversationsNextToken] = useState<string | null>(null);
  const [isLoadingMoreConversations, setIsLoadingMoreConversations] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const hasLoadedConversationsRef = useRef(false);
  const [loadMessagesError, setLoadMessagesError] = useState<string | null>(null);
  const [messagesNextToken, setMessagesNextToken] = useState<string | null>(null);
  const [isLoadingMoreMessages, setIsLoadingMoreMessages] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);

  // Create AppSyncEventsService and ChatService instances for backend operations
  const chatService = useMemo(() => {
    const endpoint = import.meta.env.VITE_APPSYNC_EVENTS_ENDPOINT;
    if (!endpoint) return null;

    const appSyncService = new AppSyncEventsService({
      endpoint,
      getToken: async () => {
        const session = await getSession();
        return session.getAccessToken().getJwtToken();
      },
    });

    return new ChatService(appSyncService);
  }, [getSession]);

  const uploadService = useMemo(() => {
    try {
      const uploadConfig = getUploadConfig();
      const cognitoConfig = getCognitoConfig();
      return new UploadService({
        region: uploadConfig.region,
        identityPoolId: uploadConfig.identityPoolId,
        bucket: uploadConfig.uploadBucket,
        userPoolId: cognitoConfig.userPoolId,
        getIdToken: async () => {
          const session = await getSession();
          return session.getIdToken().getJwtToken();
        },
      });
    } catch {
      console.error('Upload service configuration missing — file uploads disabled');
      return null;
    }
  }, [getSession]);

  // Tracks conversations with an in-flight rename to avoid overlapping calls.
  const autoRenamingRef = useRef<Set<string>>(new Set());

  // Shared auto-rename routine. `silent` mode (used after each agent response)
  // updates the title without toasts or the dropdown spinner.
  const runAutoRename = useCallback(
    async (chatId: string, opts?: { silent?: boolean }) => {
      const silent = opts?.silent ?? false;
      if (!chatService || !user || !chatId) return;
      if (autoRenamingRef.current.has(chatId)) return;

      autoRenamingRef.current.add(chatId);
      if (!silent) setRenamingChatId(chatId);
      try {
        const response = await chatService.autoRenameConversation(user.id, chatId);
        setChats(prev =>
          prev.map(c => (c.id === chatId ? { ...c, title: response.title } : c)),
        );
        if (!silent) toast.success('Conversación renombrada');
      } catch (err) {
        if (!silent) {
          toast.error(getErrorMessage(err, 'Error al auto-renombrar la conversación'));
        } else {
          console.warn('[autoRename] silent rename skipped/failed', err);
        }
      } finally {
        autoRenamingRef.current.delete(chatId);
        if (!silent) setRenamingChatId(null);
      }
    },
    [chatService, user, setChats],
  );

  const { sendMessage, processingChats, unreadChats, clearUnread, connectionStatus, error, subscribeToResponses } = useAppSyncChat({
    currentChatId,
    chats,
    setChats,
    onResponseComplete: (chatId: string) => { void runAutoRename(chatId, { silent: true }); },
  });

  // Load conversations from backend on mount
  const loadConversations = useCallback(async () => {
    if (!user || !chatService) return;
    // Wait for agents to be loaded before fetching conversations
    if (agents.length === 0) return;
    // Only load once on initial mount
    if (hasLoadedConversationsRef.current) return;
    hasLoadedConversationsRef.current = true;

    setIsLoadingConversations(true);
    setLoadConversationsError(null);

    try {
      const response = await chatService.listConversations(user.id);

      // Convert UTC dates to local Date objects and map to ChatSession
      // Match agent_arn from backend to the agent list to set the correct agentId
      const loadedChats: ChatSession[] = response.conversations.map((conv) => {
        const matchedAgent = conv.agent_arn
          ? agents.find(a => a.agent_arn === conv.agent_arn)
          : undefined;
        return {
          id: conv.conversation_id,
          title: conv.title,
          agentId: matchedAgent?.agentId || agents[0]?.agentId || '',
          modelId: conv.model_id || defaultModelId,
          messages: [],
          createdAt: new Date(conv.created_at),
          updatedAt: new Date(conv.updated_at),
        };
      });

      // Drop corrupt/duplicate entries, then sort by updated_at descending.
      const cleanChats = sanitizeChats(loadedChats);
      cleanChats.sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime());

      setChats(cleanChats);
      setConversationsNextToken(response.next_token);

      // Subscribe to response channel now that chats are loaded
      subscribeToResponses();

      // Select the most recent conversation as active
      if (cleanChats.length > 0) {
        setCurrentChatId(cleanChats[0].id);
      }
    } catch (err) {
      const message = getErrorMessage(err, 'Error al cargar conversaciones');
      setLoadConversationsError(message);
      toast.error(message);
      // Allow retry on error
      hasLoadedConversationsRef.current = false;
    } finally {
      setIsLoadingConversations(false);
    }
  }, [user, chatService, agents, defaultModelId, subscribeToResponses]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Load more conversations (pagination)
  const loadMoreConversations = useCallback(async () => {
    if (!user || !chatService || !conversationsNextToken) return;

    setIsLoadingMoreConversations(true);

    try {
      const response = await chatService.listConversations(user.id, DEFAULT_CONVERSATIONS_LIMIT, conversationsNextToken);

      const newChats: ChatSession[] = response.conversations.map((conv) => {
        const matchedAgent = conv.agent_arn
          ? agents.find(a => a.agent_arn === conv.agent_arn)
          : undefined;
        return {
          id: conv.conversation_id,
          title: conv.title,
          agentId: matchedAgent?.agentId || agents[0]?.agentId || '',
          modelId: conv.model_id || defaultModelId,
          messages: [],
          createdAt: new Date(conv.created_at),
          updatedAt: new Date(conv.updated_at),
        };
      });

      // Accumulate with existing chats, dedupe by id, then re-sort by updatedAt.
      setChats(prev => {
        const combined = sanitizeChats([...prev, ...newChats]);
        combined.sort((a, b) => b.updatedAt.getTime() - a.updatedAt.getTime());
        return combined;
      });

      setConversationsNextToken(response.next_token);
    } catch (err) {
      const message = getErrorMessage(err, 'Error al cargar más conversaciones');
      toast.error(message);
    } finally {
      setIsLoadingMoreConversations(false);
    }
  }, [user, chatService, conversationsNextToken, agents, defaultModelId]);

  // Load messages for a conversation from the backend
  const loadMessages = useCallback(async (conversationId: string) => {
    if (!user || !chatService) return;

    setIsLoadingMessages(true);
    setLoadMessagesError(null);

    try {
      const response = await chatService.getMessages(user.id, conversationId);

      // Convert backend messages to frontend Message type with local dates
      // Backend roles: user, assistant, tool_call, tool_result, message
      // tool_call/tool_result/message content is already JSON for MessageRenderer
      // assistant content is plain text — wrap in {type: "complete", answer: "..."}
      const rawMessages: Message[] = response.messages.map((msg) => {
        let content = msg.content;
        let role: 'user' | 'assistant' = 'assistant';

        switch (msg.role) {
          case 'user':
            role = 'user';
            break;
          case 'assistant':
            content = JSON.stringify({ type: 'complete', answer: msg.content });
            break;
          case 'tool_call':
          case 'tool_result':
          case 'message':
            // Content is already JSON — pass through as-is
            break;
        }

        return {
          id: crypto.randomUUID(),
          role,
          content,
          timestamp: new Date(msg.created_at),
          ...(msg.attachments && msg.attachments.length > 0
            ? { attachments: msg.attachments }
            : {}),
        };
      });

      // Merge tool_result into matching tool_call by toolUseId
      const loadedMessages = mergeToolResults(rawMessages);

      // Update the chat's messages and agent/model from get_messages response
      setChats(prev =>
        prev.map(chat => {
          if (chat.id !== conversationId) return chat;
          const updates: Partial<ChatSession> = { messages: loadedMessages };
          // Update agent/model if provided by backend
          if (response.agent_arn) {
            const matchedAgent = agents.find(a => a.agent_arn === response.agent_arn);
            if (matchedAgent) updates.agentId = matchedAgent.agentId;
          }
          if (response.model_id) {
            updates.modelId = response.model_id;
          }
          return { ...chat, ...updates };
        }),
      );

      setMessagesNextToken(response.next_token);
    } catch (err) {
      const message = getErrorMessage(err, 'Error al cargar mensajes');
      setLoadMessagesError(message);
    } finally {
      setIsLoadingMessages(false);
    }
  }, [user, chatService, setChats]);

  // Load more (older) messages for the current conversation (pagination)
  const loadMoreMessages = useCallback(async () => {
    if (!user || !chatService || !currentChatId || !messagesNextToken) return;

    setIsLoadingMoreMessages(true);

    try {
      const response = await chatService.getMessages(user.id, currentChatId, DEFAULT_MESSAGES_LIMIT, messagesNextToken);

      const rawOlderMessages: Message[] = response.messages.map((msg) => {
        let content = msg.content;
        let role: 'user' | 'assistant' = 'assistant';

        switch (msg.role) {
          case 'user':
            role = 'user';
            break;
          case 'assistant':
            content = JSON.stringify({ type: 'complete', answer: msg.content });
            break;
          case 'tool_call':
          case 'tool_result':
          case 'message':
            break;
        }

        return {
          id: crypto.randomUUID(),
          role,
          content,
          timestamp: new Date(msg.created_at),
          ...(msg.attachments && msg.attachments.length > 0
            ? { attachments: msg.attachments }
            : {}),
        };
      });

      // Merge tool_result into matching tool_call by toolUseId
      const olderMessages = mergeToolResults(rawOlderMessages);

      // Prepend older messages before existing ones
      setChats(prev =>
        prev.map(chat =>
          chat.id === currentChatId
            ? { ...chat, messages: [...olderMessages, ...chat.messages] }
            : chat,
        ),
      );

      setMessagesNextToken(response.next_token);
    } catch (err) {
      const message = getErrorMessage(err, 'Error al cargar mensajes anteriores');
      toast.error(message);
    } finally {
      setIsLoadingMoreMessages(false);
    }
  }, [user, chatService, currentChatId, messagesNextToken, setChats]);

  // Load messages when currentChatId changes (only if not already loaded)
  useEffect(() => {
    if (!currentChatId) return;

    // Use functional state access to avoid stale closure on chats
    setChats(prev => {
      const chat = prev.find(c => c.id === currentChatId);
      if (chat && chat.messages.length === 0) {
        loadMessages(currentChatId);
      }
      return prev; // No state change, just reading
    });
  }, [currentChatId, loadMessages]);

  const currentChat = chats.find(chat => chat.id === currentChatId);
  const messages = currentChat?.messages || [];
  const selectedAgent = currentChat?.agentId || defaultAgentId || agents[0]?.agentId || '';
  const selectedModel = currentChat?.modelId || defaultModelId;
  const isCurrentChatProcessing = currentChatId ? processingChats.has(currentChatId) : false;

  // Show error from the hook as a toast
  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!user) {
      navigate('/login');
    }
  }, [user, navigate]);

  // Auto-scroll to bottom within the ScrollArea viewport
  useEffect(() => {
    const viewport = scrollAreaRef.current?.querySelector('[data-slot="scroll-area-viewport"]');
    if (viewport) {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: 'smooth' });
    }
  }, [messages]);

  const createNewChat = () => {
    // Start a fresh chat locally only. The backend conversation is created
    // lazily when the first message is sent (see handleSendMessage), so
    // clicking "New Chat" never persists empty/zombie conversations.
    setCurrentChatId(null);
    setInputValue('');
    setUploadTasks([]);
    setSessionFileCounts({ images: 0, documents: 0 });
    setLoadMessagesError(null);
    setMessagesNextToken(null);
    if (isMobile) setSidebarOpen(false);
  };

  const confirmDeleteChat = (chatId: string) => {
    setChatToDelete(chatId);
    setDeleteDialogOpen(true);
  };

  const deleteChat = () => {
    if (!chatToDelete) return;

    const idToDelete = chatToDelete;
    const wasActive = currentChatId === idToDelete;

    // Optimistic: remove the chat from state immediately
    setChats(prev => prev.filter(chat => chat.id !== idToDelete));

    // If it was the active chat, select the next available one
    if (wasActive) {
      const remaining = chats.filter(chat => chat.id !== idToDelete);
      setCurrentChatId(remaining.length > 0 ? remaining[0].id : null);
    }

    setDeleteDialogOpen(false);
    setChatToDelete(null);

    // Persist deletion to backend. Fire the call whenever we have a session —
    // we do NOT gate it on the chat still being present in local state.
    // Deletion is idempotent on the backend, so we don't re-insert on error
    // (that is what produced "zombie" conversations); we only warn.
    if (chatService && user) {
      console.info('[deleteChat] Deleting conversation on backend', idToDelete);
      chatService.deleteConversation(user.id, idToDelete)
        .then(() => console.info('[deleteChat] Backend deletion request sent', idToDelete))
        .catch((err) => {
          console.warn('[deleteChat] Backend deletion reported an error', err);
          toast.warning(
            'No se pudo confirmar el borrado. Si la conversación reaparece al recargar, inténtalo de nuevo.',
          );
        });
    } else {
      console.warn('[deleteChat] No chatService/user — backend deletion NOT called');
    }
  };

  const clearCurrentChat = () => {
    if (!currentChatId) return;
    
    setChats(prev => prev.map(chat => 
      chat.id === currentChatId 
        ? { ...chat, messages: [], updatedAt: new Date() }
        : chat
    ));
    setClearDialogOpen(false);
    toast.success('Chat cleared');
  };

  const switchChat = (chatId: string) => {
    setCurrentChatId(chatId);
    clearUnread(chatId);
    setUploadTasks([]);
    setSessionFileCounts({ images: 0, documents: 0 });
    setInputValue('');
    setLoadMessagesError(null);
    setMessagesNextToken(null);
    if (isMobile) setSidebarOpen(false);
  };

  const updateChatTitle = (chatId: string, firstMessage: string) => {
    const trimmed = firstMessage.trim();
    // Fall back to a default so a conversation never ends up with an empty
    // title (which renders as a blank "zombie" row showing only the date).
    const title = trimmed
      ? trimmed.slice(0, 50) + (trimmed.length > 50 ? '...' : '')
      : 'Nueva conversación';

    // Save previous title for rollback
    const previousTitle = chats.find(c => c.id === chatId)?.title ?? 'New Chat';

    // Optimistic update
    setChats(prev => prev.map(chat => 
      chat.id === chatId ? { ...chat, title } : chat
    ));

    // Persist to backend in the background
    if (chatService && user) {
      chatService.updateConversation(user.id, chatId, title).catch((err) => {
        // Rollback: restore previous title
        setChats(prev => prev.map(chat =>
          chat.id === chatId ? { ...chat, title: previousTitle } : chat
        ));
        toast.error(getErrorMessage(err, 'Error al actualizar el título de la conversación'));
      });
    }
  };

  // Manual auto-rename (from the conversation dropdown) — shows toasts/spinner.
  // Not gated on locally-loaded messages: an unselected conversation has
  // messages=[] until opened, so a local check would wrongly block it. The
  // backend validates the dialogue and returns 400 if there is nothing to name.
  const handleAutoRename = (chatId: string) => {
    void runAutoRename(chatId, { silent: false });
  };



  const regenerateLastResponse = async () => {
    if (!currentChatId || messages.length < 2) return;
    
    // Find the last user message
    const lastUserMessageIndex = messages.map((m, i) => ({ ...m, index: i }))
      .filter(m => m.role === 'user')
      .pop();
    
    if (!lastUserMessageIndex) return;

    // Remove all messages after the last user message
    const messagesUpToUser = messages.slice(0, lastUserMessageIndex.index + 1);
    setChats(prev => prev.map(chat => 
      chat.id === currentChatId 
        ? { ...chat, messages: messagesUpToUser, updatedAt: new Date() }
        : chat
    ));

    // Re-send the last user message via the hook
    const lastUserContent = messagesUpToUser[messagesUpToUser.length - 1]?.content;
    if (lastUserContent) {
      toast.info('Regenerating response...');
      await sendMessage(currentChatId, lastUserContent);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
    toast.success('Logged out successfully');
  };

  // Ensures a backend conversation exists and returns its id. Mirrors the lazy
  // creation in handleSendMessage so features that need a real conversation id
  // (file uploads, sending) share one code path. Returns null on failure.
  const ensureConversation = async (): Promise<string | null> => {
    if (currentChatId) return currentChatId;

    if (!chatService || !user) {
      toast.error('Unable to create conversation — not connected');
      return null;
    }

    // Show optimistic chat while the backend creates the conversation.
    const tempId = crypto.randomUUID();
    const optimisticChat: ChatSession = {
      id: tempId,
      title: 'New Chat',
      agentId: selectedAgent,
      modelId: selectedModel,
      messages: [],
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setChats(prev => [optimisticChat, ...prev]);
    setCurrentChatId(tempId);

    try {
      const response = await chatService.createConversation(user.id);
      setChats(prev =>
        prev.map(chat =>
          chat.id === tempId
            ? {
                ...chat,
                id: response.conversation_id,
                title: response.title,
                createdAt: new Date(response.created_at),
                updatedAt: new Date(response.updated_at),
              }
            : chat,
        ),
      );
      setCurrentChatId(response.conversation_id);
      return response.conversation_id;
    } catch (err) {
      // Rollback: remove the optimistic chat.
      setChats(prev => prev.filter(chat => chat.id !== tempId));
      setCurrentChatId(null);
      toast.error(getErrorMessage(err, 'Error al crear conversación'));
      return null;
    }
  };

  // Re-downloads a persisted attachment from a historical message. The bucket
  // is private, so we fetch through the S3 client (Cognito creds) rather than
  // linking directly to the object URL.
  const handleDownloadAttachment = async (attachment: MessageAttachment) => {
    if (!uploadService) {
      toast.error('La descarga de archivos no está configurada');
      return;
    }
    if (downloadingAttachmentUrl) return; // avoid parallel downloads spam
    setDownloadingAttachmentUrl(attachment.url);
    try {
      await uploadService.download(attachment.url, attachment.name);
    } catch (err) {
      toast.error(getErrorMessage(err, `No se pudo descargar ${attachment.name}`));
    } finally {
      setDownloadingAttachmentUrl(null);
    }
  };

  const processFiles = async (filesToProcess: File[]) => {
    if (!uploadService) {
      toast.error('File upload is not configured');
      return;
    }
    if (!user) {
      toast.error('Please sign in before attaching files');
      return;
    }

    // Lazily create the conversation so attaching a file to a brand-new chat
    // works without first sending a message.
    const chatId = await ensureConversation();
    if (!chatId) return;

    let currentCounts = { ...sessionFileCounts };

    for (const file of filesToProcess) {
      const validation = validateFile(file, currentCounts);
      if (!validation.valid) {
        toast.error(validation.error ?? 'Invalid file');
        continue;
      }

      // Update session counts
      const fileType = classifyFile(file.type, file.name);
      if (fileType === 'image') {
        currentCounts = { ...currentCounts, images: currentCounts.images + 1 };
      } else if (fileType === 'document') {
        currentCounts = { ...currentCounts, documents: currentCounts.documents + 1 };
      }

      // Create AbortController for this upload
      const abortController = new AbortController();

      // Create the initial upload task
      const newTask: UploadTask = {
        file,
        status: 'pending',
        progress: 0,
        abort: () => abortController.abort(),
      };

      setUploadTasks(prev => [...prev, newTask]);

      // Start upload immediately
      const userId = user.id;

      // Use a self-invoking async to kick off the upload
      (async () => {
        // Update status to uploading
        setUploadTasks(prev =>
          prev.map(t => t.file === file ? { ...t, status: 'uploading' as const } : t)
        );

        try {
          const metadata = await uploadService.upload(
            file,
            userId,
            chatId,
            (pct: number) => {
              setUploadTasks(prev =>
                prev.map(t => t.file === file ? { ...t, progress: pct } : t)
              );
            },
            abortController.signal,
          );

          setUploadTasks(prev =>
            prev.map(t =>
              t.file === file
                ? { ...t, status: 'success' as const, progress: 100, metadata }
                : t
            )
          );
        } catch (err: unknown) {
          // Don't show error for aborted uploads
          if (err instanceof DOMException && err.name === 'AbortError') return;
          const errorMessage = err instanceof Error ? err.message : 'Upload failed';
          setUploadTasks(prev =>
            prev.map(t =>
              t.file === file
                ? { ...t, status: 'error' as const, error: errorMessage }
                : t
            )
          );
        }
      })();
    }

    setSessionFileCounts(currentCounts);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(e.target.files || []);
    if (selectedFiles.length > 0) {
      processFiles(selectedFiles);
    }
    // Reset input so the same file can be re-selected
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const removeFile = (index: number) => {
    const task = uploadTasks[index];
    if (task && (task.status === 'pending' || task.status === 'uploading')) {
      task.abort();
      toast.info(`Upload cancelled: ${task.file.name}`);
    }
    setUploadTasks(prev => prev.filter((_, i) => i !== index));
  };

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (dropZoneRef.current && !dropZoneRef.current.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const droppedFiles = Array.from(e.dataTransfer.files);
    if (droppedFiles.length > 0) {
      processFiles(droppedFiles);
    }
  };

  const changeAgent = (agentId: string) => {
    setDefaultAgentId(agentId);
    if (currentChatId) {
      setChats(prev => prev.map(chat =>
        chat.id === currentChatId ? { ...chat, agentId } : chat
      ));
    }
  };

  const changeModel = (modelId: string) => {
    if (currentChatId) {
      setChats(prev => prev.map(chat =>
        chat.id === currentChatId ? { ...chat, modelId, updatedAt: new Date() } : chat
      ));
    }
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim() && uploadTasks.length === 0) {
      toast.error('Please enter a message or attach a file');
      return;
    }

    // Create the backend conversation lazily if none exists yet. A file attach
    // may have already created it, in which case this returns the existing id.
    const chatId = await ensureConversation();
    if (!chatId) return;

    // Update title if this is the first message in the chat
    const chat = chats.find(c => c.id === chatId);
    if (chat && chat.messages.length === 0) {
      updateChatTitle(chatId, inputValue);
    }

    const content = inputValue;
    // Extract File objects from uploadTasks for the message.files field
    const currentFiles = uploadTasks.length > 0
      ? uploadTasks.map(t => t.file)
      : undefined;

    // Extract FileMetadata from completed upload tasks for the payload
    const completedMetadata = uploadTasks
      .filter(t => t.status === 'success' && t.metadata)
      .map(t => t.metadata!);

    setInputValue('');
    setUploadTasks([]);

    await sendMessage(
      chatId,
      content,
      currentFiles,
      completedMetadata.length > 0 ? completedMetadata : undefined,
      { agentId: selectedAgent, modelId: selectedModel },
    );
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  if (!user) {
    return null;
  }

  const selectedAgentInfo = agents.find(a => a.agentId === selectedAgent);

  const connectionStatusIndicator = () => {
    switch (connectionStatus) {
      case 'connected':
        return (
          <>
            <div className="w-2 h-2 bg-green-500 rounded-full"></div>
            Connected
          </>
        );
      case 'connecting':
        return (
          <>
            <div className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse"></div>
            Connecting...
          </>
        );
      case 'disconnected':
        return (
          <>
            <div className="w-2 h-2 bg-gray-400 rounded-full"></div>
            Disconnected
          </>
        );
      case 'error':
        return (
          <>
            <div className="w-2 h-2 bg-red-500 rounded-full"></div>
            Connection Error
          </>
        );
    }
  };

  const sidebarContent = (
    <>
      <div className="p-3 border-b shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-primary" />
            <span className="font-semibold text-sm">AI Agents</span>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={createNewChat}
              title="New Chat"
            >
              <Plus className="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
            >
              {theme === 'light' ? (
                <Moon className="w-4 h-4" />
              ) : (
                <Sun className="w-4 h-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={handleLogout}
              title="Logout"
            >
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        </div>
        <div className="text-xs text-muted-foreground truncate">
          Welcome, {user.name}
        </div>
      </div>

      {/* Chat History */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2 space-y-0.5">
          <div className="sticky top-0 z-10 bg-card text-[11px] font-medium text-muted-foreground px-1 py-1 mb-1">
            Chat History
          </div>
          {isLoadingConversations ? (
            <div className="space-y-3" data-testid="conversations-loading">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-2 p-3">
                  <Skeleton className="w-6 h-6 rounded" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : loadConversationsError ? (
            <div className="text-center py-8 space-y-3" data-testid="conversations-error">
              <p className="text-sm text-destructive">{loadConversationsError}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={loadConversations}
                className="gap-2"
              >
                <RefreshCw className="w-3 h-3" />
                Reintentar
              </Button>
            </div>
          ) : chats.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-8">
              No chats yet. Start a new conversation!
            </div>
          ) : (
            chats.map(chat => {
              const isChatProcessing = processingChats.has(chat.id);
              const hasUnread = unreadChats.has(chat.id);
              return (
              <div
                key={chat.id}
                className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors overflow-hidden ${
                  currentChatId === chat.id
                    ? 'bg-primary/10 border border-primary/20'
                    : 'hover:bg-muted'
                }`}
                onClick={() => switchChat(chat.id)}
              >
                <DropdownMenu>
                  <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                    <button className="flex-shrink-0 w-6 h-6 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted-foreground/10">
                      <MoreVertical className="w-3.5 h-3.5" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" side="bottom">
                    <DropdownMenuItem
                      className="cursor-pointer"
                      disabled={renamingChatId === chat.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleAutoRename(chat.id);
                      }}
                    >
                      <Sparkles className={`w-4 h-4 mr-2 ${renamingChatId === chat.id ? 'animate-pulse' : ''}`} />
                      {renamingChatId === chat.id ? 'Renombrando...' : 'Auto-renombrar'}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive focus:text-destructive cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        confirmDeleteChat(chat.id);
                      }}
                    >
                      <Trash2 className="w-4 h-4 mr-2" />
                      Delete chat
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium leading-snug break-words whitespace-normal">
                    {chat.title?.trim() ? chat.title : 'Sin título'}
                  </div>
                  <div className="text-[10px] text-muted-foreground leading-tight">
                    {formatConversationDate(chat.updatedAt)}
                  </div>
                  {isChatProcessing && (
                    <div className="mt-0.5 text-[10px] font-medium text-yellow-600 dark:text-yellow-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />
                      Agent responding...
                    </div>
                  )}
                  {hasUnread && !isChatProcessing && (
                    <div className="mt-0.5 text-[10px] font-medium text-primary flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                      New response
                    </div>
                  )}
                </div>
              </div>
              );
            })
          )}
          {conversationsNextToken && (
            <Button
              variant="ghost"
              size="sm"
              onClick={loadMoreConversations}
              disabled={isLoadingMoreConversations}
              className="w-full mt-2 gap-2"
              data-testid="load-more-conversations"
            >
              {isLoadingMoreConversations ? (
                <>
                  <div className="flex gap-1">
                    <div className="w-1.5 h-1.5 bg-foreground/40 rounded-full animate-bounce"></div>
                    <div className="w-1.5 h-1.5 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                    <div className="w-1.5 h-1.5 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  </div>
                  Cargando...
                </>
              ) : (
                'Cargar más'
              )}
            </Button>
          )}
        </div>
      </ScrollArea>

      {/* Agent Selector */}
      <div className="p-3 border-t shrink-0">
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium mb-1.5 block">
              Current Agent
            </label>
            <Select value={selectedAgent} onValueChange={changeAgent}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {agents.map(agent => (
                  <SelectItem key={agent.agentId} value={agent.agentId}>
                    <div className="flex flex-col">
                      <span>{agent.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {agent.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <div className="p-3 border-t text-xs text-muted-foreground shrink-0">
        <div className="flex items-center gap-2">
          {connectionStatusIndicator()}
        </div>
      </div>
    </>
  );

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      {!isMobile ? (
        <div className="w-80 border-r bg-card flex flex-col">
          {sidebarContent}
        </div>
      ) : (
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetContent side="left" className="flex flex-col p-0">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            {sidebarContent}
          </SheetContent>
        </Sheet>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* Chat Header */}
        <div className="p-4 border-b bg-card flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isMobile && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSidebarOpen(true)}
              >
                <Menu className="h-5 w-5" />
              </Button>
            )}
            <div>
              <h2 className="font-semibold">
                {currentChat ? currentChat.title : 'AI Agent Chat'}
              </h2>
              <p className="text-sm text-muted-foreground">
                {selectedAgentInfo ? `${selectedAgentInfo.name} - ${selectedAgentInfo.description}` : 'Select an agent to start chatting'}
              </p>
            </div>
          </div>
          {currentChat && messages.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setClearDialogOpen(true)}
              className="gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              Clear Chat
            </Button>
          )}
        </div>

        {/* Messages */}
        <ScrollArea ref={scrollAreaRef} className="flex-1 min-h-0 p-4">
          <div className="space-y-4 max-w-[95%] mx-auto">
            {/* Load older messages button (pagination) */}
            {!isLoadingMessages && !loadMessagesError && messagesNextToken && (
              <div className="flex justify-center">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={loadMoreMessages}
                  disabled={isLoadingMoreMessages}
                  className="gap-2"
                  data-testid="load-more-messages"
                >
                  {isLoadingMoreMessages ? (
                    <>
                      <div className="flex gap-1">
                        <div className="w-1.5 h-1.5 bg-foreground/40 rounded-full animate-bounce"></div>
                        <div className="w-1.5 h-1.5 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                        <div className="w-1.5 h-1.5 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                      </div>
                      Cargando...
                    </>
                  ) : (
                    'Cargar anteriores'
                  )}
                </Button>
              </div>
            )}

            {isLoadingMessages && (
              <div className="flex flex-col items-center justify-center py-12 gap-3" data-testid="messages-loading">
                <div className="flex gap-1">
                  <div className="w-2 h-2 bg-foreground/40 rounded-full animate-bounce"></div>
                  <div className="w-2 h-2 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                  <div className="w-2 h-2 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                </div>
                <p className="text-sm text-muted-foreground">Cargando mensajes...</p>
              </div>
            )}

            {!isLoadingMessages && loadMessagesError && (
              <div className="text-center py-12 space-y-3" data-testid="messages-error">
                <p className="text-sm text-destructive">{loadMessagesError}</p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => currentChatId && loadMessages(currentChatId)}
                  className="gap-2"
                >
                  <RefreshCw className="w-3 h-3" />
                  Reintentar
                </Button>
              </div>
            )}

            {!isLoadingMessages && !loadMessagesError && messages.length === 0 && (
              <div className="text-center py-12">
                <Bot className="w-12 h-12 mx-auto mb-4 text-muted-foreground" />
                <h3 className="font-medium mb-2">Start a conversation</h3>
                <p className="text-sm text-muted-foreground">
                  Send a message or upload a file to begin
                </p>
              </div>
            )}

            {!isLoadingMessages && !loadMessagesError && (() => {
              const isToolCall = (msg: Message) => {
                if (msg.role !== 'assistant') return false;
                try { return JSON.parse(msg.content).type === 'tool_call'; } catch { return false; }
              };

              const groups: Array<{ type: 'single'; message: Message; index: number } | { type: 'tool_group'; messages: Array<{ message: Message; index: number }> }> = [];
              let i = 0;
              while (i < messages.length) {
                if (isToolCall(messages[i])) {
                  const group: Array<{ message: Message; index: number }> = [];
                  while (i < messages.length && isToolCall(messages[i])) {
                    group.push({ message: messages[i], index: i });
                    i++;
                  }
                  groups.push({ type: 'tool_group', messages: group });
                } else {
                  groups.push({ type: 'single', message: messages[i], index: i });
                  i++;
                }
              }

              return groups.map((group, groupIdx) => {
                if (group.type === 'tool_group') {
                  return (
                    <div key={`tool-group-${groupIdx}`} className="flex gap-3 justify-start">
                      <Avatar className="w-8 h-8 flex-shrink-0">
                        <AvatarFallback className="bg-primary text-primary-foreground">
                          <Bot className="w-4 h-4" />
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex flex-wrap gap-1.5 max-w-[80%]">
                        {group.messages.map(({ message }) => (
                          <MessageRenderer key={message.id} content={message.content} />
                        ))}
                      </div>
                    </div>
                  );
                }

                const { message, index } = group;
                const isLastMessage = index === messages.length - 1;
                const isLastAssistantMessage = isLastMessage && message.role === 'assistant';

                return (
                <div
                  key={message.id}
                  className={`flex gap-3 group ${ 
                    message.role === 'user' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {message.role === 'assistant' && (
                    <Avatar className="w-8 h-8">
                      <AvatarFallback className="bg-primary text-primary-foreground">
                        <Bot className="w-4 h-4" />
                      </AvatarFallback>
                    </Avatar>
                  )}

                  <div
                    className={`flex flex-col gap-2 max-w-[80%] ${
                      message.role === 'user' ? 'items-end' : 'items-start'
                    }`}
                  >
                    <div className="flex items-start gap-2 w-full">
                      <div
                        className={`rounded-lg p-3 flex-1 ${
                          message.role === 'user'
                            ? 'bg-primary text-primary-foreground'
                            : 'bg-muted'
                        }`}
                      >
                        {message.role === 'user' ? (
                          <div>
                            {message.content && <div className="whitespace-pre-wrap">{message.content}</div>}
                            {message.files && message.files.length > 0 && (
                              <div className={`${message.content ? 'mt-3' : ''} flex flex-wrap gap-2`}>
                                {message.files.map((file, idx) => {
                                  const isImage = file.type.startsWith('image/');
                                  if (isImage) {
                                    const imageUrl = URL.createObjectURL(file);
                                    return (
                                      <div key={idx} className="relative max-w-xs">
                                        <img
                                          src={imageUrl}
                                          alt={file.name}
                                          className="rounded-lg max-h-64 w-auto"
                                          onLoad={() => URL.revokeObjectURL(imageUrl)}
                                        />
                                        <div className="text-xs opacity-80 mt-1">
                                          {file.name}
                                        </div>
                                      </div>
                                    );
                                  } else {
                                    return (
                                      <div key={idx} className="flex items-center gap-2 text-xs opacity-90 bg-primary-foreground/10 px-2 py-1 rounded">
                                        📎 {file.name}
                                      </div>
                                    );
                                  }
                                })}
                              </div>
                            )}
                            {message.attachments && message.attachments.length > 0 && (
                              <div className={`${message.content ? 'mt-3' : ''} flex flex-wrap gap-2`}>
                                {message.attachments.map((attachment, idx) => {
                                  const isDownloading = downloadingAttachmentUrl === attachment.url;
                                  return (
                                    <button
                                      key={idx}
                                      type="button"
                                      onClick={() => handleDownloadAttachment(attachment)}
                                      disabled={isDownloading}
                                      title={`Descargar ${attachment.name}`}
                                      className="group/att flex items-center gap-2 text-xs opacity-90 bg-primary-foreground/10 px-2 py-1 rounded hover:opacity-100 transition-opacity disabled:opacity-60 disabled:cursor-wait"
                                    >
                                      <Paperclip className="w-3 h-3 shrink-0" />
                                      <span className="max-w-[16rem] truncate">{attachment.name}</span>
                                      {isDownloading ? (
                                        <RefreshCw className="w-3 h-3 shrink-0 animate-spin" />
                                      ) : (
                                        <Download className="w-3 h-3 shrink-0 opacity-70 group-hover/att:opacity-100" />
                                      )}
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        ) : (
                          <MessageRenderer content={message.content} />
                        )}
                      </div>
                      
                      {/* Copy button */}
                      <CopyFormatButton
                        content={message.content}
                        role={message.role}
                        className="opacity-0 group-hover:opacity-100 transition-opacity"
                      />
                    </div>
                    
                    <div className="flex items-center gap-2">
                      <div className="text-xs text-muted-foreground">
                        {message.timestamp.toLocaleTimeString()}
                      </div>
                      
                      {/* Regenerate button for last assistant message */}
                      {isLastAssistantMessage && (
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-6 text-xs gap-1"
                          onClick={regenerateLastResponse}
                          disabled={isCurrentChatProcessing}
                        >
                          <RefreshCw className="w-3 h-3" />
                          Regenerate
                        </Button>
                      )}
                    </div>
                  </div>

                  {message.role === 'user' && (
                    <Avatar className="w-8 h-8">
                      <AvatarFallback className="bg-secondary">
                        <UserIcon className="w-4 h-4" />
                      </AvatarFallback>
                    </Avatar>
                  )}
                </div>
              );
              });
            })()}

            {isCurrentChatProcessing && (
              <div className="flex gap-3 justify-start">
                <Avatar className="w-8 h-8">
                  <AvatarFallback className="bg-primary text-primary-foreground">
                    <Bot className="w-4 h-4" />
                  </AvatarFallback>
                </Avatar>
                <div className="bg-muted rounded-lg p-3">
                  <div className="flex gap-1">
                    <div className="w-2 h-2 bg-foreground/40 rounded-full animate-bounce"></div>
                    <div className="w-2 h-2 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }}></div>
                    <div className="w-2 h-2 bg-foreground/40 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Input Area */}
        <div 
          className={`p-4 border-t bg-card transition-colors ${
            isDragging ? 'bg-primary/5 border-primary' : ''
          }`}
          ref={dropZoneRef}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
        >
          <div className="max-w-[95%] mx-auto relative">
            {/* Drag Overlay */}
            {isDragging && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-primary/10 border-2 border-dashed border-primary rounded-lg pointer-events-none">
                <div className="text-center">
                  <Paperclip className="w-12 h-12 mx-auto mb-2 text-primary" />
                  <p className="text-sm font-medium text-primary">Drop files here</p>
                </div>
              </div>
            )}

            {uploadTasks.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-3">
                {uploadTasks.map((task, index) => (
                  <div
                    key={index}
                    className="relative group"
                  >
                    <FileThumbnail
                      file={task.file}
                      size="md"
                      uploadStatus={task.status}
                      uploadProgress={task.progress}
                    />
                    <button
                      onClick={() => removeFile(index)}
                      className="absolute -top-2 -right-2 bg-destructive text-destructive-foreground rounded-full p-1 shadow-lg opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X className="w-3 h-3" />
                    </button>
                    <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-xs p-1 rounded-b-lg truncate">
                      {task.file.name}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileSelect}
                className="hidden"
                multiple
              />
              <Button
                variant="outline"
                size="icon"
                onClick={() => fileInputRef.current?.click()}
                disabled={isCurrentChatProcessing}
              >
                <Paperclip className="w-4 h-4" />
              </Button>
              <Textarea
                placeholder="Type your message... (Shift+Enter for new line)"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyPress}
                disabled={isCurrentChatProcessing}
                className="min-h-[60px] max-h-[200px] resize-none"
              />
              <Button
                onClick={handleSendMessage}
                disabled={isCurrentChatProcessing || uploadTasks.some(t => t.status === 'pending' || t.status === 'uploading') || (!inputValue.trim() && uploadTasks.length === 0)}
                size="icon"
                className="h-[60px]"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
            <div className="mt-2">
              <Select value={selectedModel} onValueChange={changeModel}>
                <SelectTrigger className="h-8 text-xs w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {models.map(model => (
                    <SelectItem key={model.id} value={model.id} className="text-xs">
                      {model.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </div>

      {/* Delete Chat Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Chat</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this chat? This action cannot be undone and all messages will be permanently removed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setChatToDelete(null)}>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={deleteChat} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Clear Chat Confirmation Dialog */}
      <AlertDialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clear Chat</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to clear all messages in this chat? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={clearCurrentChat}>
              Clear
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
