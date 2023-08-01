import os
import sys
import argparse
import datetime
import pandas as pd

data_path = "/data"
default_output_filename = "output"
default_trainer_names = [ 'PolynomialRegressionTrainer', 'GradientBoostingRegressorTrainer', 'SGDRegressorTrainer', 'KNeighborsRegressorTrainer', 'LinearRegressionTrainer','SVRRegressorTrainer']
default_trainers = ",".join(default_trainer_names)

UTC_OFFSET_TIMEDELTA = datetime.datetime.utcnow() - datetime.datetime.now()

# set model top path to data path
os.environ['MODEL_PATH'] = data_path

cur_path = os.path.join(os.path.dirname(__file__), '.')
sys.path.append(cur_path)
src_path = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.append(src_path)
profile_path = os.path.join(os.path.dirname(__file__), '../src/profile')
sys.path.append(profile_path)

from util.prom_types import PROM_SERVER, PROM_QUERY_INTERVAL, PROM_QUERY_STEP, PROM_HEADERS, PROM_SSL_DISABLE
from util.prom_types import metric_prefix as KEPLER_METRIC_PREFIX, node_info_column, prom_responses_to_results
from util.loader import load_json, DEFAULT_PIPELINE
from util.saver import save_json
from util import get_valid_feature_group_from_queries, PowerSourceMap
from train.prom.prom_query import _range_queries

def print_file_to_stdout(args):
    file_path = os.path.join(data_path, args.output_filename)
    try:
        with open(file_path, 'r') as file:
            contents = file.read()
            print(contents)
    except FileNotFoundError:
        print(f"Error: Output '{file_path}' not found.")
    except IOError:
        print(f"Error: Unable to read output '{file_path}'.")

def extract_time(benchmark_filename):
    data = load_json(data_path, benchmark_filename)
    start_str = data["metadata"]["creationTimestamp"]
    start = datetime.datetime.strptime(start_str, '%Y-%m-%dT%H:%M:%SZ')
    end_str = data["status"]["results"][-1]["repetitions"][-1]["pushedTime"].split(".")[0]
    end = datetime.datetime.strptime(end_str, '%Y-%m-%d %H:%M:%S')
    print(UTC_OFFSET_TIMEDELTA)
    return start-UTC_OFFSET_TIMEDELTA, end-UTC_OFFSET_TIMEDELTA

def summary_validation(validate_df):
    items = []
    metric_to_validate_pod = {
        "cgroup": "kepler_container_cgroupfs_cpu_usage_us_total",
        # "hwc": "kepler_container_cpu_instructions_total", 
        "hwc": "kepler_container_cpu_cycles_total",
        "kubelet": "kepler_container_kubelet_cpu_usage_total",
        "bpf": "kepler_container_bpf_cpu_time_us_total",
    }
    metric_to_validate_power = {
        "rapl": "kepler_node_package_joules_total",
        "platform": "kepler_node_platform_joules_total"
    }
    for metric, query in metric_to_validate_pod.items():
        target_df = validate_df[validate_df["query"]==query]
        valid_df = target_df[target_df[">0"] > 0]
        if len(valid_df) == 0:
            # no data
            continue
        availability = len(valid_df)/len(target_df)
        valid_datapoint = valid_df[">0"].sum()
        item = dict()
        item["usage_metric"] = metric
        item["availability"] = availability
        item["valid_datapoint"] = valid_datapoint
        items += [item]
    summary_df = pd.DataFrame(items)
    print(summary_df)
    for metric, query in metric_to_validate_pod.items():
        target_df = validate_df[validate_df["query"]==query]
        no_data_df = target_df[target_df["count"] == 0]
        zero_data_df = target_df[target_df[">0"] == 0]
        valid_df = target_df[target_df[">0"] > 0]
        print("==== {} ====".format(metric))
        if len(no_data_df) > 0:
            print("{} pods: \tNo data for {}".format(len(no_data_df), pd.unique(no_data_df["scenarioID"])))
        if len(zero_data_df) > 0:
            print("{} pods: \tZero data for {}".format(len(zero_data_df), pd.unique(zero_data_df["scenarioID"])))

        print("{} pods: \tValid\n".format(len(valid_df)))
        print("Valid data points:")
        print(valid_df.groupby(["scenarioID"]).sum()[[">0"]])
    for metric, query in metric_to_validate_power.items():
        target_df = validate_df[validate_df["query"]==query]
        print("{} data: \t{}".format(metric, target_df[">0"].values))

def get_validate_df(benchmark_filename, query_response):
    items = []
    query_results = prom_responses_to_results(query_response)
    queries = [query for query in query_results.keys() if "container" in query]
    status_data = load_json(data_path, benchmark_filename)
    if status_data is None:
        # select all with keyword
        for query in queries:
            df = query_results[query]
            filtered_df = df[df["pod_name"].str.contains(benchmark_filename)]
            # set validate item
            item = dict()
            item["pod"] = benchmark_filename
            item["scenarioID"] = ""
            item["query"] = query
            item["count"] = len(filtered_df)
            item[">0"] = len(filtered_df[filtered_df[query] > 0])
            item["total"] = filtered_df[query].max()
            items += [item]
    else:
        cpe_results = status_data["status"]["results"]
        for result in cpe_results:
            scenarioID = result["scenarioID"]
            scenarios = result["scenarios"]
            configurations = result["configurations"]
            for k, v in scenarios.items():
                result[k] = v
            for k, v in configurations.items():
                result[k] = v
            repetitions = result["repetitions"]
            for rep in repetitions:
                podname = rep["pod"]
                for query in queries:
                    df = query_results[query]
                    filtered_df = df[df["pod_name"]==podname]
                    # set validate item
                    item = dict()
                    item["pod"] = podname
                    item["scenarioID"] = scenarioID
                    item["query"] = query
                    item["count"] = len(filtered_df)
                    item[">0"] = len(filtered_df[filtered_df[query] > 0])
                    item["total"] = filtered_df[query].max()
                    items += [item]
    energy_queries = [query for query in query_results.keys() if "_joules" in query]
    for query in energy_queries:
        df = query_results[query]
        filtered_df = df.copy()
        # set validate item
        item = dict()
        item["pod"] = ""
        item["scenarioID"] = ""
        item["query"] = query
        item["count"] = len(filtered_df)
        item[">0"] = len(filtered_df[filtered_df[query] > 0])
        item["total"] = filtered_df[query].max()
        items += [item]
    validate_df = pd.DataFrame(items)
    print(validate_df)
    return validate_df

def query(args):
    from prometheus_api_client import PrometheusConnect
    prom = PrometheusConnect(url=args.server, headers=PROM_HEADERS, disable_ssl=PROM_SSL_DISABLE)
    benchmark_filename = args.input
    if benchmark_filename == "":
        print("Query last {} interval.".format(args.interval))
        end = datetime.datetime.now()
        start = end - datetime.timedelta(seconds=args.interval)
    else:
        print("Query from {}.".format(benchmark_filename))
        start, end = extract_time(benchmark_filename)
    available_metrics = prom.all_metrics()
    queries = [m for m in available_metrics if args.metric_prefix in m]
    print("Start {} End {}".format(start, end))
    response = _range_queries(prom, queries, start, end, args.step, None)
    save_json(path=data_path, name=args.output_filename, data=response)
    # try validation if applicable
    if benchmark_filename != "":
        validate_df = get_validate_df(benchmark_filename, response)
        summary_validation(validate_df)

def validate(args):
    if args.benchmark == "":
        print("Need --benchmark")
        exit()

    response_filename = args.input
    response = load_json(data_path, response_filename)
    validate_df = get_validate_df(args.benchmark, response)
    summary_validation(validate_df)

def assert_train(trainer, data, energy_components):
    import pandas as pd
    trainer.print_log("assert train")
    node_types = pd.unique(data[node_info_column])
    for node_type in node_types:
        node_type_str = int(node_type)
        node_type_filtered_data = data[data[node_info_column] == node_type]
        X_values = node_type_filtered_data[trainer.features].values
        # for component in energy_components:
        #     output = trainer.predict(node_type_str, component, X_values)
        #     assert len(output) == len(X_values), "length of predicted values != features ({}!={})".format(len(output), len(X_values))

def train(args):
    if not args.input:
        print("must give input filename (query response) via --input for training.")
        exit()

    from train import DefaultExtractor, MinIdleIsolator, NoneIsolator, DefaultProfiler, ProfileBackgroundIsolator, TrainIsolator, generate_profiles, NewPipeline
    extractor = DefaultExtractor()
    supported_isolator = {
        "min": MinIdleIsolator(),
        "none": NoneIsolator(),
    }
    profiles = dict()
    if args.profile:
        idle_response = load_json(data_path, args.profile)
        idle_data = prom_responses_to_results(idle_response)
        profile_map = DefaultProfiler.process(idle_data)
        profiles = generate_profiles(profile_map)
        supported_isolator["profile"] = ProfileBackgroundIsolator(profiles, idle_data)
        supported_isolator["trainer"] = TrainIsolator(idle_data=idle_data, profiler=DefaultProfiler)
    
    response = load_json(data_path, args.input)
    query_results = prom_responses_to_results(response)
    valid_feature_groups = get_valid_feature_group_from_queries(query_results.keys())
    if args.isolator not in supported_isolator:
        print("isolator {} is not supported. supported isolator: {}".format(args.isolator, supported_isolator.keys()))
        exit()
    energy_components = PowerSourceMap[args.energy_source]
    abs_trainer_names = args.abs_trainers.split(",")
    dyn_trainer_names = args.dyn_trainers.split(",")
    isolator = supported_isolator[args.isolator]
    pipeline = NewPipeline(args.pipeline_name, profiles, abs_trainer_names, dyn_trainer_names, extractor=extractor, isolator=isolator, target_energy_sources=[args.energy_source] ,valid_feature_groups=valid_feature_groups)
    for feature_group in valid_feature_groups:
        success, abs_data, dyn_data = pipeline.process(query_results, energy_components, args.energy_source, feature_group=feature_group.name)
        assert success, "failed to process pipeline {}".format(pipeline.name) 
        for trainer in pipeline.trainers:
            if trainer.feature_group == feature_group and trainer.energy_source == args.energy_source:
                if trainer.node_level:
                    assert_train(trainer, abs_data, energy_components)
                else:
                    assert_train(trainer, dyn_data, energy_components)


if __name__ == "__main__":
    # Create an ArgumentParser object
    parser = argparse.ArgumentParser(description="Kepler model server entrypoint")
    parser.add_argument("command", type=str, help="The command to execute.")

    # Common arguments
    parser.add_argument("-i", "--input", type=str, help="Specify input file name.", default="")
    parser.add_argument("-o", "--output-filename", type=str, help="Specify output file name", default=default_output_filename)

    # Query arguments
    parser.add_argument("-s", "--server", type=str, help="Specify prometheus server.", default=PROM_SERVER)
    parser.add_argument("--interval", type=int, help="Specify query interval.", default=PROM_QUERY_INTERVAL)
    parser.add_argument("--step", type=str, help="Specify query step.", default=PROM_QUERY_STEP)
    parser.add_argument("--metric-prefix", type=str, help="Specify metrix prefix to filter.", default=KEPLER_METRIC_PREFIX)

    # Train arguments
    parser.add_argument("-p", "--pipeline-name", type=str, help="Specify pipeline name.", default=DEFAULT_PIPELINE)
    parser.add_argument("--isolator", type=str, help="Specify isolator name (none, min, profile, trainer).", default="none")
    parser.add_argument("--profile", type=str, help="Specify profile input (required for trainer and profile isolator).")
    parser.add_argument("--energy-source", type=str, help="Specify energy source.", default="rapl")
    parser.add_argument("--abs-trainers", type=str, help="Specify trainer names (use comma(,) as delimiter).", default=default_trainers)
    parser.add_argument("--dyn-trainers", type=str, help="Specify trainer names (use comma(,) as delimiter).", default=default_trainers)

    # Validate arguments
    parser.add_argument("--benchmark", type=str, help="Specify benchmark file name.", default="")

    # Parse the command-line arguments
    args = parser.parse_args()

    if not os.path.exists("/data"):
        print("/data must be mount, add -v \"$(pwd)\":/data .")
        exit()

    # Check if the required argument is provided
    if not args.command:
        parser.print_help()
    else:
        getattr(sys.modules[__name__], args.command)(args)
    