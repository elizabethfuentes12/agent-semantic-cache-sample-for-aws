import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';

// --- Hoisted mocks ---
const { mockLogin, mockForgotPassword, mockConfirmForgotPassword, mockNavigate, mockToastError, mockToastSuccess } = vi.hoisted(() => ({
  mockLogin: vi.fn(),
  mockForgotPassword: vi.fn(),
  mockConfirmForgotPassword: vi.fn(),
  mockNavigate: vi.fn(),
  mockToastError: vi.fn(),
  mockToastSuccess: vi.fn(),
}));

vi.mock('@/app/context/AuthContext', () => ({
  useAuth: () => ({
    login: mockLogin,
    forgotPassword: mockForgotPassword,
    confirmForgotPassword: mockConfirmForgotPassword,
    completeNewPassword: vi.fn(),
    user: null,
    isLoading: false,
    newPasswordRequired: false,
    logout: vi.fn(),
  }),
}));

vi.mock('react-router', () => ({
  useNavigate: () => mockNavigate,
}));

vi.mock('sonner', () => ({
  toast: {
    error: mockToastError,
    success: mockToastSuccess,
  },
}));

import { Login } from './Login';

describe('Login page error handling', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('maps NotAuthorizedException to "Incorrect email or password."', async () => {
    // Validates: Requirements 8.1
    mockLogin.mockRejectedValue({ name: 'NotAuthorizedException', message: 'Incorrect username or password.' });

    render(<Login />);

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
      await userEvent.type(screen.getByLabelText(/password/i), 'wrongpass');
      await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    });

    expect(mockToastError).toHaveBeenCalledWith('Incorrect email or password.');
  });

  it('maps UserNotFoundException to "Incorrect email or password."', async () => {
    // Validates: Requirements 8.2
    mockLogin.mockRejectedValue({ name: 'UserNotFoundException', message: 'User does not exist.' });

    render(<Login />);

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'nobody@example.com');
      await userEvent.type(screen.getByLabelText(/password/i), 'somepass');
      await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    });

    expect(mockToastError).toHaveBeenCalledWith('Incorrect email or password.');
  });

  it('maps UserNotConfirmedException to confirmation message', async () => {
    // Validates: Requirements 8.3
    mockLogin.mockRejectedValue({ name: 'UserNotConfirmedException', message: 'User is not confirmed.' });

    render(<Login />);

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'unconfirmed@example.com');
      await userEvent.type(screen.getByLabelText(/password/i), 'somepass');
      await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    });

    expect(mockToastError).toHaveBeenCalledWith(
      'Account not confirmed. Please check your email for a confirmation link.'
    );
  });

  it('shows generic message for unknown errors', async () => {
    // Validates: Requirements 8.4
    mockLogin.mockRejectedValue({ name: 'InternalErrorException', message: 'Something broke' });

    render(<Login />);

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
      await userEvent.type(screen.getByLabelText(/password/i), 'somepass');
      await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    });

    expect(mockToastError).toHaveBeenCalledWith('Sign-in failed. Please try again.');
  });

  it('does not render demo hint text', () => {
    // Validates: Requirements 8.5
    render(<Login />);

    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/use any email and password/i)).not.toBeInTheDocument();
  });
});

describe('Login password reset flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('navigates to the forgot-password view via the "Forgot password?" link', async () => {
    render(<Login />);

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /forgot password/i }));
    });

    expect(screen.getByRole('heading', { name: /reset password/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send reset code/i })).toBeInTheDocument();
  });

  it('requests a reset code and advances to the reset view on success', async () => {
    mockForgotPassword.mockResolvedValue(undefined);

    render(<Login />);

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /forgot password/i }));
    });

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
      await userEvent.click(screen.getByRole('button', { name: /send reset code/i }));
    });

    expect(mockForgotPassword).toHaveBeenCalledWith('user@example.com');
    expect(mockToastSuccess).toHaveBeenCalledWith('We sent a reset code to your email.');
    expect(screen.getByRole('heading', { name: /enter reset code/i })).toBeInTheDocument();
  });

  it('validates that email is provided before requesting a code', async () => {
    render(<Login />);

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /forgot password/i }));
    });

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /send reset code/i }));
    });

    expect(mockForgotPassword).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith('Please enter your email');
  });

  it('confirms a new password with the reset code and returns to sign in', async () => {
    mockForgotPassword.mockResolvedValue(undefined);
    mockConfirmForgotPassword.mockResolvedValue(undefined);

    render(<Login />);

    // signin -> forgot
    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /forgot password/i }));
    });
    // forgot -> reset
    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
      await userEvent.click(screen.getByRole('button', { name: /send reset code/i }));
    });

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/reset code/i), '123456');
      await userEvent.type(screen.getByLabelText('New Password'), 'newpassword1');
      await userEvent.type(screen.getByLabelText(/confirm password/i), 'newpassword1');
      await userEvent.click(screen.getByRole('button', { name: /^reset password$/i }));
    });

    expect(mockConfirmForgotPassword).toHaveBeenCalledWith('user@example.com', '123456', 'newpassword1');
    expect(mockToastSuccess).toHaveBeenCalledWith('Password reset. You can now sign in.');
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('rejects mismatched passwords during reset', async () => {
    mockForgotPassword.mockResolvedValue(undefined);

    render(<Login />);

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /forgot password/i }));
    });
    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
      await userEvent.click(screen.getByRole('button', { name: /send reset code/i }));
    });

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/reset code/i), '123456');
      await userEvent.type(screen.getByLabelText('New Password'), 'newpassword1');
      await userEvent.type(screen.getByLabelText(/confirm password/i), 'different2');
      await userEvent.click(screen.getByRole('button', { name: /^reset password$/i }));
    });

    expect(mockConfirmForgotPassword).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith('Passwords do not match');
  });

  it('maps CodeMismatchException to a friendly message', async () => {
    mockForgotPassword.mockResolvedValue(undefined);
    mockConfirmForgotPassword.mockRejectedValue({ name: 'CodeMismatchException', message: 'Invalid code' });

    render(<Login />);

    await act(async () => {
      await userEvent.click(screen.getByRole('button', { name: /forgot password/i }));
    });
    await act(async () => {
      await userEvent.type(screen.getByLabelText(/email/i), 'user@example.com');
      await userEvent.click(screen.getByRole('button', { name: /send reset code/i }));
    });

    await act(async () => {
      await userEvent.type(screen.getByLabelText(/reset code/i), '000000');
      await userEvent.type(screen.getByLabelText('New Password'), 'newpassword1');
      await userEvent.type(screen.getByLabelText(/confirm password/i), 'newpassword1');
      await userEvent.click(screen.getByRole('button', { name: /^reset password$/i }));
    });

    expect(mockToastError).toHaveBeenCalledWith('Invalid reset code. Please check and try again.');
  });
});
