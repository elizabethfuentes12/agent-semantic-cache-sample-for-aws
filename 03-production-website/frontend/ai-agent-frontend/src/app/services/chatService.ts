import type { AppSyncEventsService } from './appSyncEventsService';
import type { MessageAttachment } from '@/app/services/uploadService';

// --- Tipos de respuesta del backend ---

export interface BackendConversation {
  conversation_id: string;
  title: string;
  created_at: string; // UTC ISO 8601
  updated_at: string; // UTC ISO 8601
  agent_arn?: string;
  model_id?: string;
}

export interface BackendMessage {
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'message';
  content: string;
  created_at: string; // UTC ISO 8601
  /** Attachment metadata persisted with a user message, if any. */
  attachments?: MessageAttachment[];
}

export interface ListConversationsResponse {
  conversations: BackendConversation[];
  next_token: string | null;
}

export interface GetMessagesResponse {
  messages: BackendMessage[];
  next_token: string | null;
  agent_arn?: string;
  model_id?: string;
}

export interface CreateConversationResponse {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface AutoRenameConversationResponse {
  conversation_id: string;
  title: string;
  updated_at: string;
}

// --- Error personalizado del servicio ---

export class ChatServiceError extends Error {
  statusCode: number;

  constructor(message: string, statusCode: number) {
    super(message);
    this.name = 'ChatServiceError';
    this.statusCode = statusCode;
  }
}

// --- Constantes de paginación ---

export const DEFAULT_CONVERSATIONS_LIMIT = 20;
export const DEFAULT_MESSAGES_LIMIT = 50;

// --- Clase del servicio (métodos implementados en Task 2.2) ---

export class ChatService {
  private appSyncService: AppSyncEventsService;

  constructor(appSyncService: AppSyncEventsService) {
    this.appSyncService = appSyncService;
  }

  /**
   * Inspects the backend response for application-level errors.
   * The HTTP response may be 200, but the response body can contain
   * a `statusCode` field indicating an error (400, 404, 500, etc.).
   * Throws a ChatServiceError with the statusCode and a descriptive message.
   */
  private handleResponseError(response: unknown): void {
    if (response == null || typeof response !== 'object') {
      return;
    }

    const res = response as Record<string, unknown>;

    if (!('statusCode' in res) || typeof res.statusCode !== 'number') {
      return;
    }

    const statusCode = res.statusCode;

    if (statusCode === 200) {
      return;
    }

    let message: string;
    switch (statusCode) {
      case 400:
        message = 'Parámetros inválidos o acción no reconocida';
        break;
      case 404:
        message = 'Conversación no encontrada o no pertenece al usuario';
        break;
      case 500:
        message = 'Error interno del servidor';
        break;
      default:
        message = `Error del servidor (código ${statusCode})`;
        break;
    }

    throw new ChatServiceError(message, statusCode);
  }

  async listConversations(
    userId: string,
    limit: number = DEFAULT_CONVERSATIONS_LIMIT,
    nextToken?: string | null,
  ): Promise<ListConversationsResponse> {
    const payload: Record<string, unknown> = {
      action: 'list_conversations',
      user_id: userId,
      limit,
    };
    if (nextToken) {
      payload.next_token = nextToken;
    }
    const response = await this.appSyncService.publishWithResponse('chat/', payload);
    console.log('[ChatService.listConversations] Raw response:', JSON.stringify(response).substring(0, 1000));
    this.handleResponseError(response);
    const res = (response ?? {}) as ListConversationsResponse;
    // Defensive: ensure conversations array exists
    if (!res.conversations) {
      res.conversations = [];
    }
    return res;
  }

  async getMessages(
    userId: string,
    conversationId: string,
    limit: number = DEFAULT_MESSAGES_LIMIT,
    nextToken?: string | null,
  ): Promise<GetMessagesResponse> {
    const payload: Record<string, unknown> = {
      action: 'get_messages',
      user_id: userId,
      conversation_id: conversationId,
      limit,
    };
    if (nextToken) {
      payload.next_token = nextToken;
    }
    const response = await this.appSyncService.publishWithResponse('chat/', payload);
    this.handleResponseError(response);
    const res = (response ?? {}) as GetMessagesResponse;
    // Defensive: ensure messages array exists
    if (!res.messages) {
      res.messages = [];
    }
    return res;
  }

  async createConversation(
    userId: string,
    title?: string,
  ): Promise<CreateConversationResponse> {
    const payload: Record<string, unknown> = {
      action: 'create_conversation',
      user_id: userId,
    };
    if (title !== undefined) {
      payload.title = title;
    }
    const response = await this.appSyncService.publishWithResponse('chat/', payload);
    this.handleResponseError(response);
    return response as CreateConversationResponse;
  }

  async updateConversation(
    userId: string,
    conversationId: string,
    title: string,
  ): Promise<void> {
    const payload: Record<string, unknown> = {
      action: 'update_conversation',
      user_id: userId,
      conversation_id: conversationId,
      title,
    };
    const response = await this.appSyncService.publishWithResponse('chat/', payload);
    this.handleResponseError(response);
  }

  /**
   * Asks the backend to generate a title from the conversation's dialogue
   * (using a Bedrock model) and persist it. Returns the generated title.
   */
  async autoRenameConversation(
    userId: string,
    conversationId: string,
  ): Promise<AutoRenameConversationResponse> {
    const payload: Record<string, unknown> = {
      action: 'auto_rename_conversation',
      user_id: userId,
      conversation_id: conversationId,
    };
    const response = await this.appSyncService.publishWithResponse('chat/', payload);
    this.handleResponseError(response);
    return response as AutoRenameConversationResponse;
  }

  async deleteConversation(
    userId: string,
    conversationId: string,
  ): Promise<void> {
    const payload: Record<string, unknown> = {
      action: 'delete_conversation',
      user_id: userId,
      conversation_id: conversationId,
    };
    // Use a plain HTTP publish instead of publishWithResponse. Deletion only
    // needs to invoke the backend handler (REQUEST_RESPONSE channels run the
    // Lambda synchronously on publish). publishWithResponse first opens a
    // WebSocket and subscribes, and only sends the HTTP POST if that succeeds
    // — if the socket fails/times out the POST is never sent, the backend
    // never deletes, and the conversation reappears on reload.
    await this.appSyncService.publish('chat/', payload);
  }
}
