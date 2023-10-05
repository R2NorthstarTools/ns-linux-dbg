#!/usr/bin/env bash
set -eu

SCRIPT="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname ${SCRIPT})"

. "${SCRIPT_DIR}/.helper.sh"

gdb_ns
