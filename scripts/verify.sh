#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

git rev-parse HEAD
git status --short --branch
make quality
make coverage COVERAGE_REPORT=--cov-report=xml:coverage.xml
