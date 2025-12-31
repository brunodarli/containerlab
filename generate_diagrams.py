import yaml
import glob
import os
import argparse
import json
import base64

def get_image_data_uri(filepath):
    try:
        with open(filepath, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            # Assuming png for now based on user flow, but could be generic
            return f"data:image/png;base64,{encoded_string}"
    except Exception as e:
        print(f"Could not load local icon {filepath}: {e}")
        return None

def parse_topology_for_visjs(filepath):
    try:
        with open(filepath, 'r') as f:
            data = yaml.safe_load(f)
        
        if not data or 'topology' not in data:
            return None, None
        
        topology = data['topology']
        topo_nodes = topology.get('nodes', {})
        topo_links = topology.get('links', [])
        
        if not topo_nodes and not topo_links:
            return None, None
            
        vis_nodes = []
        vis_edges = []
        
        # Pre-load local icons if available
        crs_icon_path = "crs_icon.png"
        crs_icon_data = get_image_data_uri(crs_icon_path)
        
        router_icon_path = "router_icon.png"
        router_icon_data = get_image_data_uri(router_icon_path)
        
        # Process Nodes
        for node_name, node_attrs in topo_nodes.items():
            # Basic node structure
            kind = node_attrs.get('kind', 'unknown')
            mgmt_ip = node_attrs.get('mgmt-ipv4', '')
            
            title_html = f"<b>{node_name}</b><br>Kind: {kind}<br>Mgmt: {mgmt_ip}"
            
            # Icon logic
            # Default to standard router
            icon_url = "https://raw.githubusercontent.com/ecceman/affinity-cisco-icons/master/Core%20Router.png" 
            
            if 'xrd' in kind.lower() or 'xrv' in kind.lower() or 'crs' in kind.lower():
                # Use local icon if available, else fallback
                if crs_icon_data:
                    icon_url = crs_icon_data
                else:
                    icon_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/6/60/Cisco_Carrier_Routing_System.svg/1200px-Cisco_Carrier_Routing_System.svg.png" 
            
            if 'iol' in kind.lower():
                 # Regular router local icon
                 if router_icon_data:
                     icon_url = router_icon_data
                 else:
                     icon_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c8/Cisco_Router.svg/1024px-Cisco_Router.svg.png"

            vis_nodes.append({
                'id': node_name,
                'label': node_name,
                'title': title_html, # Tooltip
                'shape': 'image', 
                'image': icon_url,
                'size': 30
            })
            
        # Process Links
        for link in topo_links:
            endpoints = link.get('endpoints')
            if endpoints and len(endpoints) == 2:
                src_full = endpoints[0]
                dst_full = endpoints[1]
                
                # split node:interface
                src_parts = src_full.split(':')
                dst_parts = dst_full.split(':')
                
                src_node = src_parts[0]
                dst_node = dst_parts[0]
                
                src_intf = src_parts[1] if len(src_parts) > 1 else ""
                dst_intf = dst_parts[1] if len(dst_parts) > 1 else ""
                
                # Label: "NodeA: Gi0-0-0-0 -- NodeB: Gi0-0-0-1"
                # Including node names clarifies ownership of the interface
                label = ""
                if src_intf or dst_intf:
                    label = f"{src_node}:{src_intf}\n--\n{dst_node}:{dst_intf}"
                
                vis_edges.append({
                    'from': src_node,
                    'to': dst_node,
                    'label': label,
                    'font': {'align': 'middle', 'size': 10},
                    'arrows': 'to;from', # Bidirectional visual
                    'color': {'color': '#848484'}
                })

        return vis_nodes, vis_edges
        
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
        return None, None

def generate_html_visjs(nodes, edges, title):
    # Serialize to JSON
    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    
    # Define JS component outside f-string to avoid syntax conflicts
    physics_options = "{ physics: false }"
    
    html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style type="text/css">
        body, html {{
            height: 100%;
            width: 100%;
            margin: 0;
            padding: 0;
            overflow: hidden; /* Hide scrollbars */
            font-family: sans-serif;
        }}
        #mynetwork {{
            width: 100%;
            height: 100%;
            background-color: #f4f4f4;
        }}
        .controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 100;
            background: rgba(255, 255, 255, 0.8);
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        }}
    </style>
</head>
<body>
    <div class="controls">
        <h3>{title}</h3>
        <p>Drag nodes to rearrange. Scroll to zoom.</p>
        <div style="margin-top: 5px;">
            <button onclick="resetLayout()">Reset Layout</button>
            <button onclick="exportCoordinates()">Export Coords</button>
        </div>
    </div>
    <div id="mynetwork"></div>

    <script type="text/javascript">
        // Topology ID for LocalStorage key (using filename/title to be unique per file)
        var topologyId = "visjs_layout_" + "{title}";

        // load saved positions if available
        var savedPositions = JSON.parse(localStorage.getItem(topologyId));
        
        // create an array with nodes
        var nodesArray = {nodes_json};
        
        // Apply saved positions to nodes if they exist
        if (savedPositions) {{
            nodesArray.forEach(function(node) {{
                if (savedPositions[node.id]) {{
                    node.x = savedPositions[node.id].x;
                    node.y = savedPositions[node.id].y;
                    // If we have saved positions, we might want to disable physics initially or let it stabilize from there
                    // But keeping physics enabled allows it to settle into the saved structure
                }}
            }});
        }}

        var nodes = new vis.DataSet(nodesArray);

        // create an array with edges
        var edges = new vis.DataSet({edges_json});

        // create a network
        var container = document.getElementById('mynetwork');
        var data = {{
            nodes: nodes,
            edges: edges
        }};
        var options = {{
            physics: {{
                enabled: true,
                barnesHut: {{
                    gravitationalConstant: -2000,
                    centralGravity: 0.3,
                    springLength: 95,
                    springConstant: 0.04,
                    damping: 0.09,
                    avoidOverlap: 0.1
                }},
                stabilization: {{ iterations: 150 }}
            }},
            nodes: {{
                font: {{
                    size: 16,
                    face: 'arial'
                }},
                borderWidth: 2,
                shadow: true
            }},
            edges: {{
                width: 2,
                shadow: true,
                smooth: {{
                    type: 'continuous'
                }}
            }},
            interaction: {{
                hover: true,
                navigationButtons: true,
                keyboard: true
            }}
        }};
        var network = new vis.Network(container, data, options);
        
        // Stop physics after stabilization to prevent "magnetic" pulling when dragging
        network.on("stabilizationIterationsDone", function () {{
            network.setOptions( {physics_options} );
        }});

        // Save positions to LocalStorage whenever a node is dragged
        network.on("dragEnd", function (params) {{
            if (params.nodes.length > 0) {{
                var positions = network.getPositions();
                // Merge with existing saved positions to keep track of all nodes
                var existing = JSON.parse(localStorage.getItem(topologyId)) || {{}};
                for (var nodeId in positions) {{
                    existing[nodeId] = positions[nodeId];
                }}
                localStorage.setItem(topologyId, JSON.stringify(existing));
            }}
        }});

        function resetLayout() {{
            if (confirm("Are you sure you want to reset the layout? This will clear saved positions.")) {{
                localStorage.removeItem(topologyId);
                location.reload();
            }}
        }}

        function exportCoordinates() {{
            var positions = network.getPositions();
            var jsonContent = JSON.stringify(positions, null, 2);
            var blob = new Blob([jsonContent], {{type: "application/json"}});
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = "{title}_layout.json";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }}
    </script>
</body>
</html>
"""
    return html_template

def main():
    parser = argparse.ArgumentParser(description='Generate Vis.js interactive diagrams for containerlab topologies.')
    parser.add_argument('file', nargs='?', help='Specific .clab.yaml file to process')
    parser.add_argument('--output', '-o', help='Output HTML file path')
    args = parser.parse_args()

    files = []
    if args.file:
        files = [args.file]
    else:
        # If no file specified, warn user or pick first one for simplicity in this script version
        print("Please specify a .clab.yaml file to generate an HTML visualization.")
        return

    filepath = files[0]
    filename = os.path.basename(filepath)
    
    nodes, edges = parse_topology_for_visjs(filepath)
    
    if nodes and edges:
        # Determine output filename
        if args.output:
            out_path = args.output
        else:
            # default to something based on input if no output arg
            base, _ = os.path.splitext(filename) # remove .yaml
            base, _ = os.path.splitext(base) # remove .clab if present or just ensure
            out_path = f"{base}.html"

        html_content = generate_html_visjs(nodes, edges, filename)
        with open(out_path, 'w') as f:
            f.write(html_content)
        print(f"Generated interactive HTML visualization at {out_path}")

    else:
        print("Failed to generate diagram data.")

if __name__ == "__main__":
    main()
