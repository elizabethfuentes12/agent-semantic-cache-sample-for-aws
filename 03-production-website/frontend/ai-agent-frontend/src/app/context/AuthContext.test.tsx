import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import React from 'react';

// --- Hoisted mock functions (available before vi.mock factories run) ---
const {
  mockAuthenticateUser,
  mockSignOut,
  mockGetCurrentUser,
  mockForgotPassword,
  mockConfirmPassword,
} = vi.hoisted(() => ({
  mockAuthenticateUser: vi.fn(),
  mockSignOut: vi.fn(),
  mockGetCurrentUser: vi.fn(),
  mockForgotPassword: vi.fn(),
  mockConfirmPassword: vi.fn(),
}));

// Mock cognitoConfig
vi.mock('@/app/config/cognitoConfig', () => ({
  getCognitoConfig: () => ({
    userPoolId: 'us-east-1_TestPool',
    clientId: 'testclientid123',
    region: 'us-east-1',
  }),
  mapCognitoAttributes: (attrs: { sub: string; email: string; name?: string }) => ({
    id: attrs.sub,
    email: attrs.email,
    name: attrs.name || attrs.email.split('@')[0],
  }),
}));

// Mock amazon-cognito-identity-js
vi.mock('amazon-cognito-identity-js', () => ({
  CognitoUserPool: vi.fn().mockImplementation(function (this: Record<string, unknown>) {
    this.getCurrentUser = mockGetCurrentUser;
  }),
  CognitoUser: vi.fn().mockImplementation(function (this: Record<string, unknown>) {
    this.authenticateUser = mockAuthenticateUser;
    this.signOut = mockSignOut;
    this.forgotPassword = mockForgotPassword;
    this.confirmPassword = mockConfirmPassword;
  }),
  AuthenticationDetails: vi.fn().mockImplementation(function (this: Record<string, unknown>, data: Record<string, unknown>) {
    Object.assign(this, data);
  }),
  CognitoUserSession: vi.fn(),
}));

import { AuthProvider, useAuth } from './AuthContext';

// --- Test helpers ---

function TestConsumer() {
  const { user, login, logout, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="user">{user ? JSON.stringify(user) : 'null'}</span>
      <button data-testid="login-btn" onClick={() => login('test@example.com', 'pass').catch(() => {})}>Login</button>
      <button data-testid="logout-btn" onClick={() => logout()}>Logout</button>
    </div>
  );
}

function TestConsumerWithError({ onError }: { onError: (err: Error) => void }) {
  const { login, user, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <span data-testid="user">{user ? JSON.stringify(user) : 'null'}</span>
      <button data-testid="login-btn" onClick={() => login('test@example.com', 'pass').catch(onError)}>Login</button>
    </div>
  );
}

function TestGetSessionConsumer({ onSession, onError }: { onSession: (s: unknown) => void; onError: (err: Error) => void }) {
  const { getSession, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(isLoading)}</span>
      <button data-testid="get-session-btn" onClick={() => getSession().then(onSession).catch(onError)}>GetSession</button>
    </div>
  );
}

function TestResetConsumer({ onError }: { onError: (err: Error) => void }) {
  const { forgotPassword, confirmForgotPassword } = useAuth();
  return (
    <div>
      <button
        data-testid="forgot-btn"
        onClick={() => forgotPassword('user@example.com').catch(onError)}
      >
        Forgot
      </button>
      <button
        data-testid="confirm-btn"
        onClick={() => confirmForgotPassword('user@example.com', '123456', 'newpass123').catch(onError)}
      >
        Confirm
      </button>
    </div>
  );
}

function renderWithAuth() {
  return render(
    <AuthProvider><TestConsumer /></AuthProvider>
  );
}

function createFakeSession(overrides: Record<string, string> = {}) {
  const payload = { sub: 'user-123', email: 'test@example.com', name: 'Test User', ...overrides };
  return {
    isValid: () => true,
    getIdToken: () => ({ decodePayload: () => payload }),
  };
}

// --- Tests ---

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCurrentUser.mockReturnValue(null);
  });

  describe('login()', () => {
    it('calls authenticateUser on the Cognito client', async () => {
      // Validates: Requirements 2.1, 3.1
      mockAuthenticateUser.mockImplementation((_d: unknown, cb: { onSuccess: (s: unknown) => void }) => {
        cb.onSuccess(createFakeSession());
      });

      renderWithAuth();
      await act(async () => { screen.getByTestId('login-btn').click(); });

      expect(mockAuthenticateUser).toHaveBeenCalledTimes(1);
      const callbacks = mockAuthenticateUser.mock.calls[0][1];
      expect(callbacks).toHaveProperty('onSuccess');
      expect(callbacks).toHaveProperty('onFailure');
      expect(callbacks).toHaveProperty('newPasswordRequired');
    });

    it('sets user from session on successful login', async () => {
      // Validates: Requirements 3.1
      mockAuthenticateUser.mockImplementation((_d: unknown, cb: { onSuccess: (s: unknown) => void }) => {
        cb.onSuccess(createFakeSession());
      });

      renderWithAuth();
      await act(async () => { screen.getByTestId('login-btn').click(); });

      const user = JSON.parse(screen.getByTestId('user').textContent!);
      expect(user).toEqual({ id: 'user-123', email: 'test@example.com', name: 'Test User' });
    });

    it('rejects on NEW_PASSWORD_REQUIRED challenge', async () => {
      // Validates: Requirements 3.6
      mockAuthenticateUser.mockImplementation((_d: unknown, cb: { newPasswordRequired: () => void }) => {
        cb.newPasswordRequired();
      });

      let loginError: Error | undefined;
      render(
        <AuthProvider>
          <TestConsumerWithError onError={(err) => { loginError = err; }} />
        </AuthProvider>
      );

      await act(async () => {
        screen.getAllByTestId('login-btn')[0].click();
        await new Promise((r) => setTimeout(r, 10));
      });

      expect(loginError).toBeDefined();
      expect(loginError!.message).toContain('Password reset required');
    });
  });

  describe('logout()', () => {
    it('calls cognitoUser.signOut() and clears user state', async () => {
      // Validates: Requirements 4.1, 4.2
      mockAuthenticateUser.mockImplementation((_d: unknown, cb: { onSuccess: (s: unknown) => void }) => {
        cb.onSuccess(createFakeSession());
      });
      mockGetCurrentUser.mockReturnValue({ signOut: mockSignOut, getSession: vi.fn() });

      renderWithAuth();

      await act(async () => { screen.getByTestId('login-btn').click(); });
      expect(screen.getByTestId('user').textContent).not.toBe('null');

      await act(async () => { screen.getByTestId('logout-btn').click(); });

      expect(mockSignOut).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('user').textContent).toBe('null');
    });
  });

  describe('session restore', () => {
    it('sets user from valid session on mount', async () => {
      // Validates: Requirements 5.1, 5.2
      const fakeSession = createFakeSession();
      mockGetCurrentUser.mockReturnValue({
        getSession: vi.fn((cb: (err: null, s: unknown) => void) => cb(null, fakeSession)),
        signOut: vi.fn(),
      });

      renderWithAuth();

      await waitFor(() => {
        const user = JSON.parse(screen.getByTestId('user').textContent!);
        expect(user).toEqual({ id: 'user-123', email: 'test@example.com', name: 'Test User' });
      });
    });

    it('sets user to null when no session exists', async () => {
      // Validates: Requirements 5.4
      mockGetCurrentUser.mockReturnValue(null);

      renderWithAuth();

      await waitFor(() => {
        expect(screen.getByTestId('user').textContent).toBe('null');
        expect(screen.getByTestId('loading').textContent).toBe('false');
      });
    });

    it('sets user to null when getSession returns an error', async () => {
      // Validates: Requirements 5.4
      mockGetCurrentUser.mockReturnValue({
        getSession: vi.fn((cb: (err: Error, s: null) => void) => cb(new Error('No session'), null)),
        signOut: vi.fn(),
      });

      renderWithAuth();

      await waitFor(() => {
        expect(screen.getByTestId('user').textContent).toBe('null');
        expect(screen.getByTestId('loading').textContent).toBe('false');
      });
    });

    it('isLoading is true during session restore', async () => {
      // Validates: Requirements 5.5
      let resolveSession!: () => void;
      mockGetCurrentUser.mockReturnValue({
        getSession: vi.fn((cb: (err: null, s: unknown) => void) => {
          resolveSession = () => cb(null, createFakeSession());
        }),
        signOut: vi.fn(),
      });

      renderWithAuth();

      // isLoading should be true while session restore is pending
      expect(screen.getByTestId('loading').textContent).toBe('true');

      await act(async () => { resolveSession(); });

      expect(screen.getByTestId('loading').textContent).toBe('false');
    });
  });

  describe('getSession()', () => {
    it('returns a valid session when a user is authenticated', async () => {
      // Validates: Requirements 6.1, 6.2
      const fakeSession = createFakeSession();
      const mockGetSessionFn = vi.fn((cb: (err: null, s: unknown) => void) => cb(null, fakeSession));
      mockGetCurrentUser.mockReturnValue({
        getSession: mockGetSessionFn,
        signOut: vi.fn(),
      });

      let capturedSession: unknown;
      render(
        <AuthProvider>
          <TestGetSessionConsumer
            onSession={(s) => { capturedSession = s; }}
            onError={() => {}}
          />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading').textContent).toBe('false');
      });

      await act(async () => { screen.getByTestId('get-session-btn').click(); });

      await waitFor(() => {
        expect(capturedSession).toBe(fakeSession);
      });
    });

    it('rejects with an error when no user is authenticated', async () => {
      // Validates: Requirements 6.1
      mockGetCurrentUser.mockReturnValue(null);

      let capturedError: Error | undefined;
      render(
        <AuthProvider>
          <TestGetSessionConsumer
            onSession={() => {}}
            onError={(err) => { capturedError = err; }}
          />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading').textContent).toBe('false');
      });

      await act(async () => { screen.getByTestId('get-session-btn').click(); });

      await waitFor(() => {
        expect(capturedError).toBeDefined();
        expect(capturedError!.message).toBe('No authenticated user');
      });
    });

    it('rejects when getSession callback returns an error', async () => {
      // Validates: Requirements 6.2
      mockGetCurrentUser.mockReturnValue({
        getSession: vi.fn((cb: (err: Error, s: null) => void) => cb(new Error('Session expired'), null)),
        signOut: vi.fn(),
      });

      let capturedError: Error | undefined;
      render(
        <AuthProvider>
          <TestGetSessionConsumer
            onSession={() => {}}
            onError={(err) => { capturedError = err; }}
          />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading').textContent).toBe('false');
      });

      await act(async () => { screen.getByTestId('get-session-btn').click(); });

      await waitFor(() => {
        expect(capturedError).toBeDefined();
        expect(capturedError!.message).toBe('Session expired');
      });
    });
  });

  describe('forgotPassword()', () => {
    it('resolves when Cognito sends a reset code', async () => {
      mockForgotPassword.mockImplementation((cb: { onSuccess: (d: unknown) => void }) => {
        cb.onSuccess({ CodeDeliveryDetails: {} });
      });

      let capturedError: Error | undefined;
      render(
        <AuthProvider>
          <TestResetConsumer onError={(err) => { capturedError = err; }} />
        </AuthProvider>
      );

      await act(async () => { screen.getByTestId('forgot-btn').click(); });

      expect(mockForgotPassword).toHaveBeenCalledTimes(1);
      expect(capturedError).toBeUndefined();
    });

    it('rejects with the Cognito error on failure', async () => {
      mockForgotPassword.mockImplementation((cb: { onFailure: (e: Error) => void }) => {
        cb.onFailure(Object.assign(new Error('User not found'), { name: 'UserNotFoundException' }));
      });

      let capturedError: Error | undefined;
      render(
        <AuthProvider>
          <TestResetConsumer onError={(err) => { capturedError = err; }} />
        </AuthProvider>
      );

      await act(async () => {
        screen.getByTestId('forgot-btn').click();
        await new Promise((r) => setTimeout(r, 10));
      });

      expect(capturedError).toBeDefined();
      expect(capturedError!.message).toBe('User not found');
    });
  });

  describe('confirmForgotPassword()', () => {
    it('resolves when the password is reset with a valid code', async () => {
      mockConfirmPassword.mockImplementation((_code: string, _pw: string, cb: { onSuccess: () => void }) => {
        cb.onSuccess();
      });

      let capturedError: Error | undefined;
      render(
        <AuthProvider>
          <TestResetConsumer onError={(err) => { capturedError = err; }} />
        </AuthProvider>
      );

      await act(async () => { screen.getByTestId('confirm-btn').click(); });

      expect(mockConfirmPassword).toHaveBeenCalledWith('123456', 'newpass123', expect.any(Object));
      expect(capturedError).toBeUndefined();
    });

    it('rejects when the reset code is invalid', async () => {
      mockConfirmPassword.mockImplementation((_code: string, _pw: string, cb: { onFailure: (e: Error) => void }) => {
        cb.onFailure(Object.assign(new Error('Invalid verification code provided'), { name: 'CodeMismatchException' }));
      });

      let capturedError: Error | undefined;
      render(
        <AuthProvider>
          <TestResetConsumer onError={(err) => { capturedError = err; }} />
        </AuthProvider>
      );

      await act(async () => {
        screen.getByTestId('confirm-btn').click();
        await new Promise((r) => setTimeout(r, 10));
      });

      expect(capturedError).toBeDefined();
      expect((capturedError as { name?: string }).name).toBe('CodeMismatchException');
    });
  });
});
