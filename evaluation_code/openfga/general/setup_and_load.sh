#!/bin/sh
set -e

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <model-file> [bootstrap-tuples-file] [benchmark.py args ...]"
  exit 1
fi

MODEL_FILE="$1"
BOOTSTRAP_TUPLES_FILE=""

if [ "$#" -ge 2 ] && [ "${2#--}" = "$2" ]; then
  BOOTSTRAP_TUPLES_FILE="$2"
  shift 2
else
  shift 1
fi

echo "OpenFGA is ready. Running initialization scripts..."

./setup_store.sh "$MODEL_FILE" "$BOOTSTRAP_TUPLES_FILE"

echo "Initialization completed."

echo "Starting performance benchmark..."

mkdir -p results && echo "created results directory."

python3 ./benchmark.py "$@"


# ./scripts/general/delete_store.sh
# echo "Benchmark completed. The results are available in results"



