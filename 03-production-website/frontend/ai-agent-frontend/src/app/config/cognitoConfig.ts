export interface CognitoConfig {
  userPoolId: string;
  clientId: string;
  region: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  /** Cognito groups the user belongs to (from the `cognito:groups` ID token claim). */
  groups: string[];
}

const REQUIRED_ENV_VARS = {
  VITE_COGNITO_USER_POOL_ID: 'userPoolId',
  VITE_COGNITO_CLIENT_ID: 'clientId',
  VITE_COGNITO_REGION: 'region',
} as const;

export function getCognitoConfig(): CognitoConfig {
  const missing: string[] = [];

  for (const envVar of Object.keys(REQUIRED_ENV_VARS)) {
    const value = import.meta.env[envVar];
    if (!value || value.trim() === '') {
      missing.push(envVar);
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `Missing required Cognito environment variables: ${missing.join(', ')}`
    );
  }

  return {
    userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
    clientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
    region: import.meta.env.VITE_COGNITO_REGION,
  };
}

export function mapCognitoAttributes(attrs: {
  sub: string;
  email: string;
  name?: string;
  groups?: string[];
}): User {
  return {
    id: attrs.sub,
    email: attrs.email,
    name: attrs.name || attrs.email.split('@')[0],
    groups: attrs.groups ?? [],
  };
}
