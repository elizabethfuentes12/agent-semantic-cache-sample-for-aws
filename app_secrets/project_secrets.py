from aws_cdk import RemovalPolicy, SecretValue, aws_secretsmanager as sm
from constructs import Construct


class Secrets(Construct):
    """Third-party API credentials.

    The Duffel key is created EMPTY unless the DUFFEL_API_KEY environment
    variable is present at synth time (deploy-time convenience for a sample;
    in production, create the secret out-of-band and import it instead).
    """

    def __init__(self, scope: Construct, construct_id: str, *, duffel_key: str | None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if duffel_key:
            secret_value = SecretValue.unsafe_plain_text(duffel_key)
        else:
            # Placeholder — set the real value after deploy:
            # aws secretsmanager put-secret-value --secret-id <arn> --secret-string <key>
            secret_value = SecretValue.unsafe_plain_text("REPLACE_ME")

        self.duffel = sm.Secret(
            self,
            "DuffelApiKey",
            description="Duffel sandbox API key for the flight search tool",
            secret_string_value=secret_value,
        )
        self.duffel.apply_removal_policy(RemovalPolicy.DESTROY)
