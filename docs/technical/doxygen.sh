#!/bin/bash
# Runs Doxygen on PyLink.

# Note: to change the outpuit path, doxygen.conf also has to be updated too!
OUTDIR="../../../pylink.github.io"

if [ ! -d "$OUTDIR" ]; then
	echo "Git clone https://github.com/PyLink/pylink.github.io to $OUTDIR and then rerun this script."
	exit 1
fi

CURDIR="$(pwd)"
doxygen doxygen.conf
cp -R html/* "$OUTDIR"
rm -r "html/"
