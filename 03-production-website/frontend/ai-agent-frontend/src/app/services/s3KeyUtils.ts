export function sanitizeFileName(fileName: string): string {
  const lastDotIndex = fileName.lastIndexOf('.');
  let name: string;
  let extension: string;

  if (lastDotIndex > 0) {
    name = fileName.substring(0, lastDotIndex);
    extension = fileName.substring(lastDotIndex + 1).replace(/[^a-zA-Z0-9]/g, '');
  } else {
    name = fileName;
    extension = '';
  }

  name = name.replace(/[^a-zA-Z0-9\-_]/g, '');

  if (name === '') {
    name = 'file';
  }

  return extension ? `${name}.${extension}` : name;
}

export function buildS3Key(userId: string, sessionId: string, fileName: string): string {
  const sanitizedName = sanitizeFileName(fileName);
  const timestamp = Date.now();
  const uuid = crypto.randomUUID();
  return `${userId}/${sessionId}/${timestamp}-${uuid}-${sanitizedName}`;
}
