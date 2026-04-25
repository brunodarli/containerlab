#!/usr/bin/env python3

import argparse
import subprocess
import os
import time
import json
import sys
import re
import base64
from datetime import datetime

# Setup logging
log_file = f"radkit-automation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

def log(msg):
    print(msg)
    with open(log_file, "a") as f:
        f.write(msg + "\n")

def run_command(cmd, shell=True, check=False):
    log(f"Running: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    result = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.stdout:
        with open(log_file, "a") as f:
            f.write(result.stdout)
            if not result.stdout.endswith('\n'):
                f.write("\n")
    if check and result.returncode != 0:
        log(f"Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    return result.stdout

def run_with_password(cmd):
    log(f"Running (expect): {cmd}")
    expect_script = f"""
spawn docker exec -it radkit bash -c "{cmd}"
expect "superadmin's password:"
send "Cisco123!\\r"
expect eof
"""
    try:
        result = subprocess.run(['expect', '-c', expect_script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError:
        error_msg = "[ERROR] The 'expect' utility is not installed. Please install it using 'sudo apt-get install expect -y' inside your VM and try again."
        log(error_msg)
        sys.exit(1)
        
    with open(log_file, "a") as f:
        f.write(result.stdout)
        if not result.stdout.endswith('\n'):
            f.write("\n")
    return result.stdout

def main():
    parser = argparse.ArgumentParser(description="Deploy RadKit")
    parser.add_argument("-r", "--respin", action="store_true", help="Respin RadKit container")
    args = parser.parse_args()

    log(f"Logging to {log_file}")

    if args.respin:
        log("Respinning RadKit container...")
        log("Stopping existing 'radkit' container...")
        run_command("docker stop radkit", check=False)
        run_command("docker rm -v radkit", check=False)
        
        log("Removing existing 'radkit' volume data...")
        run_command("sudo rm -rf /home/ubuntu/radkit", check=False)
        run_command("mkdir -p /home/ubuntu/radkit", check=False)
        run_command("sudo chown ubuntu:ubuntu /home/ubuntu/radkit", check=False)
        
        log("Starting new 'radkit' container...")
        base64_pw = base64.b64encode(b"Cisco123!").decode("utf-8")
        
        start_cmd = (
            "docker run -d --restart always "
            "-p 8081:8081 "
            "-v /home/ubuntu/radkit:/radkit "
            f"-e RADKIT_SERVICE_SUPERADMIN_PASSWORD_BASE64={base64_pw} "
            "-e RADKIT_CLOUD_CLIENT_PROXY_URL=http://proxy.esl.cisco.com:80 "
            "-e RADKIT_SERVICE_CLI_RUN_FORCE=1 "
            "--name radkit "
            "containers.cisco.com/radkit/radkit-service:1.6.12"
        )
        run_command(start_cmd)
        
        log("Waiting 10 seconds for container to initialize...")
        time.sleep(10)

    # STEP 1: Get user inputs
    print("Please enter the RadKit PROD value in format: PROD:xxxx-xxxx-xxxx")
    prod_value = input("RadKit PROD Value: ").strip()
    
    if not prod_value:
        print("Error: No PROD value provided. Exiting.")
        sys.exit(1)
        
    print("Please enter your Cisco email (format: username@cisco.com)")
    user_email = input("Cisco Email: ").strip()
    
    if not bool(re.match(r"^[a-zA-Z0-9._%+-]+@cisco\.com$", user_email)):
        print("Error: Invalid Cisco email format. Exiting.")
        sys.exit(1)
        
    user_name = user_email.split("@")[0]
    log(f"Using username: {user_name}")
    
    # STEP 2: Bring up network interfaces
    log("Bringing up interfaces ens3 to ens9...")
    for i in range(3, 10):
        run_command(f"sudo ip link set ens{i} up")
    log("Interfaces brought up successfully.")
    time.sleep(1)

    # STEP 4: Execute commands
    log("Setting proxy (no password needed)...")
    run_command('docker exec radkit bash -c "export -n RADKIT_CLOUD_CLIENT_PROXY_URL"')

    log("Enrolling system with provided PROD value...")
    run_with_password(f"radkit-control system enroll {prod_value}")

    log(f"Creating user {user_email}...")
    run_with_password(f"radkit-control user create {user_email} --full-name {user_name} --active forever")

    log("Creating radkit-service device...")
    run_with_password("radkit-control device create radkit-service localhost RADKIT_SERVICE --forwarded-tcp-ports 8081")

    # STEP 5: Create ubuntu0 jump host and capture UUID
    log("Creating ubuntu0 jump host...")
    cmd = "radkit-control device create ubuntu0 172.17.0.1 Linux --description ubuntu0 --terminal-connection-method SSH --terminal-username ubuntu --terminal-password cisco --forwarded-tcp-ports 22 --active true"
    ubuntu0_output = run_with_password(cmd)
    
    log("Ubuntu0 created. Output:")
    log(ubuntu0_output)

    # Extract UUID
    match = re.search(r'"uuid":\s*"([^"]*)', ubuntu0_output)
    if match:
        ubuntu0_uuid = match.group(1)
    else:
        log("Failed to capture ubuntu0 UUID. Exiting.")
        sys.exit(1)

    log(f"Captured ubuntu0 UUID: {ubuntu0_uuid}")

    # STEP 5.5: Create ubuntu-clab jump host and capture UUID
    log("Creating ubuntu-clab jump host...")
    cmd = f"radkit-control device create ubuntu-clab 192.168.255.100 Linux --terminal-connection-method SSH --terminal-username ubuntu --terminal-password cisco --jumphost {ubuntu0_uuid} --active true"
    ubuntu_clab_output = run_with_password(cmd)
    
    log("ubuntu-clab created. Output:")
    log(ubuntu_clab_output)

    # Extract UUID
    match = re.search(r'"uuid":\s*"([^"]*)', ubuntu_clab_output)
    if match:
        ubuntu_clab_uuid = match.group(1)
    else:
        log("Failed to capture ubuntu-clab UUID. Exiting.")
        sys.exit(1)

    log(f"Captured ubuntu-clab UUID: {ubuntu_clab_uuid}")

    # STEP 6: Update local radkit-devices.json
    log("Updating jumphostUuid values in local radkit-devices.json...")
    script_dir = os.path.dirname(os.path.realpath(__file__))
    json_file = os.path.join(script_dir, "radkit-devices.json")

    if not os.path.isfile(json_file):
        log(f"{json_file} not found")
        sys.exit(1)

    bak_file = f"{json_file}.bak.{int(time.time())}"
    run_command(f"cp {json_file} {bak_file}")

    with open(json_file, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            log(f"Failed to parse json file {json_file}: {e}")
            sys.exit(1)

    # We iterate and recursively update although list is flat in current setup
    def update_jumphost(obj):
        if isinstance(obj, list):
            for item in obj:
                update_jumphost(item)
        elif isinstance(obj, dict):
            if obj.get("jumphostUuid") == "x":
                obj["jumphostUuid"] = ubuntu0_uuid
            elif obj.get("jumphostUuid") == "y":
                obj["jumphostUuid"] = ubuntu_clab_uuid
            for value in obj.values():
                update_jumphost(value)

    update_jumphost(data)

    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2)

    log("Updated radkit-devices.json successfully.")
    time.sleep(1)

    # STEP 7: Copy radkit-devices.json into container
    log("Copying radkit-devices.json into radkit container...")
    run_command(f"docker cp {json_file} radkit:/radkit-devices.json")
    time.sleep(1)

    # STEP 8: Bulk import radkit-devices.json
    log("Running the bulk import for the radkit-devices...")
    run_with_password("radkit-control device bulk-create --json-input /radkit-devices.json")

    log("Bulk import finished.")
    log("===========================================")
    log(f"Automation finished! Logs saved at: {log_file}")
    log("===========================================")

if __name__ == "__main__":
    main()
