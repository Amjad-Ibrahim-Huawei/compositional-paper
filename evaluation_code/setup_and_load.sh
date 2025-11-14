#!/bin/sh
set -e  # stop script on error

# Path to the configuration file
CONFIG_FILE="config/store_config.yaml"

# Check if the configuration file exists
if [ ! -f "$CONFIG_FILE" ]; then
  echo "The configuration file $CONFIG_FILE was not found."
  exit 1
fi

# Read variables from the configuration file
FGA_API_URL=$(yq -r '.api_url' "$CONFIG_FILE" | tr -d '"')
FGA_STORE_ID=$(yq -r '.store_id' "$CONFIG_FILE" | tr -d '"')

# Check if the variables are defined
if [ -z "$FGA_API_URL" ] || [ -z "$FGA_STORE_ID" ]; then
  echo "The variables FGA_API_URL or FGA_STORE_ID are not defined in $CONFIG_FILE."
  exit 1
fi

# check the format  FGA_API_URL
if ! echo "$FGA_API_URL" | grep -q "^http"; then
  echo "FGA_API_URL is invalid"
  exit 1
fi



# Export environment variables
export FGA_API_URL
export FGA_STORE_ID

echo "OpenFGA is ready. Running initialization scripts..."

# Load the store
./setup_store.sh $1 $2

echo "Initialization completed."

echo "Starting performance benchmark..."

# Create the directory for results if necessary
mkdir -p results && echo "created results directory."

# Run the benchmark script defaults will be used	
python3 ./benchmark.py $3 $4 $5 $6


# ./scripts/general/delete_store.sh
# echo "Benchmark completed. The results are available in results"



