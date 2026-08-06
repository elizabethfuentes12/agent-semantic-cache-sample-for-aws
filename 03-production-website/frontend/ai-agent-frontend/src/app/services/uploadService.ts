import { S3Client, PutObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3';
import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers';
import { buildS3Key } from './s3KeyUtils';

export interface FileMetadata {
  name: string;
  type: string;
  size: number;
  uploadedFile: { url: string };
}

/**
 * Compact attachment metadata as persisted with a message and returned by the
 * backend when a conversation is reopened. Unlike {@link FileMetadata}, this
 * does not hold an in-memory File — only the info needed to render a chip and
 * re-download the object from S3.
 */
export interface MessageAttachment {
  name: string;
  url: string;
  type?: string;
  size?: number;
}

export interface UploadTask {
  file: File;
  status: 'pending' | 'uploading' | 'success' | 'error';
  progress: number;
  metadata?: FileMetadata;
  error?: string;
  abort: () => void;
}

export interface UploadServiceConfig {
  region: string;
  identityPoolId: string;
  bucket: string;
  userPoolId: string;
  getIdToken: () => Promise<string>;
}

const RETRY_DELAYS = [1000, 2000, 4000];

function isAuthError(error: unknown): boolean {
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    const name = error.name.toLowerCase();
    return (
      name.includes('credentials') ||
      name.includes('notauthorized') ||
      name.includes('expired') ||
      msg.includes('credentials') ||
      msg.includes('not authorized') ||
      msg.includes('token has expired') ||
      msg.includes('security token') ||
      msg.includes('expired token')
    );
  }
  return false;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });
}

export class UploadService {
  private config: UploadServiceConfig;

  constructor(config: UploadServiceConfig) {
    this.config = config;
  }

  private createS3Client(idToken: string): S3Client {
    return new S3Client({
      region: this.config.region,
      useAccelerateEndpoint: true,
      credentials: fromCognitoIdentityPool({
        clientConfig: { region: this.config.region },
        identityPoolId: this.config.identityPoolId,
        logins: {
          [`cognito-idp.${this.config.region}.amazonaws.com/${this.config.userPoolId}`]: idToken,
        },
      }),
    });
  }

  private async executeUpload(
    client: S3Client,
    key: string,
    file: File,
    signal?: AbortSignal,
  ): Promise<void> {
    const body = new Uint8Array(await file.arrayBuffer());
    const command = new PutObjectCommand({
      Bucket: this.config.bucket,
      Key: key,
      Body: body,
      ContentType: file.type,
    });
    await client.send(command, { abortSignal: signal });
  }

  async upload(
    file: File,
    userId: string,
    sessionId: string,
    onProgress: (pct: number) => void,
    signal?: AbortSignal,
  ): Promise<FileMetadata> {
    const key = buildS3Key(userId, sessionId, file.name);
    console.log('[Upload] Starting upload', { fileName: file.name, key, bucket: this.config.bucket, userId, sessionId });
    let idToken = await this.config.getIdToken();
    console.log('[Upload] Got ID token, length:', idToken.length);
    let client = this.createS3Client(idToken);

    onProgress(0);

    // First attempt — with auth retry
    try {
      await this.executeUpload(client, key, file, signal);
    } catch (error: unknown) {
      console.error('[Upload] First attempt failed:', error);
      if (isAuthError(error)) {
        console.log('[Upload] Auth error detected, refreshing token...');
        // Refresh token and retry once
        idToken = await this.config.getIdToken();
        client = this.createS3Client(idToken);
        try {
          await this.executeUpload(client, key, file, signal);
        } catch (retryError: unknown) {
          console.error('[Upload] Auth retry failed:', retryError);
          // Auth retry failed — fall through to exponential backoff
          return this.retryWithBackoff(client, key, file, signal, onProgress, retryError);
        }
      } else {
        console.log('[Upload] Non-auth error, starting backoff retries...');
        // Non-auth error — exponential backoff
        return this.retryWithBackoff(client, key, file, signal, onProgress, error);
      }
    }

    console.log('[Upload] Upload successful!', { key });
    onProgress(100);
    return this.buildMetadata(file, key);
  }

  private async retryWithBackoff(
    client: S3Client,
    key: string,
    file: File,
    signal: AbortSignal | undefined,
    onProgress: (pct: number) => void,
    lastError: unknown,
  ): Promise<FileMetadata> {
    for (let attempt = 0; attempt < RETRY_DELAYS.length; attempt++) {
      await delay(RETRY_DELAYS[attempt], signal);
      try {
        await this.executeUpload(client, key, file, signal);
        onProgress(100);
        return this.buildMetadata(file, key);
      } catch (error: unknown) {
        lastError = error;
      }
    }
    throw lastError;
  }

  private buildMetadata(file: File, key: string): FileMetadata {
    const url = `https://${this.config.bucket}.s3.${this.config.region}.amazonaws.com/${key}`;
    return {
      name: file.name,
      type: file.type,
      size: file.size,
      uploadedFile: { url },
    };
  }

  /**
   * Derives the S3 object key from a stored attachment URL of the form
   * `https://{bucket}.s3.{region}.amazonaws.com/{key}`. Keys are ASCII-safe
   * (see buildS3Key) but we decode defensively in case of encoded segments.
   */
  private keyFromUrl(url: string): string {
    try {
      const parsed = new URL(url);
      return decodeURIComponent(parsed.pathname.replace(/^\/+/, ''));
    } catch {
      // Not a full URL — assume it's already a key.
      return url.replace(/^\/+/, '');
    }
  }

  /**
   * Fetches a previously uploaded object from S3 (using the same Cognito
   * credentials as upload) and triggers a browser download. Used to
   * re-download attachments from historical messages, where the bucket is
   * private and a direct link would not be accessible.
   */
  async download(url: string, fileName: string, signal?: AbortSignal): Promise<void> {
    const idToken = await this.config.getIdToken();
    const client = this.createS3Client(idToken);
    const key = this.keyFromUrl(url);

    const command = new GetObjectCommand({
      Bucket: this.config.bucket,
      Key: key,
    });
    const response = await client.send(command, { abortSignal: signal });

    if (!response.Body) {
      throw new Error('Empty response body from S3');
    }

    // transformToByteArray is provided by the SDK's browser stream mixin.
    const bytes = await (response.Body as unknown as {
      transformToByteArray: () => Promise<Uint8Array>;
    }).transformToByteArray();

    const blob = new Blob([bytes], {
      type: response.ContentType || 'application/octet-stream',
    });
    const blobUrl = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement('a');
      anchor.href = blobUrl;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
  }
}
