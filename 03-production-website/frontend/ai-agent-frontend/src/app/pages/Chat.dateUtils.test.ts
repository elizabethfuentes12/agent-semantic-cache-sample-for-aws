import { describe, it, expect, vi, afterEach } from 'vitest';
import { formatConversationDate, getErrorMessage } from './Chat';
import { ChatServiceError } from '@/app/services/chatService';

describe('formatConversationDate', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns "Today" for a date that is today', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2025, 0, 15, 14, 30, 0));

    const todayMorning = new Date(2025, 0, 15, 8, 0, 0);
    expect(formatConversationDate(todayMorning)).toBe('Today');
  });

  it('returns "Yesterday" for a date that is yesterday', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2025, 0, 15, 14, 30, 0));

    const yesterday = new Date(2025, 0, 14, 20, 0, 0);
    expect(formatConversationDate(yesterday)).toBe('Yesterday');
  });

  it('returns a locale-formatted date string for older dates', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2025, 0, 15, 14, 30, 0));

    const olderDate = new Date(2025, 0, 10, 12, 0, 0);
    const result = formatConversationDate(olderDate);

    // Should not be "Today" or "Yesterday"
    expect(result).not.toBe('Today');
    expect(result).not.toBe('Yesterday');

    // Should match the locale date string
    expect(result).toBe(olderDate.toLocaleDateString());
  });

  it('returns "Today" even for a date at the very start of today (midnight)', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2025, 0, 15, 23, 59, 59));

    const todayMidnight = new Date(2025, 0, 15, 0, 0, 0);
    expect(formatConversationDate(todayMidnight)).toBe('Today');
  });

  it('returns "Yesterday" for a date at the end of yesterday', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2025, 0, 15, 0, 0, 1));

    const yesterdayLate = new Date(2025, 0, 14, 23, 59, 59);
    expect(formatConversationDate(yesterdayLate)).toBe('Yesterday');
  });

  it('returns locale date for a date two days ago', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2025, 0, 15, 14, 30, 0));

    const twoDaysAgo = new Date(2025, 0, 13, 12, 0, 0);
    const result = formatConversationDate(twoDaysAgo);
    expect(result).toBe(twoDaysAgo.toLocaleDateString());
  });
});


describe('getErrorMessage', () => {
  it('returns "Invalid request parameters" for ChatServiceError with statusCode 400', () => {
    const err = new ChatServiceError('some message', 400);
    expect(getErrorMessage(err, 'fallback')).toBe('Invalid request parameters');
  });

  it('returns "Conversation not found" for ChatServiceError with statusCode 404', () => {
    const err = new ChatServiceError('some message', 404);
    expect(getErrorMessage(err, 'fallback')).toBe('Conversation not found');
  });

  it('returns "Server error, please try again" for ChatServiceError with statusCode 500', () => {
    const err = new ChatServiceError('some message', 500);
    expect(getErrorMessage(err, 'fallback')).toBe('Server error, please try again');
  });

  it('returns the error message for ChatServiceError with unknown statusCode', () => {
    const err = new ChatServiceError('Custom error', 503);
    expect(getErrorMessage(err, 'fallback')).toBe('Custom error');
  });

  it('returns the error message for a generic Error', () => {
    const err = new Error('Network failure');
    expect(getErrorMessage(err, 'fallback')).toBe('Network failure');
  });

  it('returns the fallback for a non-Error value', () => {
    expect(getErrorMessage('string error', 'fallback message')).toBe('fallback message');
  });

  it('returns the fallback for null', () => {
    expect(getErrorMessage(null, 'fallback message')).toBe('fallback message');
  });

  it('returns the fallback for undefined', () => {
    expect(getErrorMessage(undefined, 'fallback message')).toBe('fallback message');
  });
});
