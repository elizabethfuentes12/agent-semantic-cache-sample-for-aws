import { describe, it, expect } from 'vitest';
import {
  isAgentVisible,
  filterVisibleAgents,
  type AgentDefinition,
} from './agentConfig';

function makeAgent(overrides: Partial<AgentDefinition> = {}): AgentDefinition {
  return {
    path: '/agent',
    name: 'Test Agent',
    agentId: 'test-agent',
    description: 'An agent',
    ...overrides,
  };
}

describe('isAgentVisible', () => {
  it('is visible to everyone when visibility is absent', () => {
    const agent = makeAgent();
    expect(isAgentVisible(agent, [])).toBe(true);
    expect(isAgentVisible(agent, ['admin'])).toBe(true);
  });

  it('is visible to everyone when visibility is an empty array', () => {
    const agent = makeAgent({ visibility: [] });
    expect(isAgentVisible(agent, [])).toBe(true);
    expect(isAgentVisible(agent, ['user'])).toBe(true);
  });

  it('is visible only to users in a listed group', () => {
    const agent = makeAgent({ visibility: ['admin'] });
    expect(isAgentVisible(agent, ['admin'])).toBe(true);
    expect(isAgentVisible(agent, ['admin', 'other'])).toBe(true);
    expect(isAgentVisible(agent, ['user'])).toBe(false);
    expect(isAgentVisible(agent, [])).toBe(false);
  });

  it('matches when the user belongs to any one of several listed groups', () => {
    const agent = makeAgent({ visibility: ['admin', 'beta'] });
    expect(isAgentVisible(agent, ['beta'])).toBe(true);
    expect(isAgentVisible(agent, ['gamma'])).toBe(false);
  });

  it('defaults user groups to an empty list when omitted', () => {
    const restricted = makeAgent({ visibility: ['admin'] });
    const open = makeAgent();
    expect(isAgentVisible(restricted)).toBe(false);
    expect(isAgentVisible(open)).toBe(true);
  });
});

describe('filterVisibleAgents', () => {
  const open = makeAgent({ agentId: 'open', name: 'Open' });
  const adminOnly = makeAgent({ agentId: 'admin-only', name: 'Admin Only', visibility: ['admin'] });
  const betaOnly = makeAgent({ agentId: 'beta-only', name: 'Beta Only', visibility: ['beta'] });

  it('returns only agents visible to the user groups', () => {
    const result = filterVisibleAgents([open, adminOnly, betaOnly], ['admin']);
    expect(result.map(a => a.agentId)).toEqual(['open', 'admin-only']);
  });

  it('returns only open agents for a user with no groups', () => {
    const result = filterVisibleAgents([open, adminOnly, betaOnly], []);
    expect(result.map(a => a.agentId)).toEqual(['open']);
  });

  it('returns all matching agents for a user in multiple groups', () => {
    const result = filterVisibleAgents([open, adminOnly, betaOnly], ['admin', 'beta']);
    expect(result.map(a => a.agentId)).toEqual(['open', 'admin-only', 'beta-only']);
  });
});
