# Open Science Artifacts

All artifacts are included in the submitted supplementary material and are accessible to reviewers through the anonymous artifact URL:

<https://gitfront.io/r/anonymous-submission/wFR5K9imudwg/compositional-paper/>

This README enumerates the artifacts necessary to evaluate and reproduce the paper's core contributions.

## 1. Documentation

- `openfga/general/6.gdrive/agent-ai/README.md`  
  Official documentation of the GDrive use case, model decisions, and expected performance characteristics.

- `openfga/general/slack/README.md`  
  Official documentation of the Slack benchmark scenario, authorization semantics, and experimental parameters.

- `openfga/general/Evaluation_Commands`  
  Step-by-step execution commands for reproducing the benchmark.

## 2. Benchmarking Infrastructure

- `openfga/general/benchmark.py`  
  Main benchmark driver implementing the evaluation protocol. Executes checks, collects performance metrics, and logs execution traces.

- `openfga/general/setup_and_load.sh`  
  Orchestration script for store initialization, model loading, and tuple population. Handles environment configuration and data ingestion required to prepare benchmarks.

- `openfga/general/setup_store.sh`  
  Store creation and model schema initialization. Deploys authorization models to OpenFGA instances.

- `openfga/general/delete_store.sh`  
  Cleanup utility between benchmark runs.

## 3. Data Generation and Tuple Population

- `openfga/general/openfga_tuple_dataset_generator.py`  
  Generates synthetic relation tuple datasets for the GDrive scenario. Implements domain-specific rules for creating user-resource relationships at scale.

- `openfga/general/openfga_tuple_slack_generator.py`  
  Generates synthetic relation tuple datasets for the Slack scenario. Populates workspace, channel, and user relationships according to Slack's authorization model.

- `openfga/general/rebuild_analysis_from_raw.py`  
  Post-processing utility that transforms raw benchmark output into analysis-ready formats. Aggregates metrics and computes summary statistics.

## 4. Authorization Models

- `openfga/general/6.gdrive/gdrive-domain.fga`  
  Core GDrive model defining relationships such as owners, editors, and viewers, together with permission logic for document access control.

- `openfga/general/6.gdrive/agent-ai/`  
  GDrive overlay model variant with agentic delegation and scoping.

- `openfga/general/slack/model.fga`  
  Core Slack model defining workspace and channel permission semantics.

- `openfga/general/slack/agent-ai/`  
  Slack overlay model variant with agentic delegation and scoping.

## 5. Relation Tuple Datasets

- `openfga/general/6.gdrive/agent-ai/generated/`  
  Synthetic relation tuples for the GDrive scenario. Contains domain and overlay files for G1--G7. (G8 files are around 80MiB so were excluded due to size limit; but they can be reproduced using the scripts as shown in the commands.)

- `openfga/general/slack/agent-ai/generated/`  
  Synthetic relation tuples for the Slack scenario. Contains domain and overlay files for S1--S4. (S5 files are around 50 MiB so were excluded from the repository due to size limit; but they can be reproduced using the scripts as shown in the commands.)

## 6. Experimental Results and Analysis

- `openfga/general/results/analysis/`  
  Aggregated analysis outputs, summary statistics, and processed metrics derived from raw benchmark runs.

- `openfga/general/results/model_7/`  
  Benchmark CSV outputs for the baseline authorization model across all GDrive datasets. These correspond to check-only queries on G1--G8.

- `openfga/general/results/model_8/`  
  Benchmark CSV outputs for the GDrive overlay variant across all datasets. These correspond to mixed query types on G1--G8.

- `openfga/general/results/model_slack_domain/`  
  Benchmark CSV outputs for the Slack domain model. These correspond to check-only queries on S1--S5.

- `openfga/general/results/model_slack_overlay/`  
  Benchmark CSV outputs for the Slack overlay variant. These correspond to mixed query types on S1--S5.