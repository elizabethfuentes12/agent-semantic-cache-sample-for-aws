export interface UploadConfig {
  identityPoolId: string;
  uploadBucket: string;
  region: string;
}

const REQUIRED_ENV_VARS = {
  VITE_COGNITO_IDENTITY_POOL_ID: 'identityPoolId',
  VITE_S3_UPLOAD_BUCKET: 'uploadBucket',
  VITE_COGNITO_REGION: 'region',
} as const;

export function getUploadConfig(): UploadConfig {
  const missing: string[] = [];

  for (const envVar of Object.keys(REQUIRED_ENV_VARS)) {
    const value = import.meta.env[envVar];
    if (!value || value.trim() === '') {
      missing.push(envVar);
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `Missing required upload environment variables: ${missing.join(', ')}`
    );
  }

  return {
    identityPoolId: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID,
    uploadBucket: import.meta.env.VITE_S3_UPLOAD_BUCKET,
    region: import.meta.env.VITE_COGNITO_REGION,
  };
}
