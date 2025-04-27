#!/bin/bash

# Set log file
LOGFILE="radkit-automation-$(date +%Y%m%d-%H%M%S).log"
echo "Logging to $LOGFILE"
exec > >(tee -a "$LOGFILE") 2>&1

# STEP 1 - Get user input
echo "Please enter the RadKit PROD value in format: PROD:xxxx-xxxx-xxxx"
read -p "RadKit PROD Value: " PROD_VALUE

# Check if input is empty
if [[ -z "$PROD_VALUE" ]]; then
    echo "Error: No PROD value provided. Exiting."
    exit 1
fi

# STEP 2 - Bring up network interfaces
echo "Bringing up interfaces ens3 to ens9..."
for i in {3..9}
do
    sudo ip link set ens$i up
done
echo "Interfaces brought up successfully."
sleep 1

# STEP 3 - Copy radkit-devices.json into container
echo "Copying radkit-devices.json into radkit container..."
docker cp radkit-devices.json radkit:/
sleep 1

# STEP 4 - Define function to run docker exec with expect
run_in_container_with_password() {
    local CMD="$1"
    expect <<EOD
spawn docker exec -it radkit bash -c "$CMD"
expect "superadmin's password:"
send "Cisco123!\r"
expect eof
EOD
}

# STEP 5 - Execute commands one-by-one
echo "Setting proxy (no password needed)..."
docker exec radkit bash -c "export -n RADKIT_CLOUD_CLIENT_PROXY_URL"

echo "Enrolling system with provided PROD value..."
run_in_container_with_password "radkit-control system enroll $PROD_VALUE"

echo "Creating user bdarlida@cisco.com..."
run_in_container_with_password "radkit-control user create bdarlida@cisco.com --full-name bruno --active forever"

echo "Creating radkit-service device..."
run_in_container_with_password "radkit-control device create radkit-service localhost RADKIT_SERVICE --forwarded-tcp-ports 8081"

# STEP 6 - Create ubuntu0 jump host and capture UUID
echo "Creating ubuntu0 jump host and capturing UUID..."
UBUNTU0_OUTPUT=$(expect <<EOD
spawn docker exec -it radkit bash -c "radkit-control device create ubuntu0 172.17.0.1 Linux --description ubuntu0 --terminal-connection-method SSH --terminal-username ubuntu --terminal-password cisco --forwarded-tcp-ports 22 --active true"
expect "superadmin's password:"
send "Cisco123!\r"
expect eof
EOD
)

echo "Ubuntu0 created. Output:"
echo "$UBUNTU0_OUTPUT"

# Extract UUID from output
UBUNTU0_UUID=$(echo "$UBUNTU0_OUTPUT" | grep -o '"uuid": "[^"]*' | awk -F'"' '{print $4}')

if [[ -z "$UBUNTU0_UUID" ]]; then
    echo "Failed to capture ubuntu0 UUID. Exiting."
    exit 1
fi

echo "Captured ubuntu0 UUID: $UBUNTU0_UUID"

# STEP 7 - Update radkit-devices.json inside container
echo "Replacing jumphostUuid values inside radkit-devices.json in container..."
docker exec radkit bash -c "sed -i 's/\"jumphostUuid\": \"[^\"]*\"/\"jumphostUuid\": \"$UBUNTU0_UUID\"/g' /radkit-devices.json"

echo "Updated radkit-devices.json successfully."

# STEP 8 - Import the radkit-devices.json inside the container
echo "Running the bulk import for the radkit-devices"

run_in_container_with_password "radkit-control device bulk-create --json-input radkit-devices.json"

echo "Bulk import finished"


echo "==========================================="
echo "Automation finished! Logs saved at: $LOGFILE"
echo "==========================================="
