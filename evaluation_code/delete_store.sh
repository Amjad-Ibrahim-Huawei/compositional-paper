#!/bin/bash

CONFIG_FILE="config/store_config.yaml"

# check configuration file
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Config file $CONFIG_FILE does not exist."
  exit 1
fi

FGA_API_URL=$(yq -r '.api_url' "$CONFIG_FILE" | tr -d '"')
FGA_STORE_ID=$(yq -r '.store_id' "$CONFIG_FILE" | tr -d '"')


if [ -z "$FGA_API_URL" ] || [ -z "$FGA_STORE_ID" ]; then
  echo "Variables FGA_API_URL or FGA_STORE_ID are not set in $CONFIG_FILE."
  exit 1
fi


# this only deletes the store, but the data related need to be cleaned TODO
curl -X DELETE  "$FGA_API_URL/stores/$FGA_STORE_ID"


echo "Store sucessfully deleted."
