# admin.py: PyLink administrative commands
import sys
import os
import inspect
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

class NotAuthenticatedError(Exception):
    pass

def checkauthenticated(irc, source):
    lastfunc = inspect.stack()[1][3]
    if not irc.users[source].identified:
        log.warning('(%s) Access denied for %s calling %r', irc.name,
                    utils.getHostmask(irc, source), lastfunc)
        raise NotAuthenticatedError("You are not authenticated!")

def _exec(irc, source, args):
    """<code>

    Admin-only. Executes <code> in the current PyLink instance.
    \x02**WARNING: THIS CAN BE DANGEROUS IF USED IMPROPERLY!**\x02"""
    checkauthenticated(irc, source)
    args = ' '.join(args)
    if not args.strip():
        utils.msg(irc, source, 'No code entered!')
        return
    log.info('(%s) Executing %r for %s', irc.name, args, utils.getHostmask(irc, source))
    exec(args, globals(), locals())
utils.add_cmd(_exec, 'exec')

@utils.add_cmd
def spawnclient(irc, source, args):
    """<nick> <ident> <host>

    Admin-only. Spawns the specified PseudoClient on the PyLink server.
    Note: this doesn't check the validity of any fields you give it!"""
    checkauthenticated(irc, source)
    try:
        nick, ident, host = args[:3]
    except ValueError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 3: nick, user, host.")
        return
    irc.proto.spawnClient(irc, nick, ident, host)

@utils.add_cmd
def quit(irc, source, args):
    """<target> [<reason>]

    Admin-only. Quits the PyLink client with nick <target>, if one exists."""
    checkauthenticated(irc, source)
    try:
        nick = args[0]
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1-2: nick, reason (optional).")
        return
    if irc.pseudoclient.uid == utils.nickToUid(irc, nick):
        utils.msg(irc, source, "Error: cannot quit the main PyLink PseudoClient!")
        return
    u = utils.nickToUid(irc, nick)
    quitmsg =  ' '.join(args[1:]) or 'Client quit'
    irc.proto.quitClient(irc, u, quitmsg)
    irc.callHooks([u, 'PYLINK_ADMIN_QUIT', {'text': quitmsg, 'parse_as': 'QUIT'}])

def joinclient(irc, source, args):
    """<target> <channel1>,[<channel2>], etc.

    Admin-only. Joins <target>, the nick of a PyLink client, to a comma-separated list of channels."""
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        clist = args[1].split(',')
        if not clist:
            raise IndexError
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = utils.nickToUid(irc, nick)
    for channel in clist:
        if not utils.isChannel(channel):
            utils.msg(irc, source, "Error: Invalid channel name %r." % channel)
            return
        irc.proto.joinClient(irc, u, channel)
        irc.callHooks([u, 'PYLINK_ADMIN_JOIN', {'channel': channel, 'users': [u],
                                                'modes': irc.channels[channel].modes,
                                                'parse_as': 'JOIN'}])
utils.add_cmd(joinclient, name='join')

@utils.add_cmd
def nick(irc, source, args):
    """<target> <newnick>

    Admin-only. Changes the nick of <target>, a PyLink client, to <newnick>."""
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        newnick = args[1]
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2: nick, newnick.")
        return
    u = utils.nickToUid(irc, nick)
    if newnick in ('0', u):
        newnick = u
    elif not utils.isNick(newnick):
        utils.msg(irc, source, 'Error: Invalid nickname %r.' % newnick)
        return
    irc.proto.nickClient(irc, u, newnick)
    irc.callHooks([u, 'PYLINK_ADMIN_NICK', {'newnick': newnick, 'oldnick': nick, 'parse_as': 'NICK'}])

@utils.add_cmd
def part(irc, source, args):
    """<target> <channel1>,[<channel2>],... [<reason>]

    Admin-only. Parts <target>, the nick of a PyLink client, from a comma-separated list of channels."""
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        clist = args[1].split(',')
        reason = ' '.join(args[2:])
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = utils.nickToUid(irc, nick)
    for channel in clist:
        if not utils.isChannel(channel):
            utils.msg(irc, source, "Error: Invalid channel name %r." % channel)
            return
        irc.proto.partClient(irc, u, channel, reason)
    irc.callHooks([u, 'PYLINK_ADMIN_PART', {'channels': clist, 'text': reason, 'parse_as': 'PART'}])

@utils.add_cmd
def kick(irc, source, args):
    """<source> <channel> <user> [<reason>]

    Admin-only. Kicks <user> from <channel> via <source>, where <source> is the nick of a PyLink client."""
    checkauthenticated(irc, source)
    try:
        nick = args[0]
        channel = args[1]
        target = args[2]
        reason = ' '.join(args[3:])
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 3-4: source nick, channel, target, reason (optional).")
        return
    u = utils.nickToUid(irc, nick) or nick
    targetu = utils.nickToUid(irc, target)
    if not utils.isChannel(channel):
        utils.msg(irc, source, "Error: Invalid channel name %r." % channel)
        return
    if utils.isInternalServer(irc, u):
        irc.proto.kickServer(irc, u, channel, targetu, reason)
    else:
        irc.proto.kickClient(irc, u, channel, targetu, reason)
    irc.callHooks([u, 'PYLINK_ADMIN_KICK', {'channel': channel, 'target': targetu, 'text': reason, 'parse_as': 'KICK'}])

@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Admin-only. Shows information about <user>."""
    checkauthenticated(irc, source)
    try:
        target = args[0]
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1: nick.")
        return
    u = utils.nickToUid(irc, target)
    if u is None:
        utils.msg(irc, source, 'Error: unknown user %r' % target)
        return
    s = ['\x02%s\x02: %s' % (k, v) for k, v in sorted(irc.users[u].__dict__.items())]
    s = 'Information on user \x02%s\x02: %s' % (target, '; '.join(s))
    utils.msg(irc, source, s)

@utils.add_cmd
def showchan(irc, source, args):
    """<channel>

    Admin-only. Shows information about <channel>."""
    checkauthenticated(irc, source)
    try:
        channel = args[0].lower()
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1: channel.")
        return
    if channel not in irc.channels:
        utils.msg(irc, source, 'Error: unknown channel %r' % channel)
        return
    s = ['\x02%s\x02: %s' % (k, v) for k, v in sorted(irc.channels[channel].__dict__.items())]
    s = 'Information on channel \x02%s\x02: %s' % (channel, '; '.join(s))
    utils.msg(irc, source, s)

@utils.add_cmd
def mode(irc, source, args):
    """<source> <target> <modes>

    Admin-only. Sets modes <modes> on <target> from <source>, where <source> is either the nick of a PyLink client, or the SID of a PyLink server."""
    checkauthenticated(irc, source)
    try:
        modesource, target, modes = args[0], args[1], args[2:]
    except IndexError:
        utils.msg(irc, source, 'Error: not enough arguments. Needs 3: source nick, target, modes to set.')
        return
    if not modes:
        utils.msg(irc, source, "Error: no modes given to set!")
        return
    parsedmodes = utils.parseModes(irc, target, modes)
    targetuid = utils.nickToUid(irc, target)
    if targetuid:
        target = targetuid
    elif not utils.isChannel(target):
        utils.msg(irc, source, "Error: Invalid channel or nick %r." % target)
        return
    if utils.isInternalServer(irc, modesource):
        irc.proto.modeServer(irc, modesource, target, parsedmodes)
        irc.callHooks([modesource, 'PYLINK_ADMIN_MODE', {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])
    else:
        sourceuid = utils.nickToUid(irc, modesource)
        irc.proto.modeClient(irc, sourceuid, target, parsedmodes)
        irc.callHooks([sourceuid, 'PYLINK_ADMIN_MODE', {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])

@utils.add_cmd
def msg(irc, source, args):
    """<source> <target> <text>

    Admin-only. Sends message <text> from <source>, where <source> is the nick of a PyLink client."""
    checkauthenticated(irc, source)
    try:
        msgsource, target, text = args[0], args[1], ' '.join(args[2:])
    except IndexError:
        utils.msg(irc, source, 'Error: not enough arguments. Needs 3: source nick, target, text.')
        return
    sourceuid = utils.nickToUid(irc, msgsource)
    if not sourceuid:
        utils.msg(irc, source, 'Error: unknown user %r' % msgsource)
        return
    if not utils.isChannel(target):
        real_target = utils.nickToUid(irc, target)
        if real_target is None:
            utils.msg(irc, source, 'Error: unknown user %r' % target)
            return
    else:
        real_target = target
    if not text:
        utils.msg(irc, source, 'Error: no text given.')
        return
    irc.proto.messageClient(irc, sourceuid, real_target, text)
    irc.callHooks([sourceuid, 'PYLINK_ADMIN_MSG', {'target': real_target, 'text': text, 'parse_as': 'PRIVMSG'}])
