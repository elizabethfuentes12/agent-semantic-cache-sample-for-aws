import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { Bot, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

export function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetCode, setResetCode] = useState('');
  const [mode, setMode] = useState<'signin' | 'forgot' | 'reset'>('signin');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { login, completeNewPassword, forgotPassword, confirmForgotPassword, user, newPasswordRequired } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (user) {
      navigate('/chat');
    }
  }, [user, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!email || !password) {
      toast.error('Please fill in all fields');
      return;
    }

    setIsSubmitting(true);
    try {
      await login(email, password);
      if (!newPasswordRequired) {
        toast.success('Welcome back!');
        navigate('/chat');
      }
    } catch (err: unknown) {
      const error = err as { name?: string };
      if (error.name === 'NotAuthorizedException' || error.name === 'UserNotFoundException') {
        toast.error('Incorrect email or password.');
      } else if (error.name === 'UserNotConfirmedException') {
        toast.error('Account not confirmed. Please check your email for a confirmation link.');
      } else {
        toast.error('Sign-in failed. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleNewPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!newPassword || !confirmPassword) {
      toast.error('Please fill in all fields');
      return;
    }

    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }

    setIsSubmitting(true);
    try {
      await completeNewPassword(newPassword);
      toast.success('Password updated. Welcome!');
      navigate('/chat');
    } catch (err: unknown) {
      const error = err as { message?: string };
      toast.error(error.message || 'Failed to set new password. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!email) {
      toast.error('Please enter your email');
      return;
    }

    setIsSubmitting(true);
    try {
      await forgotPassword(email);
      toast.success('We sent a reset code to your email.');
      setMode('reset');
    } catch (err: unknown) {
      const error = err as { name?: string; message?: string };
      if (error.name === 'LimitExceededException') {
        toast.error('Too many attempts. Please try again later.');
      } else if (error.name === 'InvalidParameterException') {
        toast.error('This account cannot be reset automatically. Please contact support.');
      } else {
        // Avoid leaking whether an account exists for the given email.
        toast.success('If an account exists for that email, a reset code has been sent.');
        setMode('reset');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!resetCode || !newPassword || !confirmPassword) {
      toast.error('Please fill in all fields');
      return;
    }

    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    if (newPassword.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }

    setIsSubmitting(true);
    try {
      await confirmForgotPassword(email, resetCode, newPassword);
      toast.success('Password reset. You can now sign in.');
      setPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setResetCode('');
      setMode('signin');
    } catch (err: unknown) {
      const error = err as { name?: string; message?: string };
      if (error.name === 'CodeMismatchException') {
        toast.error('Invalid reset code. Please check and try again.');
      } else if (error.name === 'ExpiredCodeException') {
        toast.error('This reset code has expired. Please request a new one.');
      } else if (error.name === 'InvalidPasswordException') {
        toast.error(error.message || 'Password does not meet the requirements.');
      } else if (error.name === 'LimitExceededException') {
        toast.error('Too many attempts. Please try again later.');
      } else {
        toast.error('Failed to reset password. Please try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (newPasswordRequired) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-slate-50 to-slate-100">
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1 text-center">
            <div className="flex justify-center mb-2">
              <div className="p-3 bg-primary rounded-full">
                <Bot className="w-8 h-8 text-primary-foreground" />
              </div>
            </div>
            <CardTitle className="text-2xl">Set New Password</CardTitle>
            <CardDescription>
              Your account requires a new password before you can continue.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleNewPassword} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="newPassword">New Password</Label>
                <Input
                  id="newPassword"
                  type="password"
                  placeholder="••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <Button
                type="submit"
                className="w-full"
                disabled={isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Updating password...
                  </>
                ) : (
                  'Set Password'
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (mode === 'forgot') {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-slate-50 to-slate-100">
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1 text-center">
            <div className="flex justify-center mb-2">
              <div className="p-3 bg-primary rounded-full">
                <Bot className="w-8 h-8 text-primary-foreground" />
              </div>
            </div>
            <CardTitle className="text-2xl">Reset Password</CardTitle>
            <CardDescription>
              Enter your email and we'll send you a reset code.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleForgotPassword} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="user@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Sending code...
                  </>
                ) : (
                  'Send Reset Code'
                )}
              </Button>
              <div className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => setMode('signin')}
                  disabled={isSubmitting}
                >
                  Back to sign in
                </button>
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => setMode('reset')}
                  disabled={isSubmitting}
                >
                  I already have a code
                </button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (mode === 'reset') {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-slate-50 to-slate-100">
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1 text-center">
            <div className="flex justify-center mb-2">
              <div className="p-3 bg-primary rounded-full">
                <Bot className="w-8 h-8 text-primary-foreground" />
              </div>
            </div>
            <CardTitle className="text-2xl">Enter Reset Code</CardTitle>
            <CardDescription>
              Enter the code sent to your email and choose a new password.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleResetPassword} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="user@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="resetCode">Reset Code</Label>
                <Input
                  id="resetCode"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  value={resetCode}
                  onChange={(e) => setResetCode(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="newPassword">New Password</Label>
                <Input
                  id="newPassword"
                  type="password"
                  placeholder="••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={isSubmitting}
                />
              </div>
              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Resetting password...
                  </>
                ) : (
                  'Reset Password'
                )}
              </Button>
              <div className="flex items-center justify-between text-sm">
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => setMode('signin')}
                  disabled={isSubmitting}
                >
                  Back to sign in
                </button>
                <button
                  type="button"
                  className="text-primary hover:underline"
                  onClick={() => handleForgotPassword({ preventDefault: () => {} } as React.FormEvent)}
                  disabled={isSubmitting}
                >
                  Resend code
                </button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-slate-50 to-slate-100">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1 text-center">
          <div className="flex justify-center mb-2">
            <div className="p-3 bg-primary rounded-full">
              <Bot className="w-8 h-8 text-primary-foreground" />
            </div>
          </div>
          <CardTitle className="text-2xl">AI Agent Platform</CardTitle>
          <CardDescription>
            Sign in to access intelligent AI agents
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isSubmitting}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isSubmitting}
              />
              <div className="flex justify-end">
                <button
                  type="button"
                  className="text-sm text-primary hover:underline"
                  onClick={() => setMode('forgot')}
                  disabled={isSubmitting}
                >
                  Forgot password?
                </button>
              </div>
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
