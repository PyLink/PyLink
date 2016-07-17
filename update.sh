#!/bin/bash
# Updates a locally installed copy of PyLink and runs it.

python3 setup.py install --user && pylink $*
