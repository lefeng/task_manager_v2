#!/usr/bin/env bash
# Regenerate gRPC Python files from the proto definition.
# Run from the project root: bash scripts/gen_grpc.sh

set -euo pipefail

PROTO_DIR="$(dirname "$0")/../proto"
OUT_DIR="$(dirname "$0")/../grpc_gen"

python -m grpc_tools.protoc \
    -I "$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "$PROTO_DIR/job_runner.proto"

# Fix relative imports in the generated grpc file (grpc_tools quirk)
sed -i 's/^import job_runner_pb2/from grpc_gen import job_runner_pb2/' \
    "$OUT_DIR/job_runner_pb2_grpc.py"

echo "Done. Generated files in $OUT_DIR"
