#!/bin/bash

# Bash completion for lab_connect
# Reads the active topology from ~/.lab_sim/config.json and suggests node names.

_lab_connect_completions()
{
    local cur prev
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}

    # Config location
    local config_file="/etc/lab_sim/config.json"
    
    # Check if config exists
    if [[ ! -f "$config_file" ]]; then
        return 0
    fi

    # Extract active topology path using grep/sed (avoiding python/jq dependency for speed if possible, but python is safer)
    # Using python for reliability as it's already a python ecosystem
    local topo_file
    topo_file=$(python3 -c "import json,os; print(json.load(open(os.path.expanduser('$config_file'))).get('active_topology', ''))" 2>/dev/null)

    if [[ -z "$topo_file" || ! -f "$topo_file" ]]; then
        return 0
    fi

    # Parse node names from topology file
    # We look for keys under 'nodes:'
    # A simple grep might be insufficient if indented strangely, but let's try a robust python one-liner or grep
    # Using python again for consistency with lab_connect logic
    local nodes
    nodes=$(python3 -c "
import yaml, sys
try:
    data = yaml.safe_load(open('$topo_file'))
    nodes = data.get('topology', {}).get('nodes', {}).keys()
    print(' '.join(nodes))
except: pass
" 2>/dev/null)

    COMPREPLY=($(compgen -W "$nodes" -- "$cur"))
    return 0
}

_lab_sim_completions()
{
    local cur prev
    cur=${COMP_WORDS[COMP_CWORD]}
    prev=${COMP_WORDS[COMP_CWORD-1]}

    # Complete flags
    if [[ ${cur} == -* ]] ; then
        COMPREPLY=( $(compgen -W "-i -d" -- ${cur}) )
        return 0
    fi

    # Complete .yaml files and directories using plusdirs to enable traversal
    # -o plusdirs: Adds directory names to the output
    # -f: Generate filenames
    # -X: Exclude files not matching pattern
    
    local IFS=$'\n'
    COMPREPLY=( $(compgen -o plusdirs -f -X "!*.yaml" -- "${cur}") )
    return 0
}

complete -F _lab_connect_completions lab_connect
complete -F _lab_connect_completions lc
complete -F _lab_sim_completions lab_sim
