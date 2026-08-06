export interface ValidationResult {
  valid: boolean;
  error?: string;
}

export interface SessionFileCounts {
  images: number;
  documents: number;
}

export const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB
export const MAX_IMAGES_PER_SESSION = 20;
export const MAX_DOCUMENTS_PER_SESSION = 5;

export const IMAGE_MIME_TYPES = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
]);

export const DOCUMENT_MIME_TYPES = new Set([
  // PDF
  'application/pdf',
  // Text / markup
  'text/csv',
  'text/html',
  'text/plain',
  'text/markdown',
  // Word
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  // Excel
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  // PowerPoint
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  // Email
  'message/rfc822',
  // Calendar (.ics / .cal)
  'text/calendar',
]);

/** Extensions allowed as documents when the browser reports no MIME type. */
export const DOCUMENT_EXTENSIONS = new Set([
  'drawio',
  'eml',
  'ics',
  'cal',
]);

export function classifyFile(mimeType: string, fileName?: string): 'image' | 'document' | 'unknown' {
  if (IMAGE_MIME_TYPES.has(mimeType)) return 'image';
  if (DOCUMENT_MIME_TYPES.has(mimeType)) return 'document';

  // Fallback: check file extension for types browsers don't recognise
  if (fileName) {
    const ext = fileName.split('.').pop()?.toLowerCase();
    if (ext && DOCUMENT_EXTENSIONS.has(ext)) return 'document';
  }

  return 'unknown';
}

export function validateFile(file: File, sessionCounts: SessionFileCounts): ValidationResult {
  if (file.size === 0) {
    return { valid: false, error: 'File is empty' };
  }

  if (file.size > MAX_FILE_SIZE) {
    return { valid: false, error: 'File exceeds maximum size of 20 MB' };
  }

  const fileType = classifyFile(file.type, file.name);

  if (fileType === 'unknown') {
    return { valid: false, error: 'Unsupported file type' };
  }

  if (fileType === 'image' && sessionCounts.images >= MAX_IMAGES_PER_SESSION) {
    return { valid: false, error: 'Maximum of 20 images per session reached' };
  }

  if (fileType === 'document' && sessionCounts.documents >= MAX_DOCUMENTS_PER_SESSION) {
    return { valid: false, error: 'Maximum of 5 documents per session reached' };
  }

  return { valid: true };
}
