import logging
import sys
from conf import conf

level = conf['bot']['loglevel'].upper()
try:
    level = getattr(logging, level)
except AttributeError:
    print('ERROR: Invalid log level %r specified in config.' % level)
    sys.exit(3)

logging.basicConfig(level=level, format='%(asctime)s [%(levelname)s] %(message)s')

global log
log = logging.getLogger()
