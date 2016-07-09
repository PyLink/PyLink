# servprotect.py: Protects against KILL and nick collision floods
from expiringdict import ExpiringDict

from pylinkirc import utils
from pylinkirc.log import log

# TODO: make length and time configurable
savecache = ExpiringDict(max_len=5, max_age_seconds=10)
killcache = ExpiringDict(max_len=5, max_age_seconds=10)

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
