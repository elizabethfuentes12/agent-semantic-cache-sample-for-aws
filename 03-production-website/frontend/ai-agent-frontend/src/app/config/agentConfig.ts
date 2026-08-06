export interface AgentDefinition {
  path: string;
  name: string;
  agentId: string;
  description: string;
  target_arn?: string;
  agent_arn?: string;
  disabled?: boolean;
  /**
   * Cognito groups allowed to see this agent. When present and non-empty,
   * only users belonging to at least one of these groups can see the agent.
   * When absent or empty, the agent is visible to all users.
   */
  visibility?: string[];
}

/**
 * Determine whether an agent is visible to a user given the user's Cognito groups.
 *
 * - If the agent has no `visibility` array, or it is empty, the agent is visible to everyone.
 * - Otherwise the agent is only visible to users belonging to at least one of the listed groups.
 */
export function isAgentVisible(
  agent: AgentDefinition,
  userGroups: string[] = [],
): boolean {
  if (!Array.isArray(agent.visibility) || agent.visibility.length === 0) {
    return true;
  }
  return agent.visibility.some(group => userGroups.includes(group));
}

/**
 * Filter a list of agents down to those visible to a user with the given Cognito groups.
 */
export function filterVisibleAgents(
  agents: AgentDefinition[],
  userGroups: string[] = [],
): AgentDefinition[] {
  return agents.filter(agent => isAgentVisible(agent, userGroups));
}

const REQUIRED_FIELDS: (keyof AgentDefinition)[] = [
  'path',
  'name',
  'agentId',
  'description',
];

let cached: AgentDefinition[] | null = null;

export function getAgents(): AgentDefinition[] {
  if (cached) {
    console.log('[AgentConfig] Returning cached agents:', cached.map(a => a.name));
    return cached;
  }

  console.log('[AgentConfig] Loading agents from VITE_AGENT_LIST...');

  const raw = import.meta.env.VITE_AGENT_LIST;

  if (!raw || raw.trim() === '') {
    throw new Error('VITE_AGENT_LIST environment variable is not set');
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('VITE_AGENT_LIST is not valid JSON');
  }

  const obj = parsed as Record<string, unknown>;

  if (!Array.isArray(obj.agents) || obj.agents.length === 0) {
    throw new Error(
      "VITE_AGENT_LIST must contain a non-empty 'agents' array"
    );
  }

  for (const agent of obj.agents) {
    for (const field of REQUIRED_FIELDS) {
      if (
        typeof agent[field] !== 'string' ||
        (agent[field] as string).trim() === ''
      ) {
        throw new Error(
          `Each agent must have a non-empty '${field}' field`
        );
      }
    }

    if (
      agent.target_arn !== undefined &&
      (typeof agent.target_arn !== 'string' ||
        agent.target_arn.trim() === '')
    ) {
      throw new Error(
        "Agent 'target_arn', if present, must be a non-empty string"
      );
    }

    if (
      agent.agent_arn !== undefined &&
      (typeof agent.agent_arn !== 'string' ||
        agent.agent_arn.trim() === '')
    ) {
      throw new Error(
        "Agent 'agent_arn', if present, must be a non-empty string"
      );
    }

    if (
      agent.visibility !== undefined &&
      (!Array.isArray(agent.visibility) ||
        !agent.visibility.every(
          (g: unknown) => typeof g === 'string' && g.trim() !== ''
        ))
    ) {
      throw new Error(
        "Agent 'visibility', if present, must be an array of non-empty strings"
      );
    }
  }

  const allAgents = obj.agents as AgentDefinition[];
  cached = allAgents.filter(agent => !agent.disabled);
  console.log('[AgentConfig] Total agents:', allAgents.length, '| Enabled:', cached.length, '| Disabled:', allAgents.length - cached.length);
  console.log('[AgentConfig] Enabled agents:', cached.map(a => a.name));
  return cached;
}

/** Reset memoization cache — exposed for testing only. */
export function _resetCache(): void {
  cached = null;
}
