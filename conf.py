"""
conf.py - PyLink configuration core.

This module is used to access the complete configuration for the current
PyLink instance. It will load the config on first import, taking the
configuration file name from the first command-line argument, but defaulting
to 'config.yml' if this isn't given.

If world.testing is set to True, it will return a preset testing configuration
instead.

This module also provides simple checks for validating and loading YAML-format
configurations from arbitrary files.
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

        assert type(serverblock.get('channels')) == list, "'channels' option in " \
            "server block for %s must be a list, not %s." % (netname, type(serverblock['channels']).__name__)

    assert type(conf['login'].get('password')) == type(conf['login'].get('user')) == str and \
        conf['login']['password'] != "changeme", "You have not set the login details correctly!"

    return conf

def loadConf(fname, errors_fatal=True):
    """Loads a PyLink configuration file from the filename given."""
    global confname, conf
    confname = fname.split('.', 1)[0]
    with open(fname, 'r') as f:
        try:
            conf = yaml.load(f)
            conf = validateConf(conf)
        except Exception as e:
            print('ERROR: Failed to load config from %r: %s: %s' % (fname, type(e).__name__, e))
            if errors_fatal:
                sys.exit(4)
            raise
        else:
            return conf
