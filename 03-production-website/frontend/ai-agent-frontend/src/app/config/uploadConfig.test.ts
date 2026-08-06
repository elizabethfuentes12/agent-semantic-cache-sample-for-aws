import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getUploadConfig } from './uploadConfig';

describe('getUploadConfig', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', 'us-east-1:test-pool-id');
    vi.stubEnv('VITE_S3_UPLOAD_BUCKET', 'test-upload-bucket');
    vi.stubEnv('VITE_COGNITO_REGION', 'us-east-1');
  });

  it('returns correct config when all env vars are set', () => {
    const config = getUploadConfig();
    expect(config).toEqual({
      identityPoolId: 'us-east-1:test-pool-id',
      uploadBucket: 'test-upload-bucket',
      region: 'us-east-1',
    });
  });

  it('throws when VITE_COGNITO_IDENTITY_POOL_ID is missing', () => {
    vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', '');
    expect(() => getUploadConfig()).toThrow('VITE_COGNITO_IDENTITY_POOL_ID');
  });

  it('throws when VITE_S3_UPLOAD_BUCKET is missing', () => {
    vi.stubEnv('VITE_S3_UPLOAD_BUCKET', '');
    expect(() => getUploadConfig()).toThrow('VITE_S3_UPLOAD_BUCKET');
  });

  it('throws when VITE_COGNITO_REGION is missing', () => {
    vi.stubEnv('VITE_COGNITO_REGION', '');
    expect(() => getUploadConfig()).toThrow('VITE_COGNITO_REGION');
  });

  it('throws listing all missing vars when multiple are absent', () => {
    vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', '');
    vi.stubEnv('VITE_S3_UPLOAD_BUCKET', '');
    const fn = () => getUploadConfig();
    expect(fn).toThrow('VITE_COGNITO_IDENTITY_POOL_ID');
    expect(fn).toThrow('VITE_S3_UPLOAD_BUCKET');
  });

  it('throws listing all missing vars when all are absent', () => {
    vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', '');
    vi.stubEnv('VITE_S3_UPLOAD_BUCKET', '');
    vi.stubEnv('VITE_COGNITO_REGION', '');
    const fn = () => getUploadConfig();
    expect(fn).toThrow('VITE_COGNITO_IDENTITY_POOL_ID');
    expect(fn).toThrow('VITE_S3_UPLOAD_BUCKET');
    expect(fn).toThrow('VITE_COGNITO_REGION');
  });

  it('treats whitespace-only values as missing', () => {
    vi.stubEnv('VITE_COGNITO_IDENTITY_POOL_ID', '   ');
    expect(() => getUploadConfig()).toThrow('VITE_COGNITO_IDENTITY_POOL_ID');
  });
});
