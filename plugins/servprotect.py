# servprotect.py: Protects against KILL and nick collision floods

import threading

from pylinkirc import conf, utils
from pylinkirc.log import log

try:
    from cachetools import TTLCache
except ImportError:
    log.warning('servprotect: expiringdict support is deprecated as of PyLink 3.0; consider installing cachetools instead')
    from expiringdict import ExpiringDict as TTLCache

# check for definitions
servprotect_conf = conf.conf.get('servprotect', {})
length = servprotect_conf.get('length', 10)
age = servprotect_conf.get('age', 10)

def _new_cache_dict():
    return TTLCache(length, age)

savecache = _new_cache_dict()
killcache = _new_cache_dict()
lock = threading.Lock()

def handle_kill(irc, numeric, command, args):
    """
    Tracks kills against PyLink clients. If too many are received,
    automatically disconnects from the network.
    """

    if (args['userdata'] and irc.is_internal_server(args['userdata'].server)) or irc.is_internal_client(args['target']):
        with lock:
            if killcache.setdefault(irc.name, 1) >= length:
                log.error('(%s) servprotect: Too many kills received, aborting!', irc.name)
                irc.disconnect()

            log.debug('(%s) servprotect: Incrementing killcache by 1', irc.name)
            killcache[irc.name] += 1

utils.add_hook(handle_kill, 'KILL')

def handle_save(irc, numeric, command, args):
    """
    Tracks SAVEs (nick collision) against PyLink clients. If too many are received,
    automatically disconnects from the network.
    """
    if irc.is_internal_client(args['target']):
        with lock:
            if savecache.setdefault(irc.name, 0) >= length:
                log.error('(%s) servprotect: Too many nick collisions, aborting!', irc.name)
                irc.disconnect()

            log.debug('(%s) servprotect: Incrementing savecache by 1', irc.name)
            savecache[irc.name] += 1

utils.add_hook(handle_save, 'SAVE')
