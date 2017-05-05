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
    literal colon. Account matching is case insensitive, while network name matching IS case
    sensitive.

    $account -> Returns True (a match) if the target is registered.
    $account:accountname -> Returns True if the target's account name matches the one given, and the
    target is connected to the local network.
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

    slogin = irc.toLower(userobj.services_account)

    # Split the given exttarget host into parts, so we know how many to look for.
    groups = list(map(irc.toLower, host.split(':')))
    log.debug('(%s) exttargets.account: groups to match: %s', irc.name, groups)

    if len(groups) == 1:
        # First scenario. Return True if user is logged in.
        return bool(slogin)
    elif len(groups) == 2:
        # Second scenario. Return True if the user's account matches the one given.
        return slogin == groups[1] and homenet == irc.name
    else:
        # Third or fourth scenario. If there are more than 3 groups, the rest are ignored.
        # In other words: Return True if the user is logged in, the query matches either '*' or the
        # user's login, and the user is connected on the network requested.
        return slogin and (groups[1] in ('*', slogin)) and (homenet == groups[2])

@bind
def ircop(irc, host, uid):
    """
    $ircop exttarget handler. The following forms are supported, with groups separated by a
    literal colon. Oper types are matched case insensitively.

    $ircop -> Returns True (a match) if the target is opered.
    $ircop:*admin* -> Returns True if the target's is opered and their opertype matches the glob
    given.
    """
    groups = host.split(':')
    log.debug('(%s) exttargets.ircop: groups to match: %s', irc.name, groups)

    if len(groups) == 1:
        # 1st scenario.
        return irc.isOper(uid, allowAuthed=False)
    else:
        # 2nd scenario. Use matchHost (ircmatch) to match the opertype glob to the opertype.
        return irc.matchHost(groups[1], irc.users[uid].opertype)

@bind
def server(irc, host, uid):
    """
    $server exttarget handler. The following forms are supported, with groups separated by a
    literal colon. Server names are matched case insensitively, but SIDs ARE case sensitive.

    $server:server.name -> Returns True (a match) if the target is connected on the given server.
    $server:server.glob -> Returns True (a match) if the target is connected on a server matching the glob.
    $server:1XY -> Returns True if the target's is connected on the server with the given SID.
    """
    groups = host.split(':')
    log.debug('(%s) exttargets.server: groups to match: %s', irc.name, groups)

    if len(groups) >= 2:
        sid = irc.getServer(uid)
        query = groups[1]
        # Return True if the SID matches the query or the server's name glob matches it.
        return sid == query or irc.matchHost(query, irc.getFriendlyName(sid))
    # $server alone is invalid. Don't match anything.
    return False

@bind
def channel(irc, host, uid):
    """
    $channel exttarget handler. The following forms are supported, with groups separated by a
    literal colon. Channel names are matched case insensitively.

    $channel:#channel -> Returns True if the target is in the given channel.
    $channel:#channel:op -> Returns True if the target is in the given channel, and is opped.
    Any other supported prefix (owner, admin, op, halfop, voice) can be given, but only one at a
    time.
    """
    groups = host.split(':')
    log.debug('(%s) exttargets.channel: groups to match: %s', irc.name, groups)
    try:
        channel = groups[1]
    except IndexError:  # No channel given, abort.
        return False

    if len(groups) == 2:
        # Just #channel was given as query
        return uid in irc.channels[channel].users
    elif len(groups) >= 3:
        # For things like #channel:op, check if the query is in the user's prefix modes.
        return (uid in irc.channels[channel].users) and (groups[2].lower() in irc.channels[channel].getPrefixModes(uid))

@bind
def pylinkacc(irc, host, uid):
    """
    $pylinkacc (PyLink account) exttarget handler. The following forms are supported, with groups
    separated by a literal colon. Account matching is case insensitive.

    $pylinkacc -> Returns True if the target is logged in to PyLink.
    $pylinkacc:accountname -> Returns True if the target's PyLink login matches the one given.
    """
    login = irc.toLower(irc.users[uid].account)
    groups = list(map(irc.toLower, host.split(':')))
    log.debug('(%s) exttargets.pylinkacc: groups to match: %s', irc.name, groups)

    if len(groups) == 1:
        # First scenario. Return True if user is logged in.
        return bool(login)
    elif len(groups) == 2:
        # Second scenario. Return True if the user's login matches the one given.
        return login == groups[1]

@bind
def network(irc, host, uid):
    """
    $network exttarget handler. This exttarget takes one argument: a network name, and returns
    a match for all users on that network.

    Note: network names are case sensitive.
    """
    try:
        targetnet = host.split(':')[1]
    except IndexError:  # No network arg given, bail.
        return False

    userobj = irc.users[uid]
    if hasattr(userobj, 'remote'):
        # User is a PyLink Relay client; set the correct network name.
        homenet = userobj.remote[0]
    else:
        homenet = irc.name

    return homenet == targetnet

# Note: "and" can't be a function name so we use this.
def exttarget_and(irc, host, uid):
    """
    $and exttarget handler. This exttarget takes a series of exttargets (or hostmasks) joined with
    a "+", and returns True if all sub exttargets match.

    Examples:
    $and:($ircop:*admin*+$network:ovd) -> Matches all opers on the network ovd.
    $and:($account+$pylinkirc) -> Matches all users logged in to both services and PyLink.
    $and:(*!*@localhost+$ircop) -> Matches all opers with the host `localhost`.
    $and:(*!*@*.mibbit.com+!$ircop+!$account) -> Matches all mibbit users that aren't opered or logged in to services.
    """
    targets = host.split(':', 1)[-1]
    # For readability, this requires that the exttarget list be wrapped in brackets.
    if not (targets.startswith('(') and targets.endswith(')')):
        return False

    targets = targets[1:-1]
    targets = list(filter(None, targets.split('+')))
    log.debug('exttargets_and: using raw subtargets list %r (original query=%r)', targets, host)
    # Wrap every subtarget into irc.matchHost and return True if all subtargets return True.
    return all(map(lambda sub_exttarget: irc.matchHost(sub_exttarget, uid), targets))
world.exttarget_handlers['and'] = exttarget_and
