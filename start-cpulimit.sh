#!/usr/bin/env bash
# Shell script to start PyLink under CPUlimit, killing it if it starts abusing the CPU.

# Set this to whatever you want. cpulimit --help
LIMIT=20

# Change to the PyLink root directory.
WRAPPER_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$WRAPPER_DIR"

if [[ ! -z "$(which cpulimit)" ]]; then
	# -k kills the PyLink daemon if it goes over $LIMIT
	# -z makes cpulimit exit when PyLink dies.
	cpulimit -l $LIMIT -z -k ./main.py
	echo "PyLink has been started (daemonized) under cpulimit, and will automatically be killed if it goes over the CPU limit of ${LIMIT}%."
	echo "To kill the process manually, run ./kill.sh"
else
	echo 'cpulimit not found in $PATH! Aborting.'
fi
