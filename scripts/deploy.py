#!/usr/bin/env python3
"""Deploy SCADS to AWS using boto3 and CloudFormation.

No AWS CLI and no SAM CLI. CloudFormation applies the
``AWS::Serverless-2016-10-31`` transform server-side, so a SAM template deploys
through ``create_change_set`` with ``CAPABILITY_AUTO_EXPAND`` — the CLIs are a
convenience, not a requirement. This project's environment has neither, so the
deployment path is built on the SDK that is actually present.

Steps:

    1. build the Lambda package (scripts/package_lambda.py)
    2. upload it to an artifact bucket, creating the bucket if needed
    3. create and execute a CloudFormation change set
    4. write apps/web/config.js with the live API URL
    5. seed the registry and references
    6. run the smoke test against the deployed API

Usage::

    python scripts/deploy.py --region ap-south-1
    python scripts/deploy.py --plan          # show the change set, do not apply
    python scripts/deploy.py --skip-build    # reuse the existing package
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TEMPLATE = os.path.join(ROOT, "infra", "template.yaml")
ZIP_PATH = os.path.join(ROOT, ".build", "scads-api.zip")
WEB_CONFIG = os.path.join(ROOT, "apps", "web", "config.js")

# CloudFormation states that mean "finished", successfully or not.
_TERMINAL = (
    "CREATE_COMPLETE", "UPDATE_COMPLETE", "DELETE_COMPLETE",
    "CREATE_FAILED", "ROLLBACK_COMPLETE", "ROLLBACK_FAILED",
    "UPDATE_ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED", "DELETE_FAILED",
)
_SUCCESS = ("CREATE_COMPLETE", "UPDATE_COMPLETE")


def boto3_or_exit():
    try:
        import boto3  # noqa: WPS433
        return boto3
    except ImportError:
        print(
            "boto3 is required to deploy.\n    pip install boto3",
            file=sys.stderr,
        )
        raise SystemExit(2)


def build_package() -> None:
    print("[1/6] building the Lambda package")
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "package_lambda.py"), "--zip"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise SystemExit("package build failed")


def ensure_artifact_bucket(boto3, region: str, account_id: str, name: Optional[str]) -> str:
    """Create (or confirm) the bucket that holds deployment artifacts."""
    bucket = name or "scads-artifacts-%s-%s" % (region, account_id)
    s3 = boto3.client("s3", region_name=region)
    try:
        s3.head_bucket(Bucket=bucket)
        return bucket
    except Exception:
        pass

    print("      creating artifact bucket %s" % bucket)
    kwargs: Dict[str, Any] = {"Bucket": bucket}
    # us-east-1 rejects an explicit LocationConstraint; every other region
    # requires one.
    if region != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    return bucket


def upload_artifact(boto3, region: str, bucket: str) -> str:
    """Upload the package under a content-addressed key.

    Content addressing means an unchanged package produces an unchanged key,
    so CloudFormation sees no code change and skips replacing the function.
    """
    with open(ZIP_PATH, "rb") as handle:
        payload = handle.read()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    key = "lambda/scads-api-%s.zip" % digest

    s3 = boto3.client("s3", region_name=region)
    try:
        s3.head_object(Bucket=bucket, Key=key)
        print("      artifact already uploaded (%s)" % key)
        return key
    except Exception:
        pass

    print("      uploading %.1f MB -> s3://%s/%s" % (len(payload) / 1048576.0, bucket, key))
    s3.put_object(Bucket=bucket, Key=key, Body=payload, ServerSideEncryption="AES256")
    return key


def stack_exists(cfn, stack_name: str) -> bool:
    try:
        response = cfn.describe_stacks(StackName=stack_name)
    except Exception:
        return False
    status = response["Stacks"][0]["StackStatus"]
    if status == "REVIEW_IN_PROGRESS":
        # A create change set was made but never executed; treat it as absent.
        return False
    return True


def deploy_stack(
    boto3, region: str, stack_name: str, parameters: Dict[str, str], plan_only: bool
) -> Dict[str, str]:
    cfn = boto3.client("cloudformation", region_name=region)

    with open(TEMPLATE, "r", encoding="utf-8") as handle:
        template_body = handle.read()

    exists = stack_exists(cfn, stack_name)
    change_set_type = "UPDATE" if exists else "CREATE"
    change_set_name = "scads-%s" % _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H%M%S")

    print("[3/6] %s change set %s" % (change_set_type.lower(), change_set_name))
    cfn.create_change_set(
        StackName=stack_name,
        TemplateBody=template_body,
        Parameters=[{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()],
        # AUTO_EXPAND is what applies the SAM transform. IAM capabilities are
        # needed because the template creates the function's execution role.
        Capabilities=["CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND"],
        ChangeSetName=change_set_name,
        ChangeSetType=change_set_type,
        Description="SCADS deployment",
    )

    status = _wait_for_change_set(cfn, stack_name, change_set_name)
    if status == "EMPTY":
        print("      no changes to apply")
        return _outputs(cfn, stack_name)

    _print_changes(cfn, stack_name, change_set_name)

    if plan_only:
        print("\n--plan given; change set left unexecuted:")
        print("      %s" % change_set_name)
        return {}

    print("[4/6] executing change set")
    cfn.execute_change_set(StackName=stack_name, ChangeSetName=change_set_name)
    _wait_for_stack(cfn, stack_name)
    return _outputs(cfn, stack_name)


def _wait_for_change_set(cfn, stack_name: str, change_set_name: str) -> str:
    while True:
        response = cfn.describe_change_set(StackName=stack_name, ChangeSetName=change_set_name)
        status = response["Status"]
        if status == "FAILED":
            reason = response.get("StatusReason", "")
            # A change set with nothing to do fails with a specific reason;
            # that is success, not an error.
            if "didn't contain changes" in reason or "No updates" in reason:
                return "EMPTY"
            raise SystemExit("change set failed: " + reason)
        if status == "CREATE_COMPLETE":
            return status
        time.sleep(3)


def _print_changes(cfn, stack_name: str, change_set_name: str) -> None:
    response = cfn.describe_change_set(StackName=stack_name, ChangeSetName=change_set_name)
    changes = response.get("Changes", [])
    if not changes:
        return
    print("      %d resource change(s):" % len(changes))
    for change in changes[:40]:
        detail = change.get("ResourceChange", {})
        replacement = detail.get("Replacement", "")
        print(
            "        %-8s %-34s %s%s"
            % (
                detail.get("Action", "?"),
                detail.get("LogicalResourceId", "?"),
                detail.get("ResourceType", "?"),
                "  [REPLACEMENT]" if replacement == "True" else "",
            )
        )


def _wait_for_stack(cfn, stack_name: str) -> None:
    started = time.time()
    seen = set()
    while True:
        response = cfn.describe_stacks(StackName=stack_name)
        status = response["Stacks"][0]["StackStatus"]

        try:
            events = cfn.describe_stack_events(StackName=stack_name)["StackEvents"][:12]
            for event in reversed(events):
                key = event["EventId"]
                if key in seen:
                    continue
                seen.add(key)
                if event.get("ResourceStatus", "").endswith("FAILED"):
                    print(
                        "      FAILED %s: %s"
                        % (event.get("LogicalResourceId"), event.get("ResourceStatusReason", "")),
                        file=sys.stderr,
                    )
        except Exception:
            pass

        if status in _TERMINAL:
            elapsed = int(time.time() - started)
            if status not in _SUCCESS:
                raise SystemExit("stack finished in state %s after %ds" % (status, elapsed))
            print("      %s in %ds" % (status, elapsed))
            return
        time.sleep(5)


def _outputs(cfn, stack_name: str) -> Dict[str, str]:
    response = cfn.describe_stacks(StackName=stack_name)
    outputs = response["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def write_web_config(api_url: str, environment: str) -> None:
    """Point the static web client at the deployed API.

    Written at deploy time rather than committed, so the checked-in default
    stays same-origin and works with the local dev server.
    """
    build = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = (
        "/* Generated by scripts/deploy.py. Do not edit by hand.\n"
        " *\n"
        " * Nothing secret belongs here: this file is served to every visitor.\n"
        " */\n"
        "window.SCADS_CONFIG = {\n"
        '  apiBaseUrl: "%s",\n'
        '  environment: "%s",\n'
        '  build: "%s"\n'
        "};\n" % (api_url.rstrip("/"), environment, build)
    )
    with open(WEB_CONFIG, "w", encoding="utf-8") as handle:
        handle.write(content)
    print("      wrote apps/web/config.js -> %s" % api_url)


def seed(region: str, outputs: Dict[str, str], environment: str) -> None:
    print("[5/6] seeding registry, references and demo history")
    env = dict(os.environ)
    env.update({
        "AWS_REGION": region,
        "SCADS_ENV": environment,
        "STORE_BACKEND": "s3",
        "REPO_BACKEND": "dynamodb",
        "OCR_PROVIDER": "textract",
        "SCAN_BUCKET": outputs["ScanBucketName"],
        "REFERENCE_BUCKET": outputs["ReferenceBucketName"],
        "REGISTRY_TABLE": outputs["RegistryTableName"],
        "SCAN_EVENTS_TABLE": outputs["ScanEventsTableName"],
        "REFERENCE_TABLE": outputs["ReferenceTableName"],
    })
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "seed_demo.py"), "--aws", "--reset"],
        cwd=ROOT, env=env,
    )
    if result.returncode != 0:
        raise SystemExit("seeding failed")


def smoke(api_url: str) -> int:
    print("[6/6] smoke testing the deployed API")
    return subprocess.run(
        [
            sys.executable, os.path.join(ROOT, "scripts", "smoke_test.py"),
            "--base-url", api_url, "--expect-aws",
        ],
        cwd=ROOT,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-south-1"))
    parser.add_argument("--environment", default=os.environ.get("SCADS_ENV", "dev"))
    parser.add_argument("--stack-name", default=None)
    parser.add_argument("--artifact-bucket", default=None)
    parser.add_argument("--allowed-origins", default="*")
    parser.add_argument("--admin-token", default=os.environ.get("ADMIN_API_TOKEN", ""))
    parser.add_argument("--bedrock", action="store_true", help="enable optional explanation")
    parser.add_argument("--bedrock-model", default="anthropic.claude-3-5-haiku-20241022-v1:0")
    parser.add_argument("--plan", action="store_true", help="show the change set without applying")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    args = parser.parse_args()

    boto3 = boto3_or_exit()
    stack_name = args.stack_name or ("scads-" + args.environment)

    try:
        identity = boto3.client("sts", region_name=args.region).get_caller_identity()
    except Exception as exc:
        print(
            "Could not authenticate to AWS: %s\n"
            "Configure credentials (environment variables, a shared profile or an\n"
            "instance role) and try again." % exc,
            file=sys.stderr,
        )
        return 2

    account_id = identity["Account"]
    print("SCADS deployment")
    print("  account     %s" % account_id)
    print("  region      %s" % args.region)
    print("  stack       %s" % stack_name)
    print("  environment %s" % args.environment)
    print()

    if not args.skip_build:
        build_package()
    elif not os.path.exists(ZIP_PATH):
        print("--skip-build given but no package exists at .build/", file=sys.stderr)
        return 2

    print("[2/6] uploading the deployment artifact")
    bucket = ensure_artifact_bucket(boto3, args.region, account_id, args.artifact_bucket)
    key = upload_artifact(boto3, args.region, bucket)

    parameters = {
        "Environment": args.environment,
        "AllowedOrigins": args.allowed_origins,
        "AdminApiToken": args.admin_token,
        "BedrockEnabled": "true" if args.bedrock else "false",
        "BedrockModelId": args.bedrock_model,
        "ArtifactBucket": bucket,
        "ArtifactKey": key,
    }

    outputs = deploy_stack(boto3, args.region, stack_name, parameters, args.plan)
    if args.plan:
        return 0
    if not outputs:
        print("no stack outputs returned", file=sys.stderr)
        return 1

    print()
    print("Stack outputs")
    for name in sorted(outputs):
        print("  %-22s %s" % (name, outputs[name]))
    print()

    api_url = outputs["ApiUrl"]
    write_web_config(api_url, args.environment)

    if not args.skip_seed:
        seed(args.region, outputs, args.environment)

    code = 0
    if not args.skip_smoke:
        code = smoke(api_url)

    print()
    print("API: %s" % api_url)
    print()
    print("Next: deploy the web client")
    print("  python scripts/deploy_web.py --region %s --api-url %s" % (args.region, api_url))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
