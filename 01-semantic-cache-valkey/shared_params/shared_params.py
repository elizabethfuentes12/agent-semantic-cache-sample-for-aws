from aws_cdk import aws_ssm as ssm
from constructs import Construct

PREFIX = "/semantic-cache"


class SharedParams(Construct):
    """SSM Parameter Store contract between stacks.

    Stack 01 writes these at deploy time; stacks 02 (production agent) and
    03 (website) read them at synth time via get_param.py or at runtime via
    boto3. SSM is the only coupling between the numbered stacks.
    """

    def __init__(self, scope: Construct, construct_id: str, *, values: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        for name, value in values.items():
            ssm.StringParameter(
                self,
                name.replace("/", "-"),
                parameter_name=f"{PREFIX}/{name}",
                string_value=value,
            )
