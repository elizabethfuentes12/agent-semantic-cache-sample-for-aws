import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';
import { getCognitoConfig, mapCognitoAttributes } from './cognitoConfig';

/**
 * Feature: cognito-authentication, Property 1: Missing config throws identifying error
 *
 * **Validates: Requirements 1.3**
 *
 * For any non-empty subset of the three required Cognito config keys that is
 * missing or set to an empty string, getCognitoConfig() shall throw an error
 * whose message contains the name of every missing variable.
 */

const ALL_KEYS = [
  'VITE_COGNITO_USER_POOL_ID',
  'VITE_COGNITO_CLIENT_ID',
  'VITE_COGNITO_REGION',
] as const;

/** Arbitrary that produces a non-empty subset of the config keys to mark as missing. */
const missingKeysArb = fc
  .subarray([...ALL_KEYS], { minLength: 1 })
  .filter((arr) => arr.length > 0);

/** Arbitrary for a non-empty, non-whitespace-only string to use as a valid env value. */
const validValueArb = fc.string({ minLength: 1 }).filter((s) => s.trim().length > 0);

/**
 * Arbitrary that decides whether a "missing" key is represented by an empty
 * string or by a whitespace-only string — both should be treated as missing.
 */
const emptyValueArb = fc.oneof(fc.constant(''), fc.constant('   '));

describe('Property 1: Missing config throws identifying error', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('getCognitoConfig() throws an error naming every missing/empty key', () => {
    fc.assert(
      fc.property(
        missingKeysArb,
        validValueArb,
        emptyValueArb,
        (missingKeys, validValue, emptyValue) => {
          // Set up env: present keys get a valid value, missing keys get empty/whitespace
          for (const key of ALL_KEYS) {
            if (missingKeys.includes(key)) {
              vi.stubEnv(key, emptyValue);
            } else {
              vi.stubEnv(key, validValue);
            }
          }

          // getCognitoConfig() must throw
          let thrownError: Error | undefined;
          try {
            getCognitoConfig();
          } catch (e) {
            thrownError = e as Error;
          }

          expect(thrownError).toBeDefined();

          // The error message must contain every missing key name
          for (const key of missingKeys) {
            expect(thrownError!.message).toContain(key);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

/**
 * Feature: cognito-authentication, Property 2: User attribute mapping round-trip
 *
 * **Validates: Requirements 3.3, 7.1, 7.2, 7.3, 7.4**
 *
 * For any set of Cognito ID token attributes containing a `sub` (non-empty string)
 * and `email` (valid email string), and an optional `name` (string or absent),
 * the mapping function shall produce a User object where:
 * - `id` equals the `sub` value
 * - `email` equals the `email` value
 * - `name` equals the `name` value when present and non-empty, or the portion of
 *   `email` before the `@` symbol when `name` is absent or empty
 */

/** Arbitrary for a non-empty sub string. */
const subArb = fc.string({ minLength: 1 }).filter((s) => s.trim().length > 0);

/** Arbitrary for a valid email: non-empty local part + '@' + non-empty domain. */
const emailArb = fc
  .tuple(
    fc.string({ minLength: 1 }).filter((s) => !s.includes('@') && s.trim().length > 0),
    fc.string({ minLength: 1 }).filter((s) => !s.includes('@') && s.trim().length > 0),
  )
  .map(([local, domain]) => `${local}@${domain}`);

/** Arbitrary for an optional name: either a non-empty string, an empty string, or undefined. */
const optionalNameArb = fc.oneof(
  fc.string({ minLength: 1 }).filter((s) => s.length > 0),
  fc.constant(''),
  fc.constant(undefined),
);

describe('Property 2: User attribute mapping round-trip', () => {
  it('mapCognitoAttributes produces correct User object for any valid attributes', () => {
    fc.assert(
      fc.property(
        subArb,
        emailArb,
        optionalNameArb,
        (sub, email, name) => {
          const attrs: { sub: string; email: string; name?: string } =
            name !== undefined ? { sub, email, name } : { sub, email };

          const user = mapCognitoAttributes(attrs);

          // id equals sub
          expect(user.id).toBe(sub);

          // email equals input email
          expect(user.email).toBe(email);

          // name logic: present and non-empty → use name; otherwise → email prefix
          if (name !== undefined && name !== '') {
            expect(user.name).toBe(name);
          } else {
            expect(user.name).toBe(email.split('@')[0]);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});
