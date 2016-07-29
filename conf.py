"""
conf.py - PyLink configuration core.

This module is used to access the configuration of the current PyLink instance.
It provides simple checks for validating and loading YAML-format configurations from arbitrary files.
"""

try:
    import yaml
except ImportError:
    raise ImportError("Please install PyYAML and try again.")

import sys
from collections import defaultdict

from . import world

conf = {'bot':
                {
                    'nick': 'PyLink',
                    'user': 'pylink',
                    'realname': 'PyLink Service Client',
                    'serverdesc': 'Unconfigured PyLink'
                },
        'logging':
                {
                    'stdout': 'INFO'
                },
        'servers':
                # Wildcard defaultdict! This means that
                # any network name you try will work and return
                # this basic template:
                defaultdict(lambda: {'ip': '0.0.0.0',
                                     'port': 7000,
                                     'recvpass': "unconfigured",
                                     'sendpass': "unconfigured",
                                     'protocol': "null",
                                     'hostname': "pylink.unconfigured",
                                     'sid': "000",
                                     'maxnicklen': 20,
                                     'sidrange': '0##'
                                    })
        }
confname = 'unconfigured'

def validateConf(conf):
    """Validates a parsed configuration dict."""
    assert type(conf) == dict, "Invalid configuration given: should be type dict, not %s." % type(conf).__name__

    for section in ('bot', 'servers', 'login', 'logging'):
        assert conf.get(section), "Missing %r section in config." % section

    assert type(conf['login'].get('password')) == type(conf['login'].get('user')) == str and \
        conf['login']['password'] != "changeme", "You have not set the login details correctly!"

    return conf

def loadConf(filename, errors_fatal=True):
    """Loads a PyLink configuration file from the filename given."""
    global confname, conf, fname
    fname = filename
    confname = filename.split('.', 1)[0]
    try:
        with open(filename, 'r') as f:
            conf = yaml.load(f)
            conf = validateConf(conf)
    except Exception as e:
        print('ERROR: Failed to load config from %r: %s: %s' % (filename, type(e).__name__, e), file=sys.stderr)
        print('       Users upgrading from users < 0.9-alpha1 should note that the default configuration has been renamed to *pylink.yml*, not *config.yml*', file=sys.stderr)

        if errors_fatal:
            sys.exit(4)
        raise
    else:
        return conf
