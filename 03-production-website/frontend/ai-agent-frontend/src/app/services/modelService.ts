import { SSMClient, GetParameterCommand } from '@aws-sdk/client-ssm';
import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers';
import type { ModelDefinition } from '@/app/config/modelConfig';
import { getCognitoConfig } from '@/app/config/cognitoConfig';
import { getUploadConfig } from '@/app/config/uploadConfig';

const SSM_PARAM_NAME = '/models/website';

let cached: ModelDefinition[] | null = null;

export async function fetchModelsFromSSM(
  getIdToken: () => Promise<string>,
): Promise<ModelDefinition[]> {
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
  const models: ModelDefinition[] = parsed.models ?? parsed;

  if (!Array.isArray(models) || models.length === 0) {
    throw new Error(`SSM parameter ${SSM_PARAM_NAME} must contain a non-empty models array`);
  }

  cached = models;
  return models;
}

export function resetModelCache(): void {
  cached = null;
}
