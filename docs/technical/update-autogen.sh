#!/bin/bash
# Deletes and updates the contents of the autogen/ folder

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
pwd
shopt -s nullglob
rm -v autogen/*.html

# cd to the main folder
cd ../..
pwd

# Iterate over all the .py files and run pydoc3 on them.
for module in *.py protocols/*.py; do
	echo "Running pydoc3 -w ./$module"
	pydoc3 -w "./$module"
	# Then, move the generated HTML files to the right place.
	name="$(basename $module .py).html"
	mv "$name" "$SCRIPT_DIR/autogen/$name"
done
