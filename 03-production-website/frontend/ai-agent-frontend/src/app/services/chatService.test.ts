import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ChatService, ChatServiceError } from './chatService';
import type { AppSyncEventsService } from './appSyncEventsService';

/**
 * Unit tests for ChatService error handling (Task 2.3).
 * Validates that application-level errors in the response body
 * are detected and thrown as ChatServiceError with the correct
 * statusCode and descriptive message.
 *
 * Validates: Requirements 10.1, 10.2, 10.3, 10.5
 */

function createMockAppSyncService(responseValue: unknown) {
  return {
    publishWithResponse: vi.fn().mockResolvedValue(responseValue),
    publish: vi.fn().mockResolvedValue({ successful: [], failed: [] }),
  } as unknown as AppSyncEventsService;
}

describe('ChatService error handling', () => {
  describe('statusCode 400 — Parámetros inválidos', () => {
    it('listConversations throws ChatServiceError with statusCode 400', async () => {
      const mock = createMockAppSyncService({ statusCode: 400, message: 'Bad request' });
      const service = new ChatService(mock);

      await expect(service.listConversations('user-1')).rejects.toThrow(ChatServiceError);
      await expect(service.listConversations('user-1')).rejects.toMatchObject({
        statusCode: 400,
        message: 'Parámetros inválidos o acción no reconocida',
      });
    });

    it('createConversation throws ChatServiceError with statusCode 400', async () => {
      const mock = createMockAppSyncService({ statusCode: 400 });
      const service = new ChatService(mock);

      await expect(service.createConversation('user-1')).rejects.toThrow(ChatServiceError);
      await expect(service.createConversation('user-1')).rejects.toMatchObject({
        statusCode: 400,
      });
    });
  });

  describe('statusCode 404 — Conversación no encontrada', () => {
    it('getMessages throws ChatServiceError with statusCode 404', async () => {
      const mock = createMockAppSyncService({ statusCode: 404 });
      const service = new ChatService(mock);

      await expect(service.getMessages('user-1', 'conv-1')).rejects.toThrow(ChatServiceError);
      await expect(service.getMessages('user-1', 'conv-1')).rejects.toMatchObject({
        statusCode: 404,
        message: 'Conversación no encontrada o no pertenece al usuario',
      });
    });

    it('getMessages 404 is not affected by delete changes', async () => {
      const mock = createMockAppSyncService({ statusCode: 404 });
      const service = new ChatService(mock);

      await expect(service.getMessages('user-1', 'conv-2')).rejects.toMatchObject({
        statusCode: 404,
      });
    });
  });

  describe('deleteConversation uses a plain HTTP publish (reliable, fire-and-forget)', () => {
    it('sends the delete action via publish, not publishWithResponse', async () => {
      const mock = createMockAppSyncService(null);
      const service = new ChatService(mock);

      await service.deleteConversation('user-1', 'conv-1');

      expect(mock.publish).toHaveBeenCalledWith('chat/', {
        action: 'delete_conversation',
        user_id: 'user-1',
        conversation_id: 'conv-1',
      });
      expect(mock.publishWithResponse).not.toHaveBeenCalled();
    });

    it('propagates a transport error if the publish itself fails', async () => {
      const mock = createMockAppSyncService(null);
      (mock.publish as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error('Publish failed: 500'),
      );
      const service = new ChatService(mock);

      await expect(service.deleteConversation('user-1', 'conv-1')).rejects.toThrow('Publish failed');
    });
  });

  describe('statusCode 500 — Error interno del servidor', () => {
    it('updateConversation throws ChatServiceError with statusCode 500', async () => {
      const mock = createMockAppSyncService({ statusCode: 500 });
      const service = new ChatService(mock);

      await expect(service.updateConversation('user-1', 'conv-1', 'title')).rejects.toThrow(ChatServiceError);
      await expect(service.updateConversation('user-1', 'conv-1', 'title')).rejects.toMatchObject({
        statusCode: 500,
        message: 'Error interno del servidor',
      });
    });
  });

  describe('other status codes — generic error message', () => {
    it('throws ChatServiceError with generic message for statusCode 503', async () => {
      const mock = createMockAppSyncService({ statusCode: 503 });
      const service = new ChatService(mock);

      await expect(service.listConversations('user-1')).rejects.toThrow(ChatServiceError);
      await expect(service.listConversations('user-1')).rejects.toMatchObject({
        statusCode: 503,
        message: 'Error del servidor (código 503)',
      });
    });
  });

  describe('statusCode 200 — success, no error thrown', () => {
    it('listConversations returns data when statusCode is 200', async () => {
      const successResponse = {
        statusCode: 200,
        conversations: [{ conversation_id: 'c1', title: 'Test', created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' }],
        next_token: null,
      };
      const mock = createMockAppSyncService(successResponse);
      const service = new ChatService(mock);

      const result = await service.listConversations('user-1');
      expect(result.conversations).toHaveLength(1);
      expect(result.conversations[0].conversation_id).toBe('c1');
    });
  });

  describe('autoRenameConversation', () => {
    it('sends the auto_rename_conversation action with user and conversation ids', async () => {
      const mock = createMockAppSyncService({
        statusCode: 200,
        conversation_id: 'conv-1',
        title: 'Refactoring the auth module',
        updated_at: '2024-01-01T00:00:00Z',
      });
      const service = new ChatService(mock);

      const result = await service.autoRenameConversation('user-1', 'conv-1');

      expect(mock.publishWithResponse).toHaveBeenCalledWith('chat/', {
        action: 'auto_rename_conversation',
        user_id: 'user-1',
        conversation_id: 'conv-1',
      });
      expect(result.title).toBe('Refactoring the auth module');
    });

    it('throws ChatServiceError with statusCode 400 when there is no dialogue', async () => {
      const mock = createMockAppSyncService({ statusCode: 400 });
      const service = new ChatService(mock);

      await expect(service.autoRenameConversation('user-1', 'conv-1')).rejects.toMatchObject({
        name: 'ChatServiceError',
        statusCode: 400,
      });
    });

    it('throws ChatServiceError with statusCode 404 when conversation not found', async () => {
      const mock = createMockAppSyncService({ statusCode: 404 });
      const service = new ChatService(mock);

      await expect(service.autoRenameConversation('user-1', 'conv-x')).rejects.toMatchObject({
        name: 'ChatServiceError',
        statusCode: 404,
      });
    });
  });

  describe('response without statusCode — no error thrown', () => {
    it('listConversations returns data when response has no statusCode', async () => {
      const response = {
        conversations: [{ conversation_id: 'c1', title: 'Test', created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' }],
        next_token: null,
      };
      const mock = createMockAppSyncService(response);
      const service = new ChatService(mock);

      const result = await service.listConversations('user-1');
      expect(result.conversations).toHaveLength(1);
    });

    it('handles null response without throwing', async () => {
      const mock = createMockAppSyncService(null);
      const service = new ChatService(mock);

      // Should not throw — null response is handled defensively with empty array
      const result = await service.listConversations('user-1');
      expect(result.conversations).toEqual([]);
    });
  });

  describe('ChatServiceError is an instance of Error', () => {
    it('has the correct name property', () => {
      const error = new ChatServiceError('test', 400);
      expect(error).toBeInstanceOf(Error);
      expect(error.name).toBe('ChatServiceError');
      expect(error.statusCode).toBe(400);
      expect(error.message).toBe('test');
    });
  });
});
