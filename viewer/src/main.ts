import {
  DynamoDBClient,
  BatchGetItemCommand,
  AttributeValue
} from "@aws-sdk/client-dynamodb";
import * as fs from "fs";
import select from "@inquirer/select";
import checkbox from "@inquirer/checkbox";
import confirm from "@inquirer/confirm";
import { table } from "table";
import chalk from "chalk";
interface Configuration {
  versions: [string];
  testFiles: [string];
}

function readConfiguration(fileName: string): Configuration {
  const content = fs.readFileSync(fileName, "utf-8");
  return JSON.parse(content);
}

interface TestSelectionChoice {
  name: string;
  value: string;
}

function getTestsSelectionChoices(config: Configuration): Array<TestSelectionChoice> {
  return config.testFiles.map(test => {
    return { name: test, value: test }
  });
}

function getVersionSelectionChoices(config: Configuration): Array<TestSelectionChoice> {
  return config.versions.map(version => {
    return { name: version, value: version }
  });
}

interface Throughput {
  ops_per_second: number;
}

interface Latencies {
  p99: number;
  p99_9: number;
  p99_99: number;
}

interface OpResult {
  name: string;
  throughput: Throughput;
  latencies: Latencies;
}

interface VersionWithOpResult extends OpResult {
  version: string;
}

function cmpThroughputDescending(a: VersionWithOpResult, b: VersionWithOpResult): number {
  if (a.throughput.ops_per_second < b.throughput.ops_per_second) {
    return 1;
  } else if (a.throughput.ops_per_second > b.throughput.ops_per_second) {
    return -1;
  } else {
    return 0;
  }
}

function sortBy(groupedByOpFqn: Record<string, Array<VersionWithOpResult>>,
  f: (a: VersionWithOpResult, b: VersionWithOpResult) => number) {
  Object.keys(groupedByOpFqn).forEach(opFqn => groupedByOpFqn[opFqn].sort(f));
}

async function main() {
  const config = readConfiguration("config.json");

  const versions = await checkbox({
    message: "Select Version(s)",
    choices: getVersionSelectionChoices(config)
  });

  const testFile = await select({
    message: "Select Test",
    choices: getTestsSelectionChoices(config)
  });

  const simRegion = process.env.HZ_SIM_REGION!;
  const simTable = process.env.HZ_SIM_TABLE!;
  const showPercentiles = await confirm({ message: "Show Percentiles?", default: false });

  const client = new DynamoDBClient({ region: simRegion });

  const keys: Array<Record<string, AttributeValue>> = [];
  versions.forEach(version =>
    keys.push({ version: { S: version }, test_file: { S: testFile } })
  );
  const batchGetInput = {
    RequestItems: {
      [simTable]: { // this is an oddity, you need to put var in array compute it, otherwise it cries
        Keys: keys,
        ProjectionExpression: "version,results"
      }
    }
  };

  const getItemCommand = new BatchGetItemCommand(batchGetInput);
  const getItemResp = await client.send(getItemCommand);

  const groupedByOpFqn: Record<string, Array<VersionWithOpResult>> = {};
  getItemResp?.Responses?.[simTable].forEach(row => {
    if (row?.results?.S) {
      const version = row?.version?.S!;
      const rowJson = JSON.parse(row?.results?.S);
      Object.keys(rowJson).forEach(test => {
        rowJson[test].forEach((op: OpResult) => {
          const opFqn = `${test}.${op.name}`;
          if (!(opFqn in groupedByOpFqn)) {
            groupedByOpFqn[opFqn] = [];
          }
          groupedByOpFqn[opFqn].push(
            {
              version: version,
              name: op.name,
              throughput: op.throughput,
              latencies: op.latencies
            });
        });
      });
    }
  });

  sortBy(groupedByOpFqn, cmpThroughputDescending);

  // would be good to highlight green in each p99
  const rows: Array<Array<unknown>> = [];
  const tblHeader = ["VERSION", "TEST.OP", "OPS/s", `OPS/s Relative TEST.OP ${chalk.black.bgGreen("Benchmark")}`];
  if (showPercentiles) {
    tblHeader.push("P99(μs)", "P99.9(μs)", "P99.99(μs)");
  }
  rows.push(tblHeader);

  Object.keys(groupedByOpFqn).forEach(opFqn => {
    for (let i = 0; i < groupedByOpFqn[opFqn].length; i++) {
      const iAmBaselineForTest =
        groupedByOpFqn[opFqn][0].version === groupedByOpFqn[opFqn][i].version;
      const relativeTestBenchmark = iAmBaselineForTest
        ? "-"
        : `${(groupedByOpFqn[opFqn][i].throughput.ops_per_second / groupedByOpFqn[opFqn][0].throughput.ops_per_second)}`;
      const row = [
        groupedByOpFqn[opFqn][i].version,
        opFqn,
        iAmBaselineForTest
          ? `${chalk.black.bgGreen(groupedByOpFqn[opFqn][i].throughput.ops_per_second)}`
          : groupedByOpFqn[opFqn][i].throughput.ops_per_second,
        relativeTestBenchmark
      ];
      if (showPercentiles) {
        row.push(`${groupedByOpFqn[opFqn][i].latencies.p99}`);
        row.push(`${groupedByOpFqn[opFqn][i].latencies.p99_9}`);
        row.push(`${groupedByOpFqn[opFqn][i].latencies.p99_99}`);
      }
      rows.push(row);
    }
  });

  console.log(table(rows));
}

main();
