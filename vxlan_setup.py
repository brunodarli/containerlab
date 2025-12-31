#!/usr/bin/env python3

import sys
import yaml
import subprocess
import time
import re
import os

# Mapping of hostnames to their remote physical IPs
HOST_MAP = {
    'ubuntu-0': '10.253.11.10',
    'ubuntu-1': '10.253.11.11',
    'ubuntu-2': '10.253.11.12',
    'ubuntu-3': '10.253.11.13',
}

def setup_vxlan(topology_file):
    print(f"Processing topology file: {topology_file}")
    

    try:
        with open(topology_file, 'r') as f:
            topo = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading topology file: {e}")
        sys.exit(1)

    links = topo.get('topology', {}).get('links', [])
    brought_up = []

    print("Checking for host links and configuring VXLAN...")

    for link in links:
        endpoints = link.get('endpoints', [])
        host_ep = None
        
        # Find the endpoint that starts with 'host:'
        for ep in endpoints:
            if ep.startswith('host:'):
                host_ep = ep
                break
        
        if not host_ep:
            continue

        # Extract interface name (part after 'host:')
        # Example: host:ubuntu-1_id18 -> ubuntu-1_id18
        if_name = host_ep.split(':', 1)[1]

        # Parse the interface name to find hostname and id
        # Expected pattern: <hostname>_id<vni>
        # We search specifically for our known hostnames at the start of the string
        
        target_host = None
        target_vni = None

        match = re.match(r'^([a-z0-9-]+)_id(\d+)$', if_name)
        if match:
             # Check if the captured hostname is in our map
             h_name = match.group(1)
             if h_name in HOST_MAP:
                 target_host = h_name
                 target_vni = match.group(2)
        
        if not target_host:
            # Fallback or logging if needed, but for now strict matching based on request
            # "ubuntu-0 is ..., ubuntu-1 is ..."
            # If name doesn't match standard pattern, we ignore or log?
            # Creating a VXLAN for every host link might be wrong if it's just a local mgmt link.
            # But "host:..." implies intention.
            # Let's verify against the HOST_MAP to be safe.
            continue

        remote_ip = HOST_MAP[target_host]

        # Construct the containerlab command
        # sudo containerlab tools vxlan create --remote <IP> --id <ID> --link <LINK_NAME>
        cmd = [
            "sudo", "containerlab", "tools", "vxlan", "create",
            "--remote", remote_ip,
            "--id", target_vni,
            "--link", if_name
        ]

        print(f"  Configuring {if_name} -> Remote: {target_host} ({remote_ip}), VNI: {target_vni}")
        
        try:
            # run command
            subprocess.run(cmd, check=True)
            brought_up.append(f"{if_name} (Remote: {remote_ip}, VNI: {target_vni})")
        except subprocess.CalledProcessError as e:
            print(f"  Error configuring {if_name}: {e}")
        except FileNotFoundError:
             print("  Error: 'containerlab' command not found. Ensure it is installed and in your PATH.")
             sys.exit(1)

    print("\n" + "="*40)
    print("VXLAN Setup Complete")
    print("Interfaces brought up:")
    if brought_up:
        for item in brought_up:
            print(f"- {item}")
    else:
        print("None")
    print("="*40 + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 vxlan_setup.py <path_to_topology_file.clab.yaml>")
        sys.exit(1)
    
    topo_file = sys.argv[1]
    if not os.path.exists(topo_file):
        print(f"File not found: {topo_file}")
        sys.exit(1)
        
    setup_vxlan(topo_file)
