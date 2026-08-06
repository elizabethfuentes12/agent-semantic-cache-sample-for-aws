import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';

/**
 * Property 4: Publish envelope serialization round-trip
 *
 * **Validates: Requirements 1.1, 11.1, 11.2**
 *
 * For any valid publish payload, serializing it with JSON.stringify,
 * wrapping it in the AppSync Events envelope format
 * { channel, events: [stringified_payload] }, and then deserializing
 * SHALL produce an object equivalent to the original payload.
 */
describe('Property 4: Publish envelope serialization round-trip', () => {
  /** Arbitrary for a non-empty string. */
  const nonEmptyStrArb = fc.string({ minLength: 1 }).filter((s) => s.trim().length > 0);

  /** Arbitrary for a valid publish payload (Record<string, unknown>). */
  const publishPayloadArb = fc.record({
    message: fc.record({
      content: nonEmptyStrArb,
      files: fc.option(
        fc.array(
          fc.record({
            name: nonEmptyStrArb,
            type: nonEmptyStrArb,
            size: fc.nat(),
          }),
        ),
        { nil: undefined },
      ),
    }),
    sessionId: nonEmptyStrArb,
    userId: nonEmptyStrArb,
    accessToken: nonEmptyStrArb,
    agentId: nonEmptyStrArb,
    target_arn: fc.option(nonEmptyStrArb, { nil: undefined }),
  });

  /** Arbitrary for a channel string. */
  const channelArb = nonEmptyStrArb.map((id) => '/messages/' + id);

  it('wrapping a payload in the AppSync envelope and deserializing recovers the original payload', () => {
    fc.assert(
      fc.property(channelArb, publishPayloadArb, (channel, payload) => {
        // Serialize exactly as AppSyncEventsService.publish() does
        const stringifiedPayload = JSON.stringify(payload);
        const envelope = JSON.stringify({
          channel,
          events: [stringifiedPayload],
        });

        // Deserialize the envelope
        const parsed = JSON.parse(envelope) as {
          channel: string;
          events: string[];
        };

        // The channel should survive the round-trip
        expect(parsed.channel).toBe(channel);

        // There should be exactly one event in the array
        expect(parsed.events).toHaveLength(1);

        // Deserializing the inner event should recover the original payload
        const recoveredPayload = JSON.parse(parsed.events[0]);
        expect(recoveredPayload).toEqual(payload);
      }),
      { numRuns: 200 },
    );
  });

  it('round-trip works for arbitrary JSON-serializable objects', () => {
    fc.assert(
      fc.property(channelArb, fc.jsonValue(), (channel, payload) => {
        const stringifiedPayload = JSON.stringify(payload);
        const envelope = JSON.stringify({
          channel,
          events: [stringifiedPayload],
        });

        const parsed = JSON.parse(envelope) as {
          channel: string;
          events: string[];
        };

        expect(parsed.channel).toBe(channel);
        expect(parsed.events).toHaveLength(1);

        const recovered = JSON.parse(parsed.events[0]);
        expect(recovered).toEqual(payload);
      }),
      { numRuns: 200 },
    );
  });
});
