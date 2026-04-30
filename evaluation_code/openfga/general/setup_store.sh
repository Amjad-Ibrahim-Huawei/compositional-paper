#!/bin/bash

CONFIG_DIR="config"
CONFIG_FILE="$CONFIG_DIR/store_config.yaml"

API_URL="http://localhost:8080"

STORE_NAME="General"

response=$(fga store create --model "$1")

echo $response

STORE_ID=$(echo "$response" | jq -r '.store.id')
MODEL_ID=$(echo "$response" | jq -r '.model.authorization_model_id')

if [ -z "$STORE_ID" ] || [ "$STORE_ID" == "null" ]; then
  echo "Error creating the store"
  echo "API response : $response"
  exit 1
fi

echo "Store and model successfully created. Store ID: $STORE_ID"

if [ -n "$2" ]; then
  if [ ! -f "$2" ]; then
    echo "Tuple bootstrap file not found: $2"
    exit 1
  fi

  response=$(fga tuple write --store-id="$STORE_ID" --file "$2")
  # echo "$response"
fi


cat > "$CONFIG_FILE" <<EOL
store_id: "$STORE_ID"
model_id: "$MODEL_ID"
api_url: "$API_URL"
EOL

echo "Store configuration written to $CONFIG_FILE."


