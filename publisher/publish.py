import dataclasses
import typing
from botocore.client import Config
from botocore.credentials import json
import yaml
import pathlib
import orjson
import boto3
import os


@dataclasses.dataclass()
class SimulatorPaths:
    test_dir: str
    test_path: str
    inventory_plan_path: str
    terraform_path: str
    setup_path: str  # for scraping the java version
    results_path: str


@dataclasses.dataclass()
class SimulatorTestConfiguration:
    name: str
    fqn: str
    duration: str
    loadgenerator_count: int
    loadgenerator_jvm_args: list[str]
    member_count: int
    member_jvm_args: list[str]
    version: str
    warmup_seconds: int
    cooldown_seconds: int
    tests: list[dict[str, typing.Any]]


@dataclasses.dataclass()
class Latencies:
    unit: str
    p10: float
    p20: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    p99_9: float
    p99_99: float


@dataclasses.dataclass()
class Throughput:
    ops_per_second: float
    ops_total: float


@dataclasses.dataclass()
class ThroughputResult:
    name: str
    throughput: Throughput
    latencies: Latencies


ThroughputResults = dict[str, list[ThroughputResult]]


class TestFileParser:
    def __init__(self, sp: SimulatorPaths):
        self.sp = sp

    def parse(self) -> SimulatorTestConfiguration:
        with open(self.sp.test_path, "r") as f:
            test_file = yaml.safe_load(f)
        # for now we assume a single set of tests, i.e. one 'name' with subtests
        test = test_file[0]
        name = test["name"]
        fqn = pathlib.Path(self.sp.test_path).name
        duration: str = test["duration"]
        loadgenerator_count = int(test["clients"])
        member_count = int(test["members"])
        version: str = test["version"]
        version = version.replace("maven=", "")
        member_jvm_args: list[str] = test["member_args"].replace("\n", "").split()
        loadgenerator_jvm_args: list[str] = (
            test["client_args"].replace("\n", "").split()
        )
        warmup_seconds = int(test["warmup_seconds"])
        cooldown_seconds = int(test["cooldown_seconds"])
        tests: list[dict[str, typing.Any]] = test["test"]
        return SimulatorTestConfiguration(
            name,
            fqn,
            duration,
            loadgenerator_count,
            loadgenerator_jvm_args,
            member_count,
            member_jvm_args,
            version,
            warmup_seconds,
            cooldown_seconds,
            tests,
        )


@dataclasses.dataclass()
class InventoryPlan:
    region: str
    region_az: str
    member_count: int
    member_instance_type: str
    member_ami: str
    loadbalancer_count: int
    loadbalancer_instance_type: str
    loadbalancer_ami: str


class InventoryPlanParser:
    def __init__(self, paths: SimulatorPaths):
        self.paths = paths

    def parse(self) -> InventoryPlan:
        with open(self.paths.inventory_plan_path, "r") as f:
            inventory = yaml.safe_load(f)
        members = inventory["nodes"]
        loadgenerators = inventory["loadgenerators"]
        return InventoryPlan(
            inventory["region"],
            inventory["availability_zone"],
            members["count"],
            members["instance_type"],
            members["ami"],
            loadgenerators["count"],
            loadgenerators["instance_type"],
            loadgenerators["ami"],
        )


@dataclasses.dataclass()
class Setup:
    jvm: str


class SetupParser:
    """Oddity for now given that the quick hook is to get the JVM version from the install script"""

    def __init__(self, paths: SimulatorPaths):
        self.paths = paths

    def parse(self) -> Setup:
        with open(self.paths.setup_path) as f:
            setup = f.readlines()
        # if the following throws then we've got a horribly wrong setup...
        needle = "inventory install java --url"
        match = [line for line in setup if needle in line][0]
        match = match.replace(needle, "").replace("\n", "").strip()
        return Setup(match)


@dataclasses.dataclass()
class Parameters:
    simulator_test: SimulatorTestConfiguration
    inventory_plan: InventoryPlan
    setup: Setup
    results: ThroughputResults


class ParametersCollector:
    def __init__(
        self,
        simulator_test_dir: str,
        simulator_test_file: str,
        simulator_run_output_dir: str,
    ):
        self.paths = self._create_paths(
            simulator_test_dir,
            simulator_test_file,
            simulator_run_output_dir,
        )

    def _create_paths(
        self,
        simulator_test_dir: str,
        simulator_test_file: str,
        simulator_run_output_dir: str,
    ) -> SimulatorPaths:
        return SimulatorPaths(
            f"{simulator_test_dir}",
            f"{simulator_test_dir}/{simulator_test_file}",
            f"{simulator_test_dir}/inventory_plan.yaml",
            f"{simulator_test_dir}/aws/main.tf",
            f"{simulator_test_dir}/setup",
            f"{simulator_test_dir}/{simulator_run_output_dir}/results.yaml",
        )

    def collect(self) -> Parameters:
        simulator_test_parameters = TestFileParser(self.paths).parse()
        inventory_parameters = InventoryPlanParser(self.paths).parse()
        setup = SetupParser(self.paths).parse()
        results = ThrougputResultsParser(self.paths).parse()
        return Parameters(
            simulator_test_parameters,
            inventory_parameters,
            setup,
            results,
        )


class ThrougputResultsParser:
    def __init__(self, paths: SimulatorPaths):
        self.paths = paths

    def parse(self) -> ThroughputResults:
        with open(self.paths.results_path, "r") as f:
            results_raw = yaml.safe_load(f)
        percentiles = [
            "10%(us)",
            "20%(us)",
            "50%(us)",
            "75%(us)",
            "90%(us)",
            "95%(us)",
            "99%(us)",
            "99.9%(us)",
            "99.99%(us)",
        ]
        results: ThroughputResults = dict()
        for fqn, op_result in results_raw.items():
            [test_name, op_name] = fqn.split(".")
            measurements = op_result["measurements"]
            if test_name not in results:
                results[test_name] = []
            latencies = [float(measurements[percentile]) for percentile in percentiles]
            results[test_name].append(
                ThroughputResult(
                    op_name,
                    Throughput(
                        float(measurements["throughput"]),
                        float(measurements["operations"]),
                    ),
                    Latencies("us", *latencies),
                )
            )
        return results


def dynamodb_put(parameters: Parameters):
    aws_region = os.environ["HZ_SIM_REGION"]
    aws_table = os.environ["HZ_SIM_TABLE"]
    # region + tablename need to come from os.environ
    cfg = Config(region_name=aws_region)
    dynamo = boto3.client("dynamodb", config=cfg)
    print(
        dynamo.put_item(
            TableName=aws_table,
            Item={
                "version": {"S": parameters.simulator_test.version},
                "test_file": {"S": parameters.simulator_test.fqn},
                "jvm": {"S": parameters.setup.jvm},
                "member_ami": {"S": parameters.inventory_plan.member_ami},
                "member_instance_type": {
                    "S": parameters.inventory_plan.member_instance_type
                },
                "loadgenerator_ami": {"S": parameters.inventory_plan.loadbalancer_ami},
                "loadgenerator_instance_type": {
                    "S": parameters.inventory_plan.loadbalancer_instance_type
                },
                "region": {"S": parameters.inventory_plan.region},
                "region_az": {"S": parameters.inventory_plan.region_az},
                "loadgenerator_count": {
                    "N": str(parameters.inventory_plan.loadbalancer_count)
                },
                "member_count": {"N": str(parameters.inventory_plan.member_count)},
                "jvm_member_args": {
                    "S": str(json.dumps(parameters.simulator_test.member_jvm_args))
                },
                "jvm_loadgenerator_args": {
                    "S": str(
                        json.dumps(parameters.simulator_test.loadgenerator_jvm_args)
                    )
                },
                "warmup_seconds": {"N": str(parameters.simulator_test.warmup_seconds)},
                "cooldown_seconds": {
                    "N": str(parameters.simulator_test.cooldown_seconds)
                },
                "duration": {"S": parameters.simulator_test.duration},
                "tests": {
                    "S": json.dumps(parameters.simulator_test.tests)
                },  # this should be test -> details
                "results": {"S": orjson.dumps(parameters.results).decode()},
            },
        )
    )


def main(
    simulator_test_dir: str,
    simulator_test_file: str,
    simulator_run_output_dir: str,
) -> None:
    parameters = ParametersCollector(
        simulator_test_dir,
        simulator_test_file,
        simulator_run_output_dir,
    ).collect()
    dynamodb_put(parameters)


if __name__ == "__main__":
    project_path = "/app/project"
    test_file = os.environ["HZ_TEST"]
    run_path = os.environ["HZ_RUN"]
    main(project_path, test_file, run_path)
