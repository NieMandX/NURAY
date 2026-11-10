#!/bin/sh
# Local geometry dependencies remain outside Git; no global interpreter changes.
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$PROJECT_ROOT/.local/build-deps:/Users/niemandx/Documents/ChatGPT/IDEAS/moscow-fidelity/.build-deps:/Users/niemandx/AI_Modeling/moscow_10x10/python_libs:$PROJECT_ROOT/moscow-fidelity/prototype/tiling:$PROJECT_ROOT/moscow-fidelity/prototype${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPYCACHEPREFIX=/tmp/nuray-pycache
export NURAY_COMPRESS_CANONICAL=1
export NURAY_COMPRESS_CHECKPOINTS=1
export NURAY_ARCHIVE_INTERMEDIATE_GLB=1
export NURAY_DEFER_CANONICAL_GLB=1
# Tile packing retains per-tile lineage and vertex maps for a whole source
# layer. Give this offline build headroom beyond Node's small default heap.
export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--max-old-space-size=${NURAY_NODE_HEAP_MB:-24576}"
export NODE=/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node
export PYTHON=/Users/niemandx/AI_Modeling/moscow_10x10/blender_mcp_env/bin/python3
exec "$PYTHON" "$@"
