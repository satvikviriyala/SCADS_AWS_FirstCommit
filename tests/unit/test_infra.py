"""Infrastructure template tests.

There is no SAM CLI in this environment to run ``sam validate``, and more
usefully, ``sam validate`` would not catch the mistakes that actually matter
here — a bucket that allows public access, a missing history index, a deploy
script that sends a parameter the template does not declare. These assertions
encode the security and cost decisions in ``docs/AWS_DEPLOYMENT.md`` so a later
edit cannot quietly undo one.
"""

import os
import re

import pytest

yaml = pytest.importorskip("pyyaml" if False else "yaml")

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", "template.yaml"
)
DEPLOY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "deploy.py"
)


class CfnLoader(yaml.SafeLoader):
    """YAML loader that understands CloudFormation short-form intrinsics."""


def _intrinsic(loader, tag_suffix, node):
    name = "Fn::" + tag_suffix if tag_suffix != "Ref" else "Ref"
    if isinstance(node, yaml.ScalarNode):
        return {name: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {name: loader.construct_sequence(node, deep=True)}
    return {name: loader.construct_mapping(node, deep=True)}


CfnLoader.add_multi_constructor("!", _intrinsic)


@pytest.fixture(scope="module")
def template():
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as handle:
        return yaml.load(handle, Loader=CfnLoader)


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


def _of_type(resources, kind):
    return {n: b for n, b in resources.items() if b["Type"] == kind}


# --- structure -----------------------------------------------------------


def test_template_is_a_sam_template(template):
    assert template["Transform"] == "AWS::Serverless-2016-10-31"


def test_template_declares_the_expected_resources(resources):
    kinds = {b["Type"] for b in resources.values()}
    assert "AWS::Serverless::Function" in kinds
    assert "AWS::Serverless::HttpApi" in kinds
    assert len(_of_type(resources, "AWS::S3::Bucket")) == 2
    assert len(_of_type(resources, "AWS::DynamoDB::Table")) == 3


def test_outputs_expose_what_the_deploy_scripts_consume(template):
    outputs = template["Outputs"]
    for name in (
        "ApiUrl", "ScanBucketName", "ReferenceBucketName",
        "RegistryTableName", "ScanEventsTableName", "ReferenceTableName",
    ):
        assert name in outputs, name


# --- security ------------------------------------------------------------


def test_no_bucket_allows_public_access(resources):
    """``docs/ARCHITECTURE.md`` section 9: no public S3 buckets."""
    buckets = _of_type(resources, "AWS::S3::Bucket")
    assert buckets
    for name, bucket in buckets.items():
        block = bucket["Properties"]["PublicAccessBlockConfiguration"]
        assert block["BlockPublicAcls"] is True, name
        assert block["BlockPublicPolicy"] is True, name
        assert block["IgnorePublicAcls"] is True, name
        assert block["RestrictPublicBuckets"] is True, name


def test_every_bucket_is_encrypted(resources):
    for name, bucket in _of_type(resources, "AWS::S3::Bucket").items():
        assert "BucketEncryption" in bucket["Properties"], name


def test_every_table_is_encrypted(resources):
    for name, table in _of_type(resources, "AWS::DynamoDB::Table").items():
        assert table["Properties"]["SSESpecification"]["SSEEnabled"] is True, name


def test_scan_uploads_expire(resources):
    """Raw photos of people's medicine must not live indefinitely."""
    rules = resources["ScanBucket"]["Properties"]["LifecycleConfiguration"]["Rules"]
    expiry = [r for r in rules if "ExpirationInDays" in r]
    assert expiry, "scan uploads have no expiry rule"
    assert expiry[0]["Status"] == "Enabled"


def test_reference_bucket_is_versioned(resources):
    """Enrolled references define what 'genuine' means; overwrites must be recoverable."""
    versioning = resources["ReferenceBucket"]["Properties"]["VersioningConfiguration"]
    assert versioning["Status"] == "Enabled"


def test_the_function_cannot_write_references_or_the_registry(resources):
    """Least privilege: the request path reads reference data, never writes it.

    A consumer scan that could mutate the registry or the enrolled artwork would
    let anyone redefine what counts as genuine
    (``docs/THREAT_MODEL.md`` section 5).
    """
    policies = resources["ApiFunction"]["Properties"]["Policies"]
    statements = []
    for policy in policies:
        if isinstance(policy, dict) and "Statement" in policy:
            statements.extend(policy["Statement"])

    assert statements, "the function has no inline policy statements"

    for statement in statements:
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        resource = json_ish(statement.get("Resource"))

        for action in actions:
            if action.startswith("s3:Put") and "ReferenceBucket" in resource:
                pytest.fail("the function may write to the reference bucket: " + action)
            if action in ("dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"):
                assert "ScanEventsTable" in resource, (
                    "write action %s is granted beyond the scan-events table" % action
                )
            # Blanket permissions would defeat the whole exercise.
            assert action != "*", "wildcard action granted"
            assert not action.endswith(":*"), "service-wide wildcard granted: " + action


def json_ish(value) -> str:
    import json as _json

    return _json.dumps(value, default=str)


def test_textract_permission_is_limited_to_the_call_we_make(resources):
    policies = resources["ApiFunction"]["Properties"]["Policies"]
    actions = []
    for policy in policies:
        if isinstance(policy, dict) and "Statement" in policy:
            for statement in policy["Statement"]:
                raw = statement.get("Action", [])
                actions.extend([raw] if isinstance(raw, str) else raw)
    textract = [a for a in actions if a.startswith("textract:")]
    assert textract == ["textract:DetectDocumentText"], textract


def test_admin_token_is_not_committed(template):
    """The demo-reset token must come from a parameter, never from source."""
    parameter = template["Parameters"]["AdminApiToken"]
    assert parameter["NoEcho"] is True
    assert parameter["Default"] == ""


def test_no_hardcoded_credentials_in_the_template():
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as handle:
        body = handle.read()
    assert not re.search(r"AKIA[0-9A-Z]{16}", body)
    assert "aws_secret_access_key" not in body.lower()


# --- correctness ---------------------------------------------------------


def test_scan_events_table_has_the_history_index(resources):
    """The scan-history dimension depends on this index existing.

    Without it the by-serial lookup would have to scan the table, which is both
    unaffordable and unboundedly slow — and the history check is the part of
    SCADS a database lookup cannot replicate.
    """
    table = resources["ScanEventsTable"]["Properties"]
    indexes = {i["IndexName"]: i for i in table["GlobalSecondaryIndexes"]}
    assert "serial-time-index" in indexes

    keys = {k["KeyType"]: k["AttributeName"] for k in indexes["serial-time-index"]["KeySchema"]}
    assert keys["HASH"] == "serial_index_key"
    assert keys["RANGE"] == "event_time"


def test_the_index_key_matches_what_the_record_writes(resources):
    """The GSI key and the attribute ScanEvent writes must be the same name."""
    from scads.contracts.records import ScanEvent

    item = ScanEvent(scan_id="scn_x", event_time="2026-09-18T10:00:00Z", serial_id="ser_1").to_item()
    table = resources["ScanEventsTable"]["Properties"]
    index = table["GlobalSecondaryIndexes"][0]
    hash_key = next(k["AttributeName"] for k in index["KeySchema"] if k["KeyType"] == "HASH")
    assert hash_key in item, "records do not write the GSI partition key"


def test_tables_are_on_demand(resources):
    """Demo traffic is bursty; provisioned capacity would throttle or waste."""
    for name, table in _of_type(resources, "AWS::DynamoDB::Table").items():
        assert table["Properties"]["BillingMode"] == "PAY_PER_REQUEST", name


def test_api_is_throttled(resources):
    """A public demo URL needs a bound on both abuse and the bill."""
    settings = resources["HttpApi"]["Properties"]["DefaultRouteSettings"]
    assert settings["ThrottlingRateLimit"] > 0
    assert settings["ThrottlingBurstLimit"] > 0


def test_log_groups_have_bounded_retention(resources):
    groups = _of_type(resources, "AWS::Logs::LogGroup")
    assert groups
    for name, group in groups.items():
        assert "RetentionInDays" in group["Properties"], name


def test_function_runtime_matches_the_packaging_target(resources):
    """The packager downloads wheels for a specific Python; they must agree."""
    import re as _re

    globals_block = None
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as handle:
        body = handle.read()
    match = _re.search(r"Runtime:\s*python([\d.]+)", body)
    assert match, "no runtime declared"
    template_runtime = match.group(1)

    with open(
        os.path.join(os.path.dirname(TEMPLATE_PATH), "..", "scripts", "package_lambda.py"),
        "r", encoding="utf-8",
    ) as handle:
        packager = handle.read()
    packager_target = _re.search(r'TARGET_PYTHON = "([\d.]+)"', packager).group(1)

    assert template_runtime == packager_target, (
        "template runtime python%s does not match the packaging target python%s"
        % (template_runtime, packager_target)
    )


def test_deploy_script_parameters_match_the_template(template):
    """A parameter mismatch fails only at deploy time, minutes in."""
    with open(DEPLOY_PATH, "r", encoding="utf-8") as handle:
        body = handle.read()

    block = re.search(r"parameters = \{(.*?)\n    \}", body, re.S)
    assert block, "could not locate the parameter block in deploy.py"
    sent = set(re.findall(r'"([A-Za-z]+)":', block.group(1)))

    declared = set(template["Parameters"])
    undeclared = sent - declared
    assert not undeclared, "deploy.py sends parameters the template does not declare: %s" % undeclared

    required = {n for n, p in template["Parameters"].items() if "Default" not in p}
    missing = required - sent
    assert not missing, "deploy.py omits required template parameters: %s" % missing
