import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import { sanitizeFileName, buildS3Key } from './s3KeyUtils';

/** Arbitrary for non-empty alphanumeric strings (valid userId / sessionId). */
const alphanumericArb = fc.stringMatching(/^[a-zA-Z0-9]+$/).filter((s) => s.length > 0);

/**
 * Feature: s3-file-upload, Property 1: S3 key structure invariant
 *
 * **Validates: Requirements 1.4**
 *
 * For any valid userId, sessionId, and fileName, buildS3Key produces a string
 * matching {userId}/{sessionId}/{timestamp}-{uuid}-{sanitizedName} where each
 * segment is non-empty and separated by `/`.
 */
describe('Feature: s3-file-upload, Property 1: S3 key structure invariant', () => {
  it('produces a key with exactly 2 slashes separating userId, sessionId, and file segment', () => {
    fc.assert(
      fc.property(alphanumericArb, alphanumericArb, fc.string({ minLength: 1 }), (userId, sessionId, fileName) => {
        const key = buildS3Key(userId, sessionId, fileName);
        const parts = key.split('/');
        expect(parts).toHaveLength(3);
        expect(parts[0]).toBe(userId);
        expect(parts[1]).toBe(sessionId);
        expect(parts[2].length).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });

  it('third segment contains timestamp, uuid, and sanitized name separated by hyphens', () => {
    // UUID v4 pattern: 8-4-4-4-12 hex chars
    const uuidPattern = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
    const fileSegmentRegex = new RegExp(`^(\\d+)-(${uuidPattern})-(.+)$`);

    fc.assert(
      fc.property(alphanumericArb, alphanumericArb, fc.string({ minLength: 1 }), (userId, sessionId, fileName) => {
        const key = buildS3Key(userId, sessionId, fileName);
        const fileSegment = key.split('/')[2];
        const match = fileSegment.match(fileSegmentRegex);
        expect(match).not.toBeNull();

        // Timestamp should be a valid number
        const timestamp = Number(match![1]);
        expect(Number.isFinite(timestamp)).toBe(true);
        expect(timestamp).toBeGreaterThan(0);

        // Sanitized name should match sanitizeFileName output
        const sanitizedName = match![3];
        expect(sanitizedName).toBe(sanitizeFileName(fileName));
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * Feature: s3-file-upload, Property 5: Sanitization output character set
 *
 * **Validates: Requirements 8.1**
 *
 * For any input string, sanitizeFileName produces output containing ONLY
 * alphanumeric characters, hyphens, underscores, and periods. Output is
 * always non-empty (fallback to 'file').
 */
describe('Feature: s3-file-upload, Property 5: Sanitization output character set', () => {
  const validCharsRegex = /^[a-zA-Z0-9\-_.]+$/;

  it('output contains only allowed characters for any input', () => {
    fc.assert(
      fc.property(fc.string(), (input) => {
        const result = sanitizeFileName(input);
        expect(result).toMatch(validCharsRegex);
      }),
      { numRuns: 100 },
    );
  });

  it('output is never empty', () => {
    fc.assert(
      fc.property(fc.string(), (input) => {
        const result = sanitizeFileName(input);
        expect(result.length).toBeGreaterThan(0);
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * Feature: s3-file-upload, Property 6: Extension preservation round-trip
 *
 * **Validates: Requirements 8.2, 8.4**
 *
 * For any file name with a valid extension (period followed by alphanumeric chars),
 * the extension is preserved after sanitization.
 */
describe('Feature: s3-file-upload, Property 6: Extension preservation round-trip', () => {
  it('preserves alphanumeric extensions through sanitization', () => {
    const nameArb = fc.string({ minLength: 1 });
    const extArb = fc.stringMatching(/^[a-zA-Z0-9]+$/).filter((s) => s.length > 0);

    fc.assert(
      fc.property(nameArb, extArb, (name, ext) => {
        const input = `${name}.${ext}`;
        const result = sanitizeFileName(input);

        // Extract extension from result (after last dot)
        const lastDot = result.lastIndexOf('.');
        expect(lastDot).toBeGreaterThan(-1);

        const resultExt = result.substring(lastDot + 1);
        expect(resultExt).toBe(ext);
      }),
      { numRuns: 100 },
    );
  });
});
