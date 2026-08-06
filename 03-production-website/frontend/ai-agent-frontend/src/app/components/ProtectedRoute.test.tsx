import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import React from 'react';

// --- Hoisted mock for useAuth ---
const { mockUseAuth } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
}));

vi.mock('@/app/context/AuthContext', () => ({
  useAuth: mockUseAuth,
}));

import { ProtectedRoute } from './ProtectedRoute';

function renderProtectedRoute(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<ProtectedRoute />}>
          <Route index element={<div data-testid="child-content">Protected Content</div>} />
        </Route>
        <Route path="/login" element={<div data-testid="login-page">Login Page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('ProtectedRoute', () => {
  it('renders children when user is present', () => {
    // Validates: Requirements 6.1
    mockUseAuth.mockReturnValue({ user: { id: '1', email: 'a@b.com', name: 'A' }, isLoading: false });

    renderProtectedRoute();

    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });

  it('redirects to /login when user is null and loading is false', () => {
    // Validates: Requirements 6.2
    mockUseAuth.mockReturnValue({ user: null, isLoading: false });

    renderProtectedRoute();

    expect(screen.getByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('child-content')).not.toBeInTheDocument();
  });

  it('shows loading indicator when isLoading is true', () => {
    // Validates: Requirements 6.3
    mockUseAuth.mockReturnValue({ user: null, isLoading: true });

    renderProtectedRoute();

    const spinner = document.querySelector('.animate-spin');
    expect(spinner).toBeInTheDocument();
    expect(screen.queryByTestId('child-content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });
});
