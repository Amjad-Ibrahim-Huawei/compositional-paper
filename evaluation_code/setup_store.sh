#!/bin/bash

# Définissez le chemin vers le fichier de configuration
CONFIG_DIR="config"
CONFIG_FILE="$CONFIG_DIR/store_config.yaml"

# Créez le dossier de configuration s'il n'existe pas
# mkdir -p "$CONFIG_DIR"

# Définissez l'URL de l'API OpenFGA
API_URL="http://localhost:8080"

# Nom du store à créer
STORE_NAME="General"

response=$(fga store create --model $1)

echo $response
# extract STORE_ID
STORE_ID=$(echo "$response" | jq -r '.store.id')
MODEL_ID=$(echo "$response" | jq -r '.model.authorization_model_id')

# verify result
if [ -z "$STORE_ID" ] || [ "$STORE_ID" == "null" ]; then
  echo "Error creating the store"
  echo "API response : $response"
  exit 1
fi

echo "Store and model successfully created. Store ID: $STORE_ID"


# write tuples to the store

response=$(fga tuple write --store-id=$STORE_ID --file $2)


# Enregistrer le store_id et api_url dans le fichier de configuration
cat > "$CONFIG_FILE" <<EOL
store_id: "$STORE_ID"
model_id: "$MODEL_ID"
api_url: "$API_URL"
EOL

echo "Store configuration written to $CONFIG_FILE."


