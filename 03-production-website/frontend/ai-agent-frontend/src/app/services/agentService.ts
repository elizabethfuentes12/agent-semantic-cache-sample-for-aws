import { SSMClient, GetParameterCommand } from '@aws-sdk/client-ssm';
import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers';
import type { AgentDefinition } from '@/app/config/agentConfig';
import { getCognitoConfig } from '@/app/config/cognitoConfig';
import { getUploadConfig } from '@/app/config/uploadConfig';

const SSM_PARAM_NAME = '/agents/website';

let cached: AgentDefinition[] | null = null;

export async function fetchAgentsFromSSM(
  getIdToken: () => Promise<string>,
): Promise<AgentDefinition[]> {
  if (cached) return cached;

  const cognitoConfig = getCognitoConfig();
  const uploadConfig = getUploadConfig();
  const idToken = await getIdToken();

  const ssmClient = new SSMClient({
    region: uploadConfig.region,
    credentials: fromCognitoIdentityPool({
      clientConfig: { region: uploadConfig.region },
      identityPoolId: uploadConfig.identityPoolId,
      logins: {
        [`cognito-idp.${cognitoConfig.region}.amazonaws.com/${cognitoConfig.userPoolId}`]: idToken,
      },
    }),
  });

  const response = await ssmClient.send(
    new GetParameterCommand({
      Name: SSM_PARAM_NAME,
      WithDecryption: true,
    }),
  );

  const raw = response.Parameter?.Value;
  if (!raw) {
    throw new Error(`SSM parameter ${SSM_PARAM_NAME} is empty or not found`);
  }

  const parsed = JSON.parse(raw);
  const agents: AgentDefinition[] = parsed.agents ?? parsed;

  if (!Array.isArray(agents) || agents.length === 0) {
    throw new Error(`SSM parameter ${SSM_PARAM_NAME} must contain a non-empty agents array`);
  }

  // Filter out disabled agents (disabled defaults to false if not present)
  const enabledAgents = agents.filter(agent => !agent.disabled);
  console.log('[AgentService] Total agents:', agents.length, '| Enabled:', enabledAgents.length, '| Agents:', enabledAgents.map(a => a.name));

  cached = enabledAgents;
  return enabledAgents;
}

export function resetAgentCache(): void {
  cached = null;
}
