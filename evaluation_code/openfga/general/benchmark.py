#!/usr/bin/env python3
import argparse
import concurrent.futures
import copy
import csv
from datetime import datetime
import os
import random
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import psutil
import requests
import yaml


# Helper function to recursively substitute placeholders in a dictionary.
def substitute_placeholders(obj, **values):
    if isinstance(obj, str):
        return obj.format(**values)
    elif isinstance(obj, dict):
        return {k: substitute_placeholders(v, **values) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [substitute_placeholders(item, **values) for item in obj]
    else:
        return obj

# Dictionary of request forms keyed by model name.
REQUEST_FORMS = {
    "model_1": {
        "authorization_model_id": None,  # Placeholder, will be set dynamically
        "tuple_key": {
            "user": "user:user{user}",
            "relation": "can_edit",
            "object": "document:doc{doc}"
        }
    },
    "model_2": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "user:user{user}",
            "relation": "has_feature",
            "object": "feature:can-view-page-history"},
            "context": {
                    "page_history_days_count": "500"
                }
    },
    "model_3": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "user:user{user}",
            "relation": "can_view",
            "object": "document:doc{doc}" },
            "context": {
               "user_ip": "192.168.0.1"
            }},
      "model_5": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "user:user{user}",
            "relation": "can_edit_billing",
            "object": "organization:org{doc}" }     
    },
    "model_6": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "user:user{user}",
            "relation": "can_change_owner",
            "object": "doc:doc{doc}" }     
    }, "model_7": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "user:u{user}",
            "relation": "can_read",
            "object": "doc:d{doc}" }     
    }, "model_8": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "agent:a{user}",
            "relation": "can_read",
            "object": "doc:d{doc}" }
            # ,"context": {
            #   "current_time": "2023-01-01T00:04:00Z"
            # }
            }, 
        "model_slack_domain": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "user:u{user}",
            "relation": "writer",
            "object": "channel:c{doc}" },
            "context": {
              "current_time": "2023-01-01T00:04:00Z"
            }},
        "model_slack_overlay": {
        "authorization_model_id": None,
        "tuple_key": {
            "user": "agent:a{user}",
            "relation": "writer",
            "object": "channel:c{doc}" },
            "context": {
              "current_time": "2023-01-01T00:04:00Z"
            }
             }
    # 7: is grdrive gen ai domain
    # 8 is ovrlay gdrive

    # Additional forms can be added here.
}

WRITE_SUPPORTED_MODELS = {"model_8", "model_slack_overlay"}

DEFAULT_CHECK_TYPES = {
    "model_8": ["agent_doc", "agent_folder", "human_doc", "human_folder"],
    "model_slack_overlay": ["slack_agent_writer", "slack_human_writer"],
}

VALID_CHECK_TYPES = {
    "agent_doc", "agent_folder", "human_doc", "human_folder",
    "slack_agent_writer", "slack_human_writer",
}

def parse_arguments():
    parser = argparse.ArgumentParser(description="Benchmark script for OpenFGA")
    parser.add_argument('--api-url', type=str, default=None, help="OpenFGA API URL (default: value from config/store_config.yaml)")
    parser.add_argument('--store-id', type=str, default=None, help="OpenFGA store ID (default: value from config/store_config.yaml)")
    parser.add_argument('--model-id', type=str, default=None, help="OpenFGA Authorization Model ID (default: value from config/store_config.yaml)")
    parser.add_argument('--requests-count', type=int, default=1000, help="Number of operations to send (default: 1000)")
    parser.add_argument('--concurrency', type=int, default=100,
                        help="Number of threads for concurrent requests")
    parser.add_argument('--config-file', type=str, default='config/store_config.yaml', help="Path to configuration file (default: config/store_config.yaml)")
    parser.add_argument('--test-model-id', type=str, default="model_1", help="The test model id to pick sample request")
    parser.add_argument('--userUpperBound', type=int, default=50, help="Upper bound for human user indices")
    parser.add_argument('--objectUpperBound', type=int, default=50, help="Upper bound for object indices (doc/channel)")
    parser.add_argument('--agentUpperBound', type=int, default=50,
                        help="Upper bound for agent indices (model_8 checks and writes)")
    parser.add_argument('--folderUpperBound', type=int, default=20,
                        help="Upper bound for folder indices (model_8 human_folder checks)")
    parser.add_argument('--scopeUpperBound', type=int, default=2,
                        help="Number of team scopes for gdrive model_8 write delegation (scope:org/team0 … team{N-1})")
    parser.add_argument('--workspaceUpperBound', type=int, default=1,
                        help="Number of workspaces for Slack overlay scopes (scope:ws{N}/team{T})")
    parser.add_argument('--teamsPerWorkspace', type=int, default=2,
                        help="Number of teams per workspace in Slack overlay scopes")
    parser.add_argument('--operation-mode', choices=['check-only', 'write-only', 'mixed'], default='check-only',
                        help="Workload mode: checks only, writes only, or a mixed workload")
    parser.add_argument('--write-ratio', type=float, default=0.2,
                        help="Fraction of write requests when --operation-mode=mixed (0.0 to 1.0)")
    parser.add_argument('--check-types', type=str, default=None,
                        help="Comma-separated check sub-types. model_8: agent_doc, agent_folder, human_doc, human_folder. model_slack_overlay: slack_agent_writer, slack_human_writer")
    return parser.parse_args()


def validate_arguments(args):
    if args.requests_count <= 0:
        print("--requests-count must be greater than 0.")
        sys.exit(1)

    if args.concurrency <= 0:
        print("--concurrency must be greater than 0.")
        sys.exit(1)

    if not 0.0 <= args.write_ratio <= 1.0:
        print("--write-ratio must be between 0.0 and 1.0.")
        sys.exit(1)

    if args.operation_mode in {"write-only", "mixed"} and args.test_model_id not in WRITE_SUPPORTED_MODELS:
        supported_models = ", ".join(sorted(WRITE_SUPPORTED_MODELS))
        print(f"Write benchmarking is currently supported only for: {supported_models}.")
        sys.exit(1)

    if args.scopeUpperBound <= 0:
        print("--scopeUpperBound must be greater than 0.")
        sys.exit(1)

    if args.workspaceUpperBound <= 0:
        print("--workspaceUpperBound must be greater than 0.")
        sys.exit(1)

    if args.teamsPerWorkspace <= 0:
        print("--teamsPerWorkspace must be greater than 0.")
        sys.exit(1)

    if args.check_types is not None:
        requested_check_types = {ct.strip() for ct in args.check_types.split(",") if ct.strip()}
        invalid_check_types = requested_check_types - VALID_CHECK_TYPES
        if invalid_check_types:
            print(f"Invalid --check-types values: {invalid_check_types}. Valid choices: {VALID_CHECK_TYPES}")
            sys.exit(1)

        model_allowed = set(DEFAULT_CHECK_TYPES.get(args.test_model_id, []))
        if model_allowed:
            incompatible = requested_check_types - model_allowed
            if incompatible:
                print(f"--check-types values {incompatible} are incompatible with --test-model-id {args.test_model_id}. Allowed: {model_allowed}")
                sys.exit(1)

def read_config(config_file):
    if not os.path.exists(config_file):
        print(f"Configuration file {config_file} not found.")
        sys.exit(1)
    try:
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)
            api_url = config.get('api_url')
            store_id = config.get('store_id')
            model_id = config.get('model_id')
            if not api_url or not store_id or not model_id:
                print(f"'api_url' or 'store_id' or 'model_id' not defined in {config_file}.")
                sys.exit(1)
            return api_url, store_id, model_id
    except Exception as e:
        print(f"Error reading configuration file: {e}")
        sys.exit(1)

def get_cpu_usage():
    return psutil.cpu_percent(interval=None)

def get_memory_usage():
    return psutil.virtual_memory().percent


def pick_random_index(upper_bound):
    if upper_bound <= 1:
        return 0
    return random.randint(1, upper_bound - 1)


def build_check_payload(model_name, model_id, userUpperBound, objectUpperBound,
                        agentUpperBound=50, folderUpperBound=20, check_types=None):
    """Returns (payload_dict, check_type_str)."""
    if model_name == "model_8":
        types = check_types or DEFAULT_CHECK_TYPES["model_8"]
        check_type = random.choice(types)
        if check_type == "agent_doc":
            return {
                "authorization_model_id": model_id,
                "tuple_key": {
                    "user": f"agent:a{pick_random_index(agentUpperBound)}",
                    "relation": "can_read",
                    "object": f"doc:d{pick_random_index(objectUpperBound)}",
                },
                "context": {"current_time": "2029-12-31T12:00:00Z"},
            }, check_type
        elif check_type == "agent_folder":
            return {
                "authorization_model_id": model_id,
                "tuple_key": {
                    "user": f"agent:a{pick_random_index(agentUpperBound)}",
                    "relation": "can_view",
                    "object": f"folder:f{pick_random_index(folderUpperBound)}",
                },
                "context": {"current_time": "2029-12-31T12:00:00Z"},
            }, check_type
        elif check_type == "human_doc":
            tuple_key = {
                "user": f"user:u{pick_random_index(userUpperBound)}",
                "relation": "can_read",
                "object": f"doc:d{pick_random_index(objectUpperBound)}",
            }
        elif check_type == "human_folder":
            tuple_key = {
                "user": f"user:u{pick_random_index(userUpperBound)}",
                "relation": "can_view",
                "object": f"folder:f{pick_random_index(folderUpperBound)}",
            }
        else:
            raise ValueError(f"Unsupported model_8 check type '{check_type}'")
        return {"authorization_model_id": model_id, "tuple_key": tuple_key}, check_type

    if model_name == "model_slack_overlay":
        types = check_types or DEFAULT_CHECK_TYPES["model_slack_overlay"]
        check_type = random.choice(types)
        channel_id = f"channel:c{pick_random_index(objectUpperBound)}"

        if check_type == "slack_agent_writer":
            tuple_key = {
                "user": f"agent:a{pick_random_index(agentUpperBound)}",
                "relation": "writer",
                "object": channel_id,
            }
            payload = {
                "authorization_model_id": model_id,
                "tuple_key": tuple_key,
                "context": {
                    "current_time": "2029-12-31T12:00:00Z",
                    "purpose": "marketing",
                },
            }
        elif check_type == "slack_human_writer":
            tuple_key = {
                "user": f"user:u{pick_random_index(userUpperBound)}",
                "relation": "writer",
                "object": channel_id,
            }
            payload = {
                "authorization_model_id": model_id,
                "tuple_key": tuple_key,
            }
        else:
            raise ValueError(f"Unsupported model_slack_overlay check type '{check_type}'")

        return payload, check_type

    form = REQUEST_FORMS.get(model_name)
    if not form:
        raise ValueError(f"Request form for model '{model_name}' not found.")
    request_payload = copy.deepcopy(form)
    request_payload["authorization_model_id"] = model_id
    random_user = pick_random_index(userUpperBound)
    random_doc = pick_random_index(objectUpperBound)
    return substitute_placeholders(request_payload, user=random_user, doc=random_doc), "default"


def build_model_8_write_payload(model_id, request_number, userUpperBound, agentUpperBound, scopeUpperBound):
    """Write 3 delegation tuples to existing users/agents: delegatee + actor + holder.
    A fresh session ID is generated per call so writes are unique across reruns.
    Scope index is bounded to the team scopes already in the dataset.
    """
    agent_idx = pick_random_index(agentUpperBound)
    user_idx = pick_random_index(userUpperBound)
    scope_idx = random.randint(0, max(0, scopeUpperBound - 1))
    session_id = f"session:bench_{int(time.time() * 1000)}_{request_number}"

    tuple_keys = [
        {"user": f"agent:a{agent_idx}", "relation": "delegatee", "object": f"user:u{user_idx}"},
        {"user": f"agent:a{agent_idx}", "relation": "actor",     "object": session_id},
        {"user": session_id,            "relation": "holder",    "object": f"scope:org/team{scope_idx}"},
    ]

    return {
        "authorization_model_id": model_id,
        "writes": {"tuple_keys": tuple_keys},
    }, {
        "tuple_count": len(tuple_keys),
    }


def build_slack_overlay_write_payload(model_id, request_number, userUpperBound, agentUpperBound,
                                      workspaceUpperBound, teamsPerWorkspace):
    """Write 3 delegation tuples to existing users/agents in Slack overlay: delegatee + actor + holder."""
    agent_idx = pick_random_index(agentUpperBound)
    user_idx = pick_random_index(userUpperBound)
    workspace_idx = random.randint(0, max(0, workspaceUpperBound - 1))
    team_idx = random.randint(0, max(0, teamsPerWorkspace - 1))
    session_id = f"session:bench_{int(time.time() * 1000)}_{request_number}"

    tuple_keys = [
        {"user": f"agent:a{agent_idx}", "relation": "delegatee", "object": f"user:u{user_idx}"},
        {"user": f"agent:a{agent_idx}", "relation": "actor", "object": session_id},
        {"user": session_id, "relation": "holder", "object": f"scope:ws{workspace_idx}/team{team_idx}"},
    ]

    return {
        "authorization_model_id": model_id,
        "writes": {"tuple_keys": tuple_keys},
    }, {
        "tuple_count": len(tuple_keys),
    }


def build_write_payload(model_name, model_id, request_number, userUpperBound, agentUpperBound, scopeUpperBound,
                        workspaceUpperBound, teamsPerWorkspace):
    if model_name == "model_8":
        return build_model_8_write_payload(model_id, request_number, userUpperBound, agentUpperBound, scopeUpperBound)
    if model_name == "model_slack_overlay":
        return build_slack_overlay_write_payload(
            model_id, request_number, userUpperBound, agentUpperBound, workspaceUpperBound, teamsPerWorkspace,
        )
    raise ValueError(f"Write workload for model '{model_name}' is not implemented.")


def choose_operation(operation_mode, write_ratio):
    if operation_mode == "check-only":
        return "check"
    if operation_mode == "write-only":
        return "write"
    return "write" if random.random() < write_ratio else "check"


def send_operation(api_url, store_id, model_id, model_name, operation_mode, write_ratio,
                   userUpperBound, objectUpperBound, agentUpperBound, folderUpperBound,
                   scopeUpperBound, workspaceUpperBound, teamsPerWorkspace,
                   check_types, request_number):
    operation = choose_operation(operation_mode, write_ratio)
    check_type = "n/a"
    start_time = time.time()

    try:
        if operation == "check":
            request_payload, check_type = build_check_payload(
                model_name, model_id, userUpperBound, objectUpperBound,
                agentUpperBound, folderUpperBound, check_types,
            )
            response = requests.post(
                f"{api_url}/stores/{store_id}/check",
                headers={"Content-Type": "application/json"},
                json=request_payload,
            )
            response.raise_for_status()
            response_body = response.json()
            tuple_count = 1
            allowed = response_body.get("allowed", False)
        else:
            request_payload, write_metadata = build_write_payload(
                model_name,
                model_id,
                request_number,
                userUpperBound,
                agentUpperBound,
                scopeUpperBound,
                workspaceUpperBound,
                teamsPerWorkspace,
            )
            response = requests.post(
                f"{api_url}/stores/{store_id}/write",
                headers={"Content-Type": "application/json"},
                json=request_payload,
            )
            response.raise_for_status()
            tuple_count = write_metadata["tuple_count"]
            allowed = None

        end_time = time.time()
        return {
            'operation': operation,
            'check_type': check_type,
            'execution_time': end_time - start_time,
            'status_code': response.status_code,
            'cpu_usage': get_cpu_usage(),
            'memory_usage': get_memory_usage(),
            'success': True,
            'allowed': allowed,
            'tuple_count': tuple_count,
        }
    except requests.exceptions.RequestException as e:
        print(f"{operation.title()} request error: {e}")
        status_code = e.response.status_code if e.response is not None else None
        return {
            'operation': operation,
            'check_type': check_type,
            'execution_time': None,
            'status_code': status_code,
            'cpu_usage': None,
            'memory_usage': None,
            'success': False,
            'allowed': False if operation == 'check' else None,
            'tuple_count': 1 if operation == 'check' else None,
        }


def benchmark(api_url, store_id, model_id, test_model_id, requests_count, concurrency,
              userUpperBound, objectUpperBound, operation_mode, write_ratio,
              agentUpperBound, folderUpperBound, scopeUpperBound,
              workspaceUpperBound, teamsPerWorkspace, check_types):
    results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_request = {
            executor.submit(
                send_operation,
                api_url,
                store_id,
                model_id,
                test_model_id,
                operation_mode,
                write_ratio,
                userUpperBound,
                objectUpperBound,
                agentUpperBound,
                folderUpperBound,
                scopeUpperBound,
                workspaceUpperBound,
                teamsPerWorkspace,
                check_types,
                i,
            ): i for i in range(requests_count)
        }

        for i, future in enumerate(concurrent.futures.as_completed(future_to_request), start=1):
            result = future.result()
            current_time = time.time()

            elapsed_time = current_time - start_time
            result['requests_per_second'] = i / elapsed_time if elapsed_time > 0 else 0
            result['sequence'] = i
            results.append(result)

            if result['execution_time'] is not None:
                check_label = f"/{result['check_type']}" if result['check_type'] != 'n/a' else ""
                print(
                    f"Operation {i}/{requests_count} - "
                    f"Type : {result['operation']}{check_label} - "
                    f"Execution Time : {result['execution_time']:.4f}s - "
                    f"Code : {result['status_code']} - "
                    f"Allowed : {result['allowed']}"
                )
            else:
                check_label = f"/{result['check_type']}" if result['check_type'] != 'n/a' else ""
                print(f"Operation {i}/{requests_count} - Type : {result['operation']}{check_label} - Request failed.")

    total_duration = time.time() - start_time
    return results, total_duration


def valid_execution_times(results, operation=None, allowed_only=False):
    values = []
    for result in results:
        if result['execution_time'] is None:
            continue
        if operation is not None and result['operation'] != operation:
            continue
        if allowed_only and result.get('allowed') is not True:
            continue
        values.append(result['execution_time'])
    return values


def print_operation_summary(results, operation):
    operation_results = [result for result in results if result['operation'] == operation]
    if not operation_results:
        return

    successful_requests = sum(1 for result in operation_results if result['success'])
    execution_times = valid_execution_times(operation_results)

    print(f"{operation.capitalize()} operations: {successful_requests}/{len(operation_results)} succeeded.")
    if execution_times:
        print(f"Average {operation} execution time (milliseconds) : {np.mean(execution_times) * 1000}")
        print(f"P95 {operation} execution time (milliseconds) : {np.percentile(execution_times, 95) * 1000}")
    else:
        print(f"No successful {operation} timing data to summarize.")

    if operation == 'check':
        allowed_requests = sum(1 for result in operation_results if result.get('allowed') is True)
        allowed_execution_times = valid_execution_times(operation_results, allowed_only=True)
        print(f"Allowed check requests : {allowed_requests}/{len(operation_results)}")
        if allowed_execution_times:
            print(f"Average execution time of allowed checks (milliseconds) : {np.mean(allowed_execution_times) * 1000:.3f}")

        check_type_values = sorted({r.get('check_type', 'default') for r in operation_results})
        if check_type_values != ['default']:
            print("  Check-type breakdown:")
            for ct in check_type_values:
                ct_results = [r for r in operation_results if r.get('check_type') == ct]
                ct_success = sum(1 for r in ct_results if r['success'])
                ct_allowed = sum(1 for r in ct_results if r.get('allowed') is True)
                ct_times = valid_execution_times(ct_results)
                if ct_times:
                    print(f"    [{ct}]: {ct_success}/{len(ct_results)} ok, "
                          f"{ct_allowed} allowed, "
                          f"avg {np.mean(ct_times) * 1000:.2f}ms, "
                          f"p95 {np.percentile(ct_times, 95) * 1000:.2f}ms")
                else:
                    print(f"    [{ct}]: {ct_success}/{len(ct_results)} ok, no timing data")

    if operation == 'write':
        written_tuples = sum(result.get('tuple_count') or 0 for result in operation_results if result['success'])
        print(f"Total tuples written successfully : {written_tuples}")


def generate_plots(results, output_file=None):
    valid_results = [result for result in results if result['execution_time'] is not None]
    if not valid_results:
        print("No valid data to display.")
        return

    request_numbers = [result['sequence'] for result in valid_results]
    execution_times_valid = [result['execution_time'] for result in valid_results]
    cpu_usage_valid = [result['cpu_usage'] for result in valid_results]
    memory_usage_valid = [result['memory_usage'] for result in valid_results]
    requests_per_second_valid = [result['requests_per_second'] for result in valid_results]
    check_results = [result for result in valid_results if result['operation'] == 'check']
    write_results = [result for result in valid_results if result['operation'] == 'write']

    plt.figure(figsize=(12, 8))

    plt.subplot(2, 2, 1)
    if check_results:
        plt.plot(
            [result['sequence'] for result in check_results],
            [result['execution_time'] for result in check_results],
            label="Check Execution Time (s)",
        )
    if write_results:
        plt.plot(
            [result['sequence'] for result in write_results],
            [result['execution_time'] for result in write_results],
            label="Write Execution Time (s)",
        )
    if not check_results and not write_results:
        plt.plot(request_numbers, execution_times_valid, label="Execution Time (s)")
    plt.title("Operation Execution Time")
    plt.xlabel("Operation Number")
    plt.ylabel("Time (s)")
    plt.legend()

    plt.subplot(2, 2, 2)
    plt.plot(request_numbers, cpu_usage_valid, label="CPU Usage (%)", color='red')
    plt.title("CPU Usage")
    plt.xlabel("Operation Number")
    plt.ylabel("CPU (%)")
    plt.legend()

    plt.subplot(2, 2, 3)
    plt.plot(request_numbers, memory_usage_valid, label="Memory Usage (%)", color='green')
    plt.title("Memory Usage")
    plt.xlabel("Operation Number")
    plt.ylabel("Memory (%)")
    plt.legend()

    plt.subplot(2, 2, 4)
    plt.plot(request_numbers, requests_per_second_valid, label="Requests per Second", color='purple')
    plt.title("Operations per Second")
    plt.xlabel("Operation Number")
    plt.ylabel("Operations per Second")
    plt.legend()

    plt.tight_layout()

    if output_file:
        results_dir = os.path.dirname(output_file)
        if results_dir and not os.path.exists(results_dir):
            os.makedirs(results_dir, exist_ok=True)

        plt.savefig(output_file)
        print(f"Graphs saved in file {output_file}")
    else:
        plt.show()


def save_to_csv(results, csv_path):
    results_dir = os.path.dirname(csv_path)
    if results_dir and not os.path.exists(results_dir):
        os.makedirs(results_dir, exist_ok=True)

    with open(csv_path, mode='w', newline='') as csv_file:
        fieldnames = [
            'Request',
            'Operation',
            'Check Type',
            'Execution Time (s)',
            'CPU (%)',
            'Memory (%)',
            'Requests/s',
            'Status Code',
            'Success',
            'Allowed',
            'Tuple Count',
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            if result['execution_time'] is not None:
                writer.writerow({
                    'Request': result['sequence'],
                    'Operation': result['operation'],
                    'Check Type': result.get('check_type', 'n/a'),
                    'Execution Time (s)': f"{result['execution_time']:.6f}",
                    'CPU (%)': f"{result['cpu_usage']:.1f}",
                    'Memory (%)': f"{result['memory_usage']:.1f}",
                    'Requests/s': f"{result['requests_per_second']:.6f}",
                    'Status Code': result['status_code'],
                    'Success': result['success'],
                    'Allowed': result['allowed'],
                    'Tuple Count': result['tuple_count'],
                })
            else:
                writer.writerow({
                    'Request': result['sequence'],
                    'Operation': result['operation'],
                    'Check Type': result.get('check_type', 'n/a'),
                    'Execution Time (s)': '',
                    'CPU (%)': '',
                    'Memory (%)': '',
                    'Requests/s': f"{result['requests_per_second']:.6f}",
                    'Status Code': result['status_code'],
                    'Success': result['success'],
                    'Allowed': result['allowed'],
                    'Tuple Count': result['tuple_count'],
                })
    print(f"Benchmark results saved to the file {csv_path}")


if __name__ == "__main__":
    args = parse_arguments()
    validate_arguments(args)

    if args.api_url is None or args.store_id is None:
        api_url_from_config, store_id_from_config, model_id_from_config = read_config(args.config_file)
        if args.api_url is None:
            args.api_url = api_url_from_config
        if args.store_id is None:
            args.store_id = store_id_from_config
        if args.model_id is None:
            args.model_id = model_id_from_config

    if args.check_types is None:
        check_types = DEFAULT_CHECK_TYPES.get(args.test_model_id)
    else:
        check_types = [ct.strip() for ct in args.check_types.split(",") if ct.strip()]

    results, total_duration = benchmark(
        api_url=args.api_url,
        store_id=args.store_id,
        model_id=args.model_id,
        test_model_id=args.test_model_id,
        requests_count=args.requests_count,
        concurrency=args.concurrency,
        userUpperBound=args.userUpperBound,
        objectUpperBound=args.objectUpperBound,
        operation_mode=args.operation_mode,
        write_ratio=args.write_ratio,
        agentUpperBound=args.agentUpperBound,
        folderUpperBound=args.folderUpperBound,
        scopeUpperBound=args.scopeUpperBound,
        workspaceUpperBound=args.workspaceUpperBound,
        teamsPerWorkspace=args.teamsPerWorkspace,
        check_types=check_types,
    )

    successful_requests = sum(1 for result in results if result['success'])
    execution_times = valid_execution_times(results)
    memory_usage = [result['memory_usage'] for result in results if result['memory_usage'] is not None]

    print(f"Benchmark completed in {total_duration:.2f} seconds. {successful_requests}/{args.requests_count} operations succeeded.")
    if execution_times:
        print("Average execution time of operations (milliseconds) :", np.mean(execution_times) * 1000)
        print("P95 execution time of operations (milliseconds) :", np.percentile(execution_times, 95) * 1000)
    if memory_usage:
        print("Average memory usage during operations (%) :", np.mean(memory_usage))

    print_operation_summary(results, 'check')
    print_operation_summary(results, 'write')

    timestamp = datetime.now().strftime("%m%d_%H%M%S")
    base_filename = f"benchmark_{timestamp}_{args.concurrency}_{args.requests_count}_{args.operation_mode}"
    output_file = os.path.join("results/" + args.test_model_id, f"{base_filename}.png")

    generate_plots(results, output_file=output_file)

    csv_path = os.path.join("results/" + args.test_model_id, f"{base_filename}.csv")
    save_to_csv(results, csv_path)