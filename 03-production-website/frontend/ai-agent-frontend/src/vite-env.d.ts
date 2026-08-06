/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_COGNITO_USER_POOL_ID: string;
  readonly VITE_COGNITO_CLIENT_ID: string;
  readonly VITE_COGNITO_REGION: string;
  readonly VITE_APPSYNC_EVENTS_ENDPOINT: string;
  readonly VITE_AGENT_LIST: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
