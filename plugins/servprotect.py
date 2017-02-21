# servprotect.py: Protects against KILL and nick collision floods
from expiringdict import ExpiringDict

from pylinkirc import utils
from pylinkirc.conf import conf
from pylinkirc.log import log

# we've already checked this combinations sanity.
# so lets set this up

length = conf['servprotect'].get('length', 5)
age    = conf['servprotect'].get('max_age', 10)

savecache = ExpiringDict(max_len=length, max_age_seconds=age)
killcache = ExpiringDict(max_len=length, max_age_seconds=age)

def handle_kill(irc, numeric, command, args):
    """
    Tracks kills against PyLink clients. If too many are received,
    automatically disconnects from the network.
    """
    if killcache.setdefault(irc.name, 1) >= 5:
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
    if savecache.setdefault(irc.name, 0) >= 5:
        log.error('(%s) servprotect: Too many nick collisions, aborting!', irc.name)
        irc.disconnect()

    log.debug('(%s) servprotect: Incrementing savecache by 1', irc.name)
    savecache[irc.name] += 1

utils.add_hook(handle_save, 'SAVE')
