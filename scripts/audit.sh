#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

printf '=== Git revision ===\n'
git log -1 --format='%H %s'
git status --short --branch

printf '\n=== Tracked project structure ===\n'
git ls-files

printf '\n=== Setup and documentation ===\n'
for path in .gitignore Makefile make/*.mk pyproject.toml requirements*.txt \
    docker/Dockerfile docker/Dockerfile.dockerignore docker/compose.yaml README.md; do
    [[ -f "$path" ]] || continue
    printf '\n--- %s ---\n' "$path"
    cat -- "$path"
done

printf '\n=== Local tools ===\n'
for executable in python3 make docker; do
    command -v "$executable" || printf '%s unavailable\n' "$executable"
done

python_path="${PYTHON:-.venv/bin/python}"
if [[ -x "$python_path" ]]; then
    "$python_path" -c 'import sys; print(sys.executable, sys.version.split()[0]); print("Virtualenv:", sys.prefix != sys.base_prefix)'
else
    printf 'Project interpreter unavailable at %s\n' "$python_path"
fi
