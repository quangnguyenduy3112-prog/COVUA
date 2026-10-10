#!/usr/bin/env sh
set -eu
if ! command -v uv >/dev/null 2>&1; then
  echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
if [ ! -f .venv/pyvenv.cfg ] || ! grep -q '^prompt = chesslab$' .venv/pyvenv.cfg; then
  uv venv --clear --managed-python --python 3.12.11 --prompt chesslab
fi
uv sync --frozen --managed-python
