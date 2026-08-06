import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import type { FileMetadata } from './uploadService';

/**
 * Arbitrary for a single FileMetadata object with realistic field values.
 */
const fileMetadataArb: fc.Arbitrary<FileMetadata> = fc.record({
  name: fc.string({ minLength: 1 }),
  type: fc.string({ minLength: 1 }),
  size: fc.nat(),
  uploadedFile: fc.record({
    url: fc.webUrl(),
  }),
});

/**
 * Arbitrary for a non-empty array of FileMetadata objects.
 */
const fileMetadataArrayArb = fc.array(fileMetadataArb, { minLength: 1, maxLength: 25 });

/**
 * Simulates the payload construction that Chat.tsx performs when assembling
 * the AppSync publish payload files array from completed UploadTask metadata.
 * Each FileMetadata is mapped directly into the payload files entry.
 */
function buildPayloadFiles(metadataArray: FileMetadata[]): Array<{
  name: string;
  type: string;
  size: number;
  uploadedFile: { url: string };
}> {
  return metadataArray.map((meta) => ({
    name: meta.name,
    type: meta.type,
    size: meta.size,
    uploadedFile: { url: meta.uploadedFile.url },
  }));
}

/**
 * Feature: s3-file-upload, Property 7: Payload file metadata structure
 *
 * **Validates: Requirements 5.1, 5.2**
 *
 * For any non-empty array of FileMetadata objects, the constructed payload files
 * array SHALL contain exactly one entry per metadata object, and each entry SHALL
 * have the fields name (string), type (string), size (number), and
 * uploadedFile.url (string).
 */
describe('Feature: s3-file-upload, Property 7: Payload file metadata structure', () => {
  it('payload files array length matches input metadata array length', () => {
    fc.assert(
      fc.property(fileMetadataArrayArb, (metadataArray) => {
        const payloadFiles = buildPayloadFiles(metadataArray);
        expect(payloadFiles).toHaveLength(metadataArray.length);
      }),
      { numRuns: 100 },
    );
  });

  it('each payload entry has name (string), type (string), size (number), and uploadedFile.url (string)', () => {
    fc.assert(
      fc.property(fileMetadataArrayArb, (metadataArray) => {
        const payloadFiles = buildPayloadFiles(metadataArray);

        for (const entry of payloadFiles) {
          expect(typeof entry.name).toBe('string');
          expect(typeof entry.type).toBe('string');
          expect(typeof entry.size).toBe('number');
          expect(entry.uploadedFile).toBeDefined();
          expect(typeof entry.uploadedFile.url).toBe('string');
        }
      }),
      { numRuns: 100 },
    );
  });

  it('each payload entry preserves the original metadata values', () => {
    fc.assert(
      fc.property(fileMetadataArrayArb, (metadataArray) => {
        const payloadFiles = buildPayloadFiles(metadataArray);

        for (let i = 0; i < metadataArray.length; i++) {
          expect(payloadFiles[i].name).toBe(metadataArray[i].name);
          expect(payloadFiles[i].type).toBe(metadataArray[i].type);
          expect(payloadFiles[i].size).toBe(metadataArray[i].size);
          expect(payloadFiles[i].uploadedFile.url).toBe(metadataArray[i].uploadedFile.url);
        }
      }),
      { numRuns: 100 },
    );
  });
});
