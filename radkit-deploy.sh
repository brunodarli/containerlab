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

# STEP 4 - Enter radkit container and run commands
echo "Entering radkit container..."

docker exec -i radkit bash << 'EOF'
echo "Setting proxy..."
export -n RADKIT_CLOUD_CLIENT_PROXY_URL

# Define the common password
PASSWORD="Cisco123!"

# Function to automate commands requiring password
run_with_password() {
    CMD="\$1"
    expect <<EOD
spawn bash -c "\$CMD"
expect "superadmin's password:"
send "\$PASSWORD\r"
expect eof
EOD
}

# 1. Enroll system
echo "Enrolling system with provided PROD value..."
run_with_password "radkit-control system enroll '"$PROD_VALUE"'"

# 2. Create user
echo "Creating user bdarlida@cisco.com..."
run_with_password "radkit-control user create bdarlida@cisco.com --full-name bruno --active forever"

# 3. Create radkit-service device
echo "Creating radkit-service device..."
run_with_password "radkit-control device create radkit-service localhost RADKIT_SERVICE --forwarded-tcp-ports 8081"

# 4. Create ubuntu0 jump host
echo "Creating ubuntu0 jump host..."
UBUNTU0_OUTPUT=\$(expect <<EOD
spawn bash -c "radkit-control device create ubuntu0 172.17.0.1 Linux --description ubuntu0 --terminal-connection-method SSH --terminal-username ubuntu --terminal-password cisco --forwarded-tcp-ports 22 --active true"
expect "superadmin's password:"
send "\$PASSWORD\r"
expect eof
EOD
)

echo "Ubuntu0 created. Output:"
echo "\$UBUNTU0_OUTPUT"

# Extract UUID from output
UBUNTU0_UUID=\$(echo "\$UBUNTU0_OUTPUT" | grep -o '"uuid": "[^"]*' | awk -F'"' '{print \$4}')

if [[ -z "\$UBUNTU0_UUID" ]]; then
    echo "Failed to capture ubuntu0 UUID. Exiting."
    exit 1
fi

echo "Captured ubuntu0 UUID: \$UBUNTU0_UUID"

# Update radkit-devices.json
echo "Replacing jumphostUuid values in radkit-devices.json..."
sed -i "s/\"jumphostUuid\": \"[^\"]*\"/\"jumphostUuid\": \"\$UBUNTU0_UUID\"/g" /radkit-devices.json

echo "Updated radkit-devices.json successfully."
EOF

echo "All steps completed!"

echo "==========================================="
echo "Automation finished! Logs saved at: $LOGFILE"
echo "==========================================="
