"""The CloudFormation template keeps the security and scaling design (Feature 6).

Reads scripts/nimbus-stack.yaml as data; nothing is deployed. Complements `cfn-lint`,
which checks the template is valid CloudFormation, by checking the design choices the
README and docs/aws-deployment.md describe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")  # dev dependency: pip install -r requirements-dev.txt

TEMPLATE = Path(__file__).resolve().parent.parent / "scripts" / "nimbus-stack.yaml"


class _CfnLoader(yaml.SafeLoader):
    """Reads CloudFormation short forms (!Ref, !Sub, !GetAtt ...) as {"Ref": ...} etc."""


def _tag(loader, suffix, node):
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    if isinstance(node, yaml.SequenceNode):
        return {name: loader.construct_sequence(node, deep=True)}
    if isinstance(node, yaml.MappingNode):
        return {name: loader.construct_mapping(node, deep=True)}
    return {name: loader.construct_scalar(node)}


_CfnLoader.add_multi_constructor("!", _tag)


@pytest.fixture(scope="module")
def resources():
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_CfnLoader)["Resources"]


def of_type(resources, kind):
    return {name: r for name, r in resources.items() if r["Type"] == kind}


def test_servers_come_from_an_auto_scaling_group_behind_a_load_balancer(resources):
    assert not of_type(resources, "AWS::EC2::Instance")  # no hand-placed server
    group = resources["AppAutoScalingGroup"]["Properties"]
    assert group["HealthCheckType"] == "ELB"
    assert group["TargetGroupARNs"] == [{"Ref": "AppTargetGroup"}]
    assert len(group["VPCZoneIdentifier"]) == 2  # two Availability Zones
    assert group["MinSize"] == {"Ref": "MinServers"} and group["MaxSize"] == {"Ref": "MaxServers"}
    assert resources["LoadBalancer"]["Properties"]["Scheme"] == "internet-facing"


def test_capacity_changes_automatically_on_cpu_and_on_requests(resources):
    metrics = {p["Properties"]["TargetTrackingConfiguration"]["PredefinedMetricSpecification"]["PredefinedMetricType"]
               for p in of_type(resources, "AWS::AutoScaling::ScalingPolicy").values()
               if p["Properties"]["PolicyType"] == "TargetTrackingScaling"}
    assert metrics == {"ASGAverageCPUUtilization", "ALBRequestCountPerTarget"}


def test_each_user_stays_on_one_server(resources):
    attributes = {a["Key"]: a["Value"] for a in resources["AppTargetGroup"]["Properties"]["TargetGroupAttributes"]}
    assert attributes["stickiness.enabled"] == "true"
    assert resources["AppTargetGroup"]["Properties"]["HealthCheckPath"] == "/_stcore/health"


def test_only_the_load_balancer_reaches_the_servers_and_only_the_servers_reach_the_database(resources):
    app_rules = resources["AppSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    streamlit = [r for r in app_rules if r["FromPort"] == 8501]
    assert streamlit == [dict(streamlit[0], SourceSecurityGroupId={"Ref": "LoadBalancerSecurityGroup"})]
    assert "CidrIp" not in streamlit[0]
    db_rules = resources["DbSecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert [r["SourceSecurityGroupId"] for r in db_rules] == [{"Ref": "AppSecurityGroup"}]
    database = resources["NimbusDatabase"]["Properties"]
    assert database["PubliclyAccessible"] is False


def test_new_code_replaces_servers_one_at_a_time_and_waits_for_each(resources):
    rolling = resources["AppAutoScalingGroup"]["UpdatePolicy"]["AutoScalingRollingUpdate"]
    assert rolling["MaxBatchSize"] == 1 and rolling["WaitOnResourceSignals"] is True
    user_data = resources["AppLaunchTemplate"]["Properties"]["LaunchTemplateData"]["UserData"]["Fn::Base64"]["Fn::Sub"]
    assert "--resource AppAutoScalingGroup" in user_data and "${GitCommit}" in user_data
    assert "set +x" in user_data.split("NIMBUS_DATABASE_URL")[0]  # tracing off before the password


def test_every_server_runs_the_same_pinned_commit():
    """QA 31 Oct 2026, D-1: with GitCommit empty, servers added later would clone the newest
    commit, so different servers behind the load balancer could run different code."""
    parameters = yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_CfnLoader)["Parameters"]
    commit = parameters["GitCommit"]
    assert "Default" not in commit  # must be given when the stack is created
    import re

    pattern = re.compile(commit["AllowedPattern"])
    assert not pattern.match("") and pattern.match("ff18611")
