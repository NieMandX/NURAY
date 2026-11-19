#!/bin/sh
# Local geometry dependencies remain outside Git; no global interpreter changes.
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LEGACY_BUILD_ROOT="$HOME/AI_Modeling/moscow_10x10"
BUILD_LIBS=${NURAY_PYTHON_LIBS:-}
if [ -n "${NURAY_PYTHON:-}" ]; then
    PYTHON=$NURAY_PYTHON
elif [ -x "$PROJECT_ROOT/.local/venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.local/venv/bin/python"
elif [ -x "$LEGACY_BUILD_ROOT/blender_mcp_env/bin/python3" ]; then
    PYTHON="$LEGACY_BUILD_ROOT/blender_mcp_env/bin/python3"
    BUILD_LIBS="$PROJECT_ROOT/.local/build-deps:$PROJECT_ROOT/.local/legacy-build-deps:$LEGACY_BUILD_ROOT/python_libs${BUILD_LIBS:+:$BUILD_LIBS}"
else
    PYTHON=python3
fi
export PYTHONPATH="$PROJECT_ROOT/moscow-fidelity/prototype/tiling:$PROJECT_ROOT/moscow-fidelity/prototype${BUILD_LIBS:+:$BUILD_LIBS}${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPYCACHEPREFIX="$PROJECT_ROOT/.local/pycache"
export NURAY_COMPRESS_CANONICAL=1
export NURAY_COMPRESS_CHECKPOINTS=1
export NURAY_ARCHIVE_INTERMEDIATE_GLB=1
export NURAY_DEFER_CANONICAL_GLB=1
# Tile packing retains per-tile lineage and vertex maps for a whole source
# layer. Give this offline build headroom beyond Node's small default heap.
export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--max-old-space-size=${NURAY_NODE_HEAP_MB:-24576}"
NODE=${NURAY_NODE:-$(command -v node || true)}
if [ -z "$NODE" ] && [ -x /Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node ]; then
    NODE=/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node
fi
export NODE="${NODE:-node}" PYTHON
exec "$PYTHON" "$@"
