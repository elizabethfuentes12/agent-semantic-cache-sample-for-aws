import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getCognitoConfig, mapCognitoAttributes } from './cognitoConfig';

describe('getCognitoConfig', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_TestPool');
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'testclientid123');
    vi.stubEnv('VITE_COGNITO_REGION', 'us-east-1');
  });

  it('returns correct config when all env vars are set', () => {
    const config = getCognitoConfig();
    expect(config).toEqual({
      userPoolId: 'us-east-1_TestPool',
      clientId: 'testclientid123',
      region: 'us-east-1',
    });
  });

  it('throws when VITE_COGNITO_USER_POOL_ID is missing', () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
    expect(() => getCognitoConfig()).toThrow('VITE_COGNITO_USER_POOL_ID');
  });

  it('throws when multiple env vars are missing', () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', '');
    expect(() => getCognitoConfig()).toThrow('VITE_COGNITO_USER_POOL_ID');
    expect(() => getCognitoConfig()).toThrow('VITE_COGNITO_CLIENT_ID');
  });

  it('throws when all env vars are missing', () => {
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '');
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', '');
    vi.stubEnv('VITE_COGNITO_REGION', '');
    const fn = () => getCognitoConfig();
    expect(fn).toThrow('VITE_COGNITO_USER_POOL_ID');
    expect(fn).toThrow('VITE_COGNITO_CLIENT_ID');
    expect(fn).toThrow('VITE_COGNITO_REGION');
  });
});

describe('mapCognitoAttributes', () => {
  it('maps sub, email, and name correctly', () => {
    const user = mapCognitoAttributes({
      sub: 'abc-123',
      email: 'alice@example.com',
      name: 'Alice',
    });
    expect(user).toEqual({
      id: 'abc-123',
      email: 'alice@example.com',
      name: 'Alice',
      groups: [],
    });
  });

  it('derives name from email prefix when name is absent', () => {
    const user = mapCognitoAttributes({
      sub: 'def-456',
      email: 'bob@example.com',
    });
    expect(user).toEqual({
      id: 'def-456',
      email: 'bob@example.com',
      name: 'bob',
      groups: [],
    });
  });

  it('derives name from email prefix when name is empty string', () => {
    const user = mapCognitoAttributes({
      sub: 'ghi-789',
      email: 'carol@test.org',
      name: '',
    });
    expect(user).toEqual({
      id: 'ghi-789',
      email: 'carol@test.org',
      name: 'carol',
      groups: [],
    });
  });

  it('maps Cognito groups when present', () => {
    const user = mapCognitoAttributes({
      sub: 'jkl-012',
      email: 'dave@example.com',
      name: 'Dave',
      groups: ['admin', 'beta'],
    });
    expect(user).toEqual({
      id: 'jkl-012',
      email: 'dave@example.com',
      name: 'Dave',
      groups: ['admin', 'beta'],
    });
  });
});
