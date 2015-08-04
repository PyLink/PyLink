import yaml
import sys

global confname
try:
    # Get the config name from the command line, falling back to config.yml
    # if not given.
    fname = sys.argv[1]
    confname = fname.split('.', 1)[0]
except IndexError:
    # confname is used for logging and PID writing, so that each
    # instance uses its own files. fname is the actual name of the file
    # we load.
    confname = 'pylink'
    fname = 'config.yml'

with open(fname, 'r') as f:
    global conf
    conf = yaml.load(f)
