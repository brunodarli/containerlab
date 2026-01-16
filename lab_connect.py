#!/usr/bin/env python3

import sys
import yaml
import argparse
import os
import signal

try:
    import pexpect
except ImportError:
    print("Error: 'pexpect' module is not installed. Please install it using: pip install pexpect")
    sys.exit(1)

# Credentials Map
CREDENTIALS = {
    'default': ('clab', 'clab@123'),
    'cisco_iol': ('admin', 'admin'),
}

CONFIG_DIR = "/etc/lab_sim"
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
EXTRA_HOSTS_FILE = os.path.join(CONFIG_DIR, "extra_hosts.json")

def parse_topology(topo_file):
    """
    Parses the .clab.yaml file and returns a dictionary of {node_name: {'ip': mgmt_ipv4, 'kind': kind}}.
    """
    nodes_map = {}
    try:
        with open(topo_file, 'r') as f:
            topo = yaml.safe_load(f)
            
        nodes = topo.get('topology', {}).get('nodes', {})
        for name, data in nodes.items():
            mgmt_ip = data.get('mgmt-ipv4')
            kind = data.get('kind', 'default')
            if mgmt_ip:
                nodes_map[name] = {'ip': mgmt_ip, 'kind': kind}
                
    except Exception as e:
        print(f"Error parsing topology file: {e}")
        sys.exit(1)
    
    # Load extra hosts
    if os.path.exists(EXTRA_HOSTS_FILE):
        try:
            with open(EXTRA_HOSTS_FILE, 'r') as f:
                extra = json.load(f)
                for name, ip in extra.items():
                    if name not in nodes_map:
                         nodes_map[name] = {'ip': ip, 'kind': 'default'}
        except Exception as e:
            # Just ignore if we can't read it
            pass

    return nodes_map

def resize_window(child):
    """
    Update the child process window size to match the terminal.
    """
    try:
        rows, cols = os.popen('stty size', 'r').read().split()
        child.setwinsize(int(rows), int(cols))
    except (ValueError, OSError):
        pass

def connect_to_node(node_name, node_data):
    """
    Establishes an SSH connection to the node using pexpect.
    """
    ip = node_data['ip']
    kind = node_data['kind']
    
    user, password = CREDENTIALS.get(kind, CREDENTIALS['default'])
    
    print(f"\nConnecting to {node_name} ({ip}) as {user}...")
    print("Escape character is '^]'.\n")
    
    # -o HostKeyAlgorithms=+ssh-rsa: Allow connecting to legacy devices using RSA
    # -o PubkeyAcceptedKeyTypes=+ssh-rsa: Allow RSA for public key auth if needed
    cmd = f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa {user}@{ip}"
    
    try:
        child = pexpect.spawn(cmd, encoding='utf-8')
        
        # Pass SIGWINCH (window resize) signal to child
        def sigwinch_handler(sig, data):
            resize_window(child)
        
        # Register signal handler if supported (Unix)
        if hasattr(signal, "SIGWINCH"):
            signal.signal(signal.SIGWINCH, sigwinch_handler)
            resize_window(child) # Set initial size

        # Expect loop to handle various login states
        index = child.expect([
            '[Pp]assword:',
            'Are you sure you want to continue connecting',
            pexpect.EOF,
            pexpect.TIMEOUT
        ], timeout=30)

        if index == 0:
            # Password prompt
            child.sendline(password)
        elif index == 1:
            # Fingerprint confirmation
            child.sendline('yes')
            child.expect('[Pp]assword:', timeout=30)
            child.sendline(password)
        elif index == 2:
            print("Connection closed unexpectedly.")
            print(f"Output before verify: {child.before}")
            return
        elif index == 3:
            print("Connection timed out.")
            print(f"Output before timeout: {child.before}")
            return

        # Hand over control to the user
        child.interact()
        
    except pexpect.ExceptionPexpect as e:
        print(f"An error occurred: {e}")
    except KeyboardInterrupt:
        print("\nSession interrupted.")

import json


def get_active_topology():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            return data.get("active_topology")
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="Automate SSH connection to Containerlab nodes.")
    parser.add_argument("topology_file", nargs="?", help="Path to the .clab.yaml topology file. If failed, attempts to use active topology from lab_sim.")
    parser.add_argument("node", nargs="?", help="Name of the node to connect to (optional)")
    
    args = parser.parse_args()
    
    topo_file = args.topology_file
    
    # If no topology file specified (or if it looks like a node name), try to load active one
    # Heuristic: if 1st arg doesn't end in .yaml/.yml and config exists, maybe 1st arg is node?
    # But argparse handles positionals. If nargs='?', topology_file gets the first string.
    # If user runs 'lab_connect node1', topology_file becomes 'node1'.
    # We need to handle this.
    
    active_topo = get_active_topology()
    target_node = args.node

    # Logic to disambiguate:
    # 1. If args.topology_file is a file that exists, use it.
    # 2. If args.topology_file is NOT a file, but looks like a node name, and we have active_topo:
    #    assume args.topology_file is actually the node name, and use active_topo.
    # 3. If args.topology_file is None, use active_topo.
    
    if topo_file and os.path.isfile(topo_file):
        # Case 1: Explicit topology file provided
        pass
    elif topo_file and active_topo and not os.path.exists(topo_file):
        # Case 2: Argument provided but it's not a file. Likely a node name.
        # Shift args: topology_file -> node
        target_node = topo_file
        topo_file = active_topo
    elif not topo_file and active_topo:
        # Case 3: No args, use active
        topo_file = active_topo
    
    if not topo_file or not os.path.exists(topo_file):
        print("Error: Topology file not found or not specified.")
        print(f"Checked: {topo_file}")
        print("Usage: lab_connect [topology_file] [node]")
        sys.exit(1)
        
    nodes = parse_topology(topo_file)
    
    if not nodes:
        print("No nodes with 'mgmt-ipv4' found in the topology.")
        sys.exit(1)
        
    # target_node = args.node # REMOVED redundant assignment
    
    if not target_node:
        # Interactive selection
        print(f"\nAvailable nodes in {args.topology_file}:")
        node_list = sorted(nodes.keys())
        for idx, name in enumerate(node_list):
            data = nodes[name]
            print(f"{idx + 1}. {name} ({data['ip']}) [{data['kind']}]")
            
        while True:
            try:
                choice = input("\nSelect a node number: ")
                if not choice: continue
                idx = int(choice) - 1
                if 0 <= idx < len(node_list):
                    target_node = node_list[idx]
                    break
                else:
                    print("Invalid selection.")
            except ValueError:
                print("Please enter a number.")
            except KeyboardInterrupt:
                print("\nCancelled.")
                sys.exit(0)
    
    if target_node not in nodes:
        print(f"Node '{target_node}' not found in topology.")
        sys.exit(1)
        
    connect_to_node(target_node, nodes[target_node])

if __name__ == "__main__":
    main()
