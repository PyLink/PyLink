import yaml
import sys
from collections import defaultdict

import world

global testconf
testconf = {'bot':
                {
                    'nick': 'PyLink',
                    'user': 'pylink',
                    'realname': 'PyLink Service Client',
                    # Suppress logging in the test output for the most part.
                    'loglevel': 'CRITICAL',
                    'serverdesc': 'PyLink unit tests'
                },
            'servers':
                # Wildcard defaultdict! This means that
                # any network name you try will work and return
                # this basic template:
                defaultdict(lambda: {
                        'ip': '0.0.0.0',
                        'port': 7000,
                        'recvpass': "abcd",
                        'sendpass': "chucknorris",
                        'protocol': "null",
                        'hostname': "pylink.unittest",
                        'sid': "9PY",
                        'channels': ["#pylink"],
                        'maxnicklen': 20
                    })
           }
if world.testing:
    conf = testconf
    confname = 'testconf'
else:
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
        try:
            conf = yaml.load(f)
        except Exception as e:
            print('ERROR: Failed to load config from %r: %s: %s' % (fname, type(e).__name__, e))
            sys.exit(4)
