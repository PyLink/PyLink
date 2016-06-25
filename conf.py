"""
conf.py - PyLink configuration core.

This module is used to access the configuration of the current PyLink instance.
It provides simple checks for validating and loading YAML-format configurations from arbitrary files.
"""

import yaml
import sys
from collections import defaultdict

from . import world

def validateConf(conf):
    """Validates a parsed configuration dict."""
    assert type(conf) == dict, "Invalid configuration given: should be type dict, not %s." % type(conf).__name__

    for section in ('bot', 'servers', 'login', 'logging'):
        assert conf.get(section), "Missing %r section in config." % section

    for netname, serverblock in conf['servers'].items():
        for section in ('ip', 'port', 'recvpass', 'sendpass', 'hostname',
                        'sid', 'sidrange', 'protocol', 'maxnicklen'):
            assert serverblock.get(section), "Missing %r in server block for %r." % (section, netname)

    assert type(conf['login'].get('password')) == type(conf['login'].get('user')) == str and \
        conf['login']['password'] != "changeme", "You have not set the login details correctly!"

    return conf

def loadConf(filename, errors_fatal=True):
    """Loads a PyLink configuration file from the filename given."""
    global confname, conf, fname
    fname = filename
    confname = filename.split('.', 1)[0]
    with open(filename, 'r') as f:
        try:
            conf = yaml.load(f)
            conf = validateConf(conf)
        except Exception as e:
            print('ERROR: Failed to load config from %r: %s: %s' % (filename, type(e).__name__, e))
            if errors_fatal:
                sys.exit(4)
            raise
        else:
            return conf
