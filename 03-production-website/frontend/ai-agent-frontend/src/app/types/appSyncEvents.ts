export interface ToolCallEvent {
  type: 'tool_call';
  tool: string;
  toolUseId?: string;
  input: Record<string, unknown>;
  conversation_id?: string;
}

export interface ToolResultEvent {
  type: 'tool_result';
  tool: string;
  toolUseId?: string;
  result: string;
  conversation_id?: string;
}

export interface MessageEvent {
  type: 'message';
  content: string;
  conversation_id?: string;
}

export interface CompleteEvent {
  type: 'complete';
  answer: string;
  conversation_id?: string;
}

export type AppSyncEvent =
  | ToolCallEvent
  | ToolResultEvent
  | MessageEvent
  | CompleteEvent;

export interface FileMetadata {
  name: string;
  type: string;
  size: number;
}

export interface PublishPayload {
  message: {
    content: string;
    files?: FileMetadata[];
  };
  sessionId: string;
  userId: string;
  accessToken: string;
  agentId: string;
  target_arn?: string;
  agent_arn?: string;
}

export interface SubscriptionCallbacks {
  onEvent: (event: AppSyncEvent) => void;
  onError: (error: Error) => void;
  onClose?: () => void;
}

export interface Subscription {
  unsubscribe: () => void;
}

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';
