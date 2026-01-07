#!/usr/bin/env python3

import os
import sys
import argparse
import json
import shutil
import subprocess

# Configuration
APP_DIR = os.path.dirname(os.path.abspath(__file__))
HOME_DIR = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME_DIR, ".lab_sim")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Tools to process
TOOLS = {
    "lab_sim": "lab_sim.py",
    "lab_connect": "lab_connect.py",
    "vxlan_setup": "vxlan_setup.py"
}

# Target directory for symlinks (User's bin or system bin)
# We'll try to use /usr/local/bin so it's system-wide, as requested ("native program")
# This requires sudo.
INSTALL_DIR = "/usr/local/bin"

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

def load_config():
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config(config):
    ensure_config_dir()
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def install_tools():
    print(f"Installing tools to {INSTALL_DIR}...")
    
    # Check if we have write access, otherwise warn user they might need sudo
    if not os.access(INSTALL_DIR, os.W_OK):
        print(f"Warning: {INSTALL_DIR} is not writable. You may need to run this with sudo for installation.")
        # But we continue to try, it might fail. Only fail if specific link fails.

    for link_name, script_name in TOOLS.items():
        script_path = os.path.join(APP_DIR, script_name)
        link_path = os.path.join(INSTALL_DIR, link_name)
        
        # Make executable
        os.chmod(script_path, 0o755)
        
        if os.path.exists(link_path):
            try:
                os.remove(link_path)
            except OSError as e:
                print(f"Error removing existing link {link_path}: {e}")
                continue
                
        try:
            os.symlink(script_path, link_path)
            print(f"  Linked {link_name} -> {script_path}")
        except OSError as e:
            print(f"  Error creating symlink for {link_name}: {e}")
            print("  Try running with 'sudo'.")

    # Install bash completion
    completion_src = os.path.join(APP_DIR, "lab_completion.bash")
    # Typical bash completion dir
    completion_dirs = [
        "/etc/bash_completion.d",
        "/usr/local/etc/bash_completion.d",
        "/usr/share/bash-completion/completions"
    ]
    
    completion_dst_dir = None
    for d in completion_dirs:
        if os.path.exists(d) and os.access(d, os.W_OK):
            completion_dst_dir = d
            break
            
    if completion_dst_dir:
        dst = os.path.join(completion_dst_dir, "lab_connect")
        try:
            shutil.copy(completion_src, dst)
            print(f"  Installed completion script to {dst}")
        except Exception as e:
            print(f"  Error installing completion: {e}")
    else:
        print("  Could not find a writable bash_completion.d directory. Completion script not installed automatically.")
        print(f"  You can manually source {completion_src} in your .bashrc")

    print("Installation complete.")

def run_command(cmd, check=True):
    print(f"Executing: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return False
    return True

def deploy_lab(topo_file):
    print(f"State: Setting active topology to {topo_file}")
    config = load_config()
    config["active_topology"] = os.path.abspath(topo_file)
    save_config(config)

    # 1. Install checks (symlinks)
    # We do a quick check if they exist, if not we try to install?
    # Or purely rely on user having run it once. 
    # User said: "It should act as the installation of all this pieces."
    # So we should probably try to install/update links on every run or check.
    # But running install might require sudo, while deploying usually also requires sudo
    # but maybe user runs 'lab_sim' which calls 'sudo containerlab'.
    # Let's assume user runs `lab_sim` possibly without sudo, but `lab_sim` will call sudo.
    # Installation requires writing to /usr/local/bin, which needs sudo.
    # So for now, let's JUST install if we detect we are running as root (sudo lab_sim -i ...)
    # OR if we explicitly ask.
    # Use logic: Attempt install.
    install_tools()

    # 2. Deploy Containerlab
    print("\n[Step 1] Deploying Containerlab topology...")
    if not run_command(["sudo", "containerlab", "deploy", "-t", topo_file, "--reconfigure"]):
        print("Deploy failed.")
        sys.exit(1)

    # 3. VXLAN Setup
    print("\n[Step 2] Setting up VXLANs...")
    # Using absolute path to ensure we run the right script even if symlink failed
    vxlan_script = os.path.join(APP_DIR, "vxlan_setup.py")
    if not run_command(["python3", vxlan_script, topo_file]):
        print("VXLAN setup failed.")
        # We don't exit here, might be partial success

    print("\nLab Simulation Started Successfully.")
    print(f"Active Topology: {topo_file}")

def destroy_lab(topo_file):
    # If topo_file not provided, use active?
    # User said "-d <lab file>" explicitly. We stick to that.
    
    print(f"\n[Step 1] Cleaning up VXLANs...")
    vxlan_script = os.path.join(APP_DIR, "vxlan_setup.py")
    # Using -c flag
    run_command(["python3", vxlan_script, topo_file, "-c"], check=False)

    print("\n[Step 2] Destroying Containerlab topology...")
    run_command(["sudo", "containerlab", "destroy", "-t", topo_file, "-c"], check=False)
    
    # We can optionally clear active topology if it matches
    config = load_config()
    if config.get("active_topology") == os.path.abspath(topo_file):
        config["active_topology"] = None
        save_config(config)

    print("\nLab Simulation Stopped.")

def main():
    parser = argparse.ArgumentParser(description="Lab Simulation Orchestrator")
    parser.add_argument("-i", "--install", metavar="TOPO_FILE", help="Install tools and Start the lab simulation")
    parser.add_argument("-d", "--destroy", metavar="TOPO_FILE", help="Stop the simulation and destroy the lab")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    if args.install:
        if not os.path.exists(args.install):
            print(f"Error: Topology file {args.install} not found.")
            sys.exit(1)
        deploy_lab(args.install)
    
    elif args.destroy:
        if not os.path.exists(args.destroy):
            print(f"Error: Topology file {args.destroy} not found.")
            sys.exit(1)
        destroy_lab(args.destroy)

if __name__ == "__main__":
    main()
