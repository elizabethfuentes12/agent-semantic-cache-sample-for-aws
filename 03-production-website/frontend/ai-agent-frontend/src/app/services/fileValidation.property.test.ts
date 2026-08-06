import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  validateFile,
  classifyFile,
  IMAGE_MIME_TYPES,
  DOCUMENT_MIME_TYPES,
  DOCUMENT_EXTENSIONS,
  MAX_FILE_SIZE,
  MAX_IMAGES_PER_SESSION,
  MAX_DOCUMENTS_PER_SESSION,
  type SessionFileCounts,
} from './fileValidation';

/** Helper to create a mock File with specific size and type. */
function createMockFile(name: string, size: number, type: string): File {
  const file = new File([''], name, { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

/** Arbitrary for a valid image MIME type. */
const imageMimeArb = fc.constantFrom(...IMAGE_MIME_TYPES);

/** Arbitrary for a valid document MIME type. */
const documentMimeArb = fc.constantFrom(...DOCUMENT_MIME_TYPES);

/** Arbitrary for any known (valid) MIME type. */
const knownMimeArb = fc.oneof(imageMimeArb, documentMimeArb);

/** Session counts that are well below limits. */
const safeCounts: SessionFileCounts = { images: 0, documents: 0 };

/**
 * Feature: s3-file-upload, Property 2: File size validation boundary
 *
 * **Validates: Requirements 3.1, 3.2**
 *
 * For any file size 0 or > MAX_FILE_SIZE (20 MB), validateFile returns { valid: false }.
 * For any file size between 1 and MAX_FILE_SIZE (inclusive) with valid MIME type and
 * session counts below limits, the size check passes.
 */
describe('Feature: s3-file-upload, Property 2: File size validation boundary', () => {
  it('rejects empty files (size === 0)', () => {
    fc.assert(
      fc.property(knownMimeArb, (mime) => {
        const file = createMockFile('test.bin', 0, mime);
        const result = validateFile(file, safeCounts);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
      }),
      { numRuns: 100 },
    );
  });

  it('rejects files exceeding MAX_FILE_SIZE', () => {
    const oversizeArb = fc.integer({ min: MAX_FILE_SIZE + 1, max: MAX_FILE_SIZE * 10 });

    fc.assert(
      fc.property(oversizeArb, knownMimeArb, (size, mime) => {
        const file = createMockFile('test.bin', size, mime);
        const result = validateFile(file, safeCounts);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
      }),
      { numRuns: 100 },
    );
  });

  it('accepts files with size between 1 and MAX_FILE_SIZE (inclusive) when other constraints are met', () => {
    const validSizeArb = fc.integer({ min: 1, max: MAX_FILE_SIZE });

    fc.assert(
      fc.property(validSizeArb, knownMimeArb, (size, mime) => {
        const file = createMockFile('test.bin', size, mime);
        const result = validateFile(file, safeCounts);
        expect(result.valid).toBe(true);
      }),
      { numRuns: 100 },
    );
  });
});


/**
 * Feature: s3-file-upload, Property 3: MIME type classification correctness
 *
 * **Validates: Requirements 3.3**
 *
 * For any MIME type in IMAGE_MIME_TYPES, classifyFile returns 'image'.
 * For any MIME type in DOCUMENT_MIME_TYPES, classifyFile returns 'document'.
 * For any arbitrary string NOT in either set, classifyFile returns 'unknown'.
 */
describe('Feature: s3-file-upload, Property 3: MIME type classification correctness', () => {
  it('classifies all image MIME types as image', () => {
    fc.assert(
      fc.property(imageMimeArb, (mime) => {
        expect(classifyFile(mime)).toBe('image');
      }),
      { numRuns: 100 },
    );
  });

  it('classifies all document MIME types as document', () => {
    fc.assert(
      fc.property(documentMimeArb, (mime) => {
        expect(classifyFile(mime)).toBe('document');
      }),
      { numRuns: 100 },
    );
  });

  it('classifies arbitrary strings not in either set as unknown', () => {
    const allKnown = new Set([...IMAGE_MIME_TYPES, ...DOCUMENT_MIME_TYPES]);
    const unknownMimeArb = fc.string().filter((s) => !allKnown.has(s));

    fc.assert(
      fc.property(unknownMimeArb, (mime) => {
        expect(classifyFile(mime)).toBe('unknown');
      }),
      { numRuns: 100 },
    );
  });

  it('classifies files with allowed extensions as document even when MIME is unknown', () => {
    const extArb = fc.constantFrom(...DOCUMENT_EXTENSIONS);

    fc.assert(
      fc.property(extArb, (ext) => {
        // Empty MIME → falls through to extension check
        expect(classifyFile('', `file.${ext}`)).toBe('document');
        // Unknown MIME → also falls through to extension check
        expect(classifyFile('application/octet-stream', `file.${ext}`)).toBe('document');
      }),
      { numRuns: 50 },
    );
  });
});

/**
 * Feature: s3-file-upload, Property 4: Session file limit enforcement
 *
 * **Validates: Requirements 3.4, 3.5**
 *
 * For image files with sessionCounts.images >= 20, validateFile returns { valid: false }.
 * For document files with sessionCounts.documents >= 5, validateFile returns { valid: false }.
 * For image files with sessionCounts.images < 20 (and valid size), session limit check passes.
 * For document files with sessionCounts.documents < 5 (and valid size), session limit check passes.
 */
describe('Feature: s3-file-upload, Property 4: Session file limit enforcement', () => {
  const validSize = 1024; // 1 KB — well within limits

  it('rejects image files when session image count >= MAX_IMAGES_PER_SESSION', () => {
    const atOrOverLimitArb = fc.integer({ min: MAX_IMAGES_PER_SESSION, max: MAX_IMAGES_PER_SESSION + 100 });

    fc.assert(
      fc.property(imageMimeArb, atOrOverLimitArb, (mime, imageCount) => {
        const file = createMockFile('photo.png', validSize, mime);
        const counts: SessionFileCounts = { images: imageCount, documents: 0 };
        const result = validateFile(file, counts);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
      }),
      { numRuns: 100 },
    );
  });

  it('rejects document files when session document count >= MAX_DOCUMENTS_PER_SESSION', () => {
    const atOrOverLimitArb = fc.integer({ min: MAX_DOCUMENTS_PER_SESSION, max: MAX_DOCUMENTS_PER_SESSION + 100 });

    fc.assert(
      fc.property(documentMimeArb, atOrOverLimitArb, (mime, docCount) => {
        const file = createMockFile('report.pdf', validSize, mime);
        const counts: SessionFileCounts = { images: 0, documents: docCount };
        const result = validateFile(file, counts);
        expect(result.valid).toBe(false);
        expect(result.error).toBeDefined();
      }),
      { numRuns: 100 },
    );
  });

  it('accepts image files when session image count < MAX_IMAGES_PER_SESSION', () => {
    const belowLimitArb = fc.integer({ min: 0, max: MAX_IMAGES_PER_SESSION - 1 });

    fc.assert(
      fc.property(imageMimeArb, belowLimitArb, (mime, imageCount) => {
        const file = createMockFile('photo.png', validSize, mime);
        const counts: SessionFileCounts = { images: imageCount, documents: 0 };
        const result = validateFile(file, counts);
        expect(result.valid).toBe(true);
      }),
      { numRuns: 100 },
    );
  });

  it('accepts document files when session document count < MAX_DOCUMENTS_PER_SESSION', () => {
    const belowLimitArb = fc.integer({ min: 0, max: MAX_DOCUMENTS_PER_SESSION - 1 });

    fc.assert(
      fc.property(documentMimeArb, belowLimitArb, (mime, docCount) => {
        const file = createMockFile('report.pdf', validSize, mime);
        const counts: SessionFileCounts = { images: 0, documents: docCount };
        const result = validateFile(file, counts);
        expect(result.valid).toBe(true);
      }),
      { numRuns: 100 },
    );
  });
});
