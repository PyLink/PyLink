"""
exttargets.py - Implements extended targets like $account:xyz, $oper, etc.
"""

from pylinkirc import world
from pylinkirc.log import log

def bind(func):
    """
    Binds an exttarget with the given name.
    """
    world.exttarget_handlers[func.__name__] = func
    return func

@bind
def account(irc, host, uid):
    """
    $account exttarget handler. The following forms are supported, with groups separated by a
    literal colon. All account and network name matching is currently case sensitive:

    $account -> Returns True (a match) if the target is registered.
    $account:accountname -> Returns True if the target's account name matches the one given, and the
    target is connected to the local network..
    $account:accountname:netname -> Returns True if both the target's account name and origin
    network name match the ones given.
    $account:*:netname -> Matches all logged in users on the given network.
    """
    userobj = irc.users[uid]
    homenet = irc.name
    if hasattr(userobj, 'remote'):
        # User is a PyLink Relay pseudoclient. Use their real services account on their
        # origin network.
        homenet, realuid = userobj.remote
        log.debug('(%s) exttargets.account: Changing UID of relay client %s to %s/%s', irc.name,
                  uid, homenet, realuid)
        try:
            userobj = world.networkobjects[homenet].users[realuid]
        except KeyError:  # User lookup failed. Bail and return False.
            log.exception('(%s) exttargets.account: KeyError finding %s/%s:', irc.name,
                          homenet, realuid)
            return False

    slogin = userobj.services_account

    # Split the given exttarget host into parts, so we know how many to look for.
    groups = host.split(':')
    log.debug('(%s) exttargets.account: groups to match: %s', irc.name, groups)

    if len(groups) == 1:
        # First scenario. Return True if user is logged in.
        return bool(slogin)
    elif len(groups) == 2:
        # Second scenario. Return True if the user's account matches the one given.
        return slogin == groups[1] and homenet == irc.name
    else:
        # Third or fourth scenario. If there are more than 3 groups, the rest are ignored.
        return (groups[1] in ('*', slogin)) and (homenet == groups[2])
