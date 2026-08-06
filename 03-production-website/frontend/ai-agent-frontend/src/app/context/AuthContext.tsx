import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
} from 'amazon-cognito-identity-js';
import { getCognitoConfig, mapCognitoAttributes } from '@/app/config/cognitoConfig';
import type { User } from '@/app/config/cognitoConfig';

interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  completeNewPassword: (newPassword: string) => Promise<void>;
  forgotPassword: (email: string) => Promise<void>;
  confirmForgotPassword: (email: string, code: string, newPassword: string) => Promise<void>;
  logout: () => void;
  getSession: () => Promise<CognitoUserSession>;
  isLoading: boolean;
  newPasswordRequired: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const config = getCognitoConfig();
const userPool = new CognitoUserPool({
  UserPoolId: config.userPoolId,
  ClientId: config.clientId,
});

function extractUserFromSession(session: CognitoUserSession): User {
  const payload = session.getIdToken().decodePayload();
  const rawGroups = payload['cognito:groups'];
  const groups = Array.isArray(rawGroups) ? (rawGroups as string[]) : [];
  return mapCognitoAttributes({
    sub: payload.sub,
    email: payload.email,
    name: payload.name,
    groups,
  });
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [newPasswordRequired, setNewPasswordRequired] = useState(false);
  const [challengeUser, setChallengeUser] = useState<CognitoUser | null>(null);
  const [challengeAttributes, setChallengeAttributes] = useState<Record<string, string>>({});

  // Session restore on mount
  useEffect(() => {
    const currentUser = userPool.getCurrentUser();
    if (!currentUser) {
      setIsLoading(false);
      return;
    }

    currentUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session || !session.isValid()) {
        setUser(null);
      } else {
        setUser(extractUserFromSession(session));
      }
      setIsLoading(false);
    });
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<void> => {
    const cognitoUser = new CognitoUser({
      Username: email,
      Pool: userPool,
    });

    const authDetails = new AuthenticationDetails({
      Username: email,
      Password: password,
    });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.authenticateUser(authDetails, {
        onSuccess: (session: CognitoUserSession) => {
          setNewPasswordRequired(false);
          setChallengeUser(null);
          setUser(extractUserFromSession(session));
          resolve();
        },
        onFailure: (err: Error) => {
          if (err.message === 'Network error' || err.message?.includes('fetch')) {
            reject(new Error('Unable to connect. Please check your internet connection.'));
          } else {
            reject(err);
          }
        },
        newPasswordRequired: (userAttributes: Record<string, string>) => {
          setChallengeUser(cognitoUser);
          setChallengeAttributes(userAttributes);
          setNewPasswordRequired(true);
          resolve();
        },
      });
    });
  }, []);

  const logout = useCallback(() => {
    const currentUser = userPool.getCurrentUser();
    if (currentUser) {
      currentUser.signOut();
    }
    setUser(null);
    setNewPasswordRequired(false);
    setChallengeUser(null);
  }, []);

  const completeNewPassword = useCallback(async (newPassword: string): Promise<void> => {
    if (!challengeUser) {
      throw new Error('No pending password challenge');
    }

    return new Promise<void>((resolve, reject) => {
      // Remove non-writable attributes that Cognito returns but doesn't accept back
      const { email_verified, email, ...writableAttributes } = challengeAttributes;
      void email_verified;
      void email;

      challengeUser.completeNewPasswordChallenge(newPassword, writableAttributes, {
        onSuccess: (session: CognitoUserSession) => {
          setNewPasswordRequired(false);
          setChallengeUser(null);
          setUser(extractUserFromSession(session));
          resolve();
        },
        onFailure: (err: Error) => {
          reject(err);
        },
      });
    });
  }, [challengeUser, challengeAttributes]);

  const forgotPassword = useCallback(async (email: string): Promise<void> => {
    const cognitoUser = new CognitoUser({
      Username: email,
      Pool: userPool,
    });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.forgotPassword({
        onSuccess: () => resolve(),
        onFailure: (err: Error) => {
          if (err.message === 'Network error' || err.message?.includes('fetch')) {
            reject(new Error('Unable to connect. Please check your internet connection.'));
          } else {
            reject(err);
          }
        },
      });
    });
  }, []);

  const confirmForgotPassword = useCallback(async (
    email: string,
    code: string,
    newPassword: string,
  ): Promise<void> => {
    const cognitoUser = new CognitoUser({
      Username: email,
      Pool: userPool,
    });

    return new Promise<void>((resolve, reject) => {
      cognitoUser.confirmPassword(code, newPassword, {
        onSuccess: () => resolve(),
        onFailure: (err: Error) => {
          if (err.message === 'Network error' || err.message?.includes('fetch')) {
            reject(new Error('Unable to connect. Please check your internet connection.'));
          } else {
            reject(err);
          }
        },
      });
    });
  }, []);

  const getSession = useCallback((): Promise<CognitoUserSession> => {
    return new Promise((resolve, reject) => {
      const currentUser = userPool.getCurrentUser();
      if (!currentUser) {
        reject(new Error('No authenticated user'));
        return;
      }
      currentUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
        if (err) {
          reject(err);
        } else if (!session) {
          reject(new Error('No session available'));
        } else {
          resolve(session);
        }
      });
    });
  }, []);

  return (
    <AuthContext.Provider value={{ user, login, completeNewPassword, forgotPassword, confirmForgotPassword, logout, getSession, isLoading, newPasswordRequired }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
