#!/usr/bin/env python3

import sys
import yaml
import subprocess
import time
import re
import os

import argparse

# Mapping of hostnames to their remote physical IPs
HOST_MAP = {
    'ubuntu-0': '10.253.11.10',
    'ubuntu-1': '10.253.11.11',
    'ubuntu-2': '10.253.11.12',
    'ubuntu-3': '10.253.11.13',
}

def process_vxlan(topology_file, cleanup=False):
    print(f"Processing topology file: {topology_file}")
    action = "Cleaning up" if cleanup else "Configuring"
    print(f"{action} VXLAN interfaces...")

    try:
        with open(topology_file, 'r') as f:
            topo = yaml.safe_load(f)
    except Exception as e:
        print(f"Error reading topology file: {e}")
        sys.exit(1)

    links = topo.get('topology', {}).get('links', [])
    processed_links = []

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
        if_name = host_ep.split(':', 1)[1]

        # Parse the interface name to find hostname and id
        target_host = None
        target_vni = None

        match = re.match(r'^([a-z0-9-]+)_id(\d+)$', if_name)
        if match:
             h_name = match.group(1)
             if h_name in HOST_MAP:
                 target_host = h_name
                 target_vni = match.group(2)
        
        if not target_host:
            continue

        remote_ip = HOST_MAP[target_host]

        if cleanup:
            # Cleanup: sudo ip link delete <link-name>
            cmd = ["sudo", "ip", "link", "delete", if_name]
            msg = f"  Deleting {if_name}..."
        else:
            # Setup: sudo containerlab tools vxlan create ...
            cmd = [
                "sudo", "containerlab", "tools", "vxlan", "create",
                "--remote", remote_ip,
                "--id", target_vni,
                "--link", if_name
            ]
            msg = f"  Configuring {if_name} -> Remote: {target_host} ({remote_ip}), VNI: {target_vni}"

        print(msg)
        
        try:
            subprocess.run(cmd, check=True)
            processed_links.append(if_name)
        except subprocess.CalledProcessError as e:
            # In cleanup, it's possible the link doesn't exist, which is fine but we report it.
            print(f"  Error processing {if_name}: {e}")
        except FileNotFoundError:
             print(f"  Error: Command not found for {' '.join(cmd)}")
             sys.exit(1)

    print("\n" + "="*40)
    print(f"VXLAN {action} Complete")
    print("Interfaces processed:")
    if processed_links:
        for item in processed_links:
            print(f"- {item}")
    else:
        print("None")
    print("="*40 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup or cleanup VXLAN interfaces based on a topology file.")
    parser.add_argument("topology_file", help="Path to the topology file (.clab.yaml)")
    parser.add_argument("-c", "--cleanup", action="store_true", help="Remove the interfaces created by this script")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.topology_file):
        print(f"File not found: {args.topology_file}")
        sys.exit(1)
        
    process_vxlan(args.topology_file, cleanup=args.cleanup)
