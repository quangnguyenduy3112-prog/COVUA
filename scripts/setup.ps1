$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}
if (-not (Test-Path ".venv/pyvenv.cfg") -or
    -not (Select-String -Path ".venv/pyvenv.cfg" -Pattern "^prompt = chesslab$" -Quiet)) {
  uv venv --clear --managed-python --python 3.12.11 --prompt chesslab
}
uv sync --frozen --managed-python
