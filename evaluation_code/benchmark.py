#!/usr/bin/env python3
import time
import psutil
import requests
import matplotlib.pyplot as plt
from datetime import datetime
import argparse
import sys
import yaml
import os
import numpy as np  
import concurrent.futures
import csv
import random


# Helper function to recursively substitute placeholders in a dictionary.
def substitute_placeholders(obj, user, doc):
    if isinstance(obj, str):
        return obj.format(user=user, doc=doc)
    elif isinstance(obj, dict):
        return {k: substitute_placeholders(v, user, doc) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [substitute_placeholders(item, user, doc) for item in obj]
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
            "object": "doc:d{doc}" },
            "context": {
              "current_time": "2023-01-01T00:04:00Z"
            }}, 
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

def parse_arguments():
    parser = argparse.ArgumentParser(description="Benchmark script for OpenFGA")
    parser.add_argument('--api-url', type=str, default=None, help="OpenFGA API URL (default: value from config/store_config.yaml)")
    parser.add_argument('--store-id', type=str, default=None, help="OpenFGA store ID (default: value from config/store_config.yaml)")
    parser.add_argument('--model-id', type=str, default=None, help="OpenFGA Authorization Model ID (default: value from config/store_config.yaml)")
    parser.add_argument('--requests-count', type=int, default=1000, help="Number of requests to send (default: 100)")
    parser.add_argument('--concurrency', type=int, default=100,
                        help="Number of threads for concurrent requests")
    parser.add_argument('--config-file', type=str, default='config/store_config.yaml', help="Path to configuration file (default: config/store_config.yaml)")
    parser.add_argument('--test-model-id', type=str, default="model_1", help="The test model id to pick sample request")
    parser.add_argument('--upperBound', type=int, default=50,help="Upper limit for the random request information")
    return parser.parse_args()

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



def send_request(api_url, store_id, model_id, model_name, upperBound):
    # Pick random values for substitution.
    random_user = random.randint(1, upperBound-1)
    random_doc = random.randint(1, upperBound-1)
    

    # Select the request form from the dictionary.
    form = REQUEST_FORMS.get(model_name)
    if not form:
        raise ValueError(f"Request form for model '{model_name}' not found.")
    
    # Create a deep copy of the form and set the model id.
    request_payload = form.copy()
    request_payload["authorization_model_id"] = model_id
    
    # Process the tuple_key part, substituting placeholders.
    # We expect the template to include {user} and {doc} placeholders.
    request_payload["tuple_key"] = substitute_placeholders(
        request_payload["tuple_key"], user=random_user, doc=random_doc
    )
    start_time = time.time()
    try:
        response = requests.post(
            f"{api_url}/stores/{store_id}/check", 
            headers={"Content-Type": "application/json"},
            json=request_payload
        )
        
        end_time = time.time()
        response.raise_for_status()
        return {
            'execution_time': end_time - start_time,
            'status_code': response.status_code,
            'cpu_usage': get_cpu_usage(),      # Assumes get_cpu_usage() is defined
            'memory_usage': get_memory_usage(),# Assumes get_memory_usage() is defined
            'success': True
        }
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return {
            'execution_time': 0.0,
            'status_code': None,
            'cpu_usage': None,
            'memory_usage': None,
            'success': False
        }


def benchmark(api_url, store_id, model_id, test_model_id, requests_count, concurrency, upperBound):
    execution_times = []
    cpu_usage = []
    memory_usage = []
    requests_per_second = []
    successful_requests = 0

    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_request = {
            executor.submit(send_request, api_url, store_id, model_id, test_model_id, upperBound): i for i in range(requests_count)
        }

        for i, future in enumerate(concurrent.futures.as_completed(future_to_request)):
            result = future.result()
            current_time = time.time()

            if result['execution_time'] is not None:
                execution_times.append(result['execution_time'])
                cpu_usage.append(result['cpu_usage'])
                memory_usage.append(result['memory_usage'])

                if result['status_code'] == 200:
                    successful_requests += 1

                # calculate requests per second
                elapsed_time = current_time - start_time
                if elapsed_time > 0:
                    req_per_sec = (i + 1) / elapsed_time
                    requests_per_second.append(req_per_sec)
                else:
                    requests_per_second.append(0)
            else:
                execution_times.append(None)
                cpu_usage.append(None)
                memory_usage.append(None)
                requests_per_second.append(None)

            # show benchmark status 
            if result['execution_time'] is not None:
                print(f"Request {i+1}/{requests_count} - "
                      f"Execution Time : {result['execution_time']:.4f}s - "
                      f"Code : {result['status_code']}")
            else:
                print(f"Request {i+1}/{requests_count} - Request failed.")

    total_duration = time.time() - start_time

    return execution_times, cpu_usage, memory_usage, requests_per_second, successful_requests, total_duration

def generate_plots(execution_times, cpu_usage, memory_usage, requests_per_second, output_file=None):
    valid_indices = [i for i, x in enumerate(execution_times) if x is not None]
    if not valid_indices:
        print("No valid data to display.")
        return

    execution_times_valid = [execution_times[i] for i in valid_indices]
    cpu_usage_valid = [cpu_usage[i] for i in valid_indices]
    memory_usage_valid = [memory_usage[i] for i in valid_indices]
    requests_per_second_valid = [requests_per_second[i] for i in valid_indices]
    request_numbers = [i+1 for i in valid_indices]

    plt.figure(figsize=(12, 8))

    plt.subplot(2, 2, 1)
    plt.plot(request_numbers, execution_times_valid, label="Execution Time (s)")
    plt.title("Request Execution Time")
    plt.xlabel("Request Number")
    plt.ylabel("Time (s)")
    plt.legend()

    plt.subplot(2, 2, 2)
    plt.plot(request_numbers, cpu_usage_valid, label="CPU Usage (%)", color='red')
    plt.title("CPU Usage")
    plt.xlabel("Request Number")
    plt.ylabel("CPU (%)")
    plt.legend()

    plt.subplot(2, 2, 3)
    plt.plot(request_numbers, memory_usage_valid, label="Memory Usage (%)", color='green')
    plt.title("Memory Usage")
    plt.xlabel("Request Number")
    plt.ylabel("Memory (%)")
    plt.legend()

    plt.subplot(2, 2, 4)
    plt.plot(request_numbers, requests_per_second_valid, label="Requests per Second", color='purple')
    plt.title("Requests per Second")
    plt.xlabel("Request Number")
    plt.ylabel("Requests per Second")
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


def save_to_csv(execution_times, cpu_usage, memory_usage, requests_per_second, csv_path):
    """Saves benchmark results to a CSV file."""
    # Create the 'results' directory if it does not exist
    results_dir = os.path.dirname(csv_path)
    if results_dir and not os.path.exists(results_dir):
        os.makedirs(results_dir, exist_ok=True)

    with open(csv_path, mode='w', newline='') as csv_file:
        fieldnames = [
            'Request',
            'Execution Time (s)',
            'CPU (%)',
            'Memory (%)',
            'Requests/s'
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(len(execution_times)):
            if execution_times[i] is not None:
                writer.writerow({
                    'Request': i + 1,
                    'Execution Time (s)': f"{execution_times[i]:.6f}",
                    'CPU (%)': f"{cpu_usage[i]:.1f}",
                    'Memory (%)': f"{memory_usage[i]:.1f}",
                    'Requests/s': f"{requests_per_second[i]:.6f}"
                })
            else:
                writer.writerow({
                    'Request': i + 1,
                    'Execution Time (s)': '',
                    'CPU (%)': '',
                    'Memory (%)': '',
                    'Requests/s': ''
                })
    print(f"Benchmark results saved to the file {csv_path}")


if __name__ == "__main__":
    args = parse_arguments()
  
    if args.api_url is None or args.store_id is None:
        api_url_from_config, store_id_from_config, model_id_from_config = read_config(args.config_file)
        if args.api_url is None:
            args.api_url = api_url_from_config
        if args.store_id is None:
            args.store_id = store_id_from_config
        if args.model_id is None:
            args.model_id = model_id_from_config

    
    execution_times, cpu_usage, memory_usage, requests_per_second, successful_requests, total_duration = benchmark(
        api_url=args.api_url,
        store_id=args.store_id,
        model_id=args.model_id,
        test_model_id=args.test_model_id,
        requests_count=args.requests_count,
        concurrency=args.concurrency,
        upperBound=args.upperBound
    )


    print(f"Benchmark completed in {total_duration:.2f} seconds. {successful_requests}/{args.requests_count} requests succeeded.")
    average = np.mean(execution_times) 
 
    print("Average Execution time of Requests (milliseconds) :", average * 1000)
    p = np.percentile(execution_times, 95)
    print("P95 of Execution time of Requests (milliseconds) :", p * 1000)
    averageMem = np.mean(memory_usage)
    print("Average Execution time of Requests :", averageMem)

    # generate plots
    timestamp = datetime.now().strftime("%m%d_%H%M%S")
    output_file = os.path.join("results/"+args.test_model_id, f"benchmark_{timestamp}_{args.concurrency}_{args.requests_count}.png")

    generate_plots(execution_times, cpu_usage, memory_usage, requests_per_second, output_file=output_file)

    csv_path = os.path.join("results/"+args.test_model_id, f"benchmark_{timestamp}_{args.concurrency}_{args.requests_count}.csv")
    save_to_csv(execution_times, cpu_usage, memory_usage, requests_per_second, csv_path)