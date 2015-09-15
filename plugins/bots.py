"""
bots.py: Spawn virtual users/bots on a PyLink server and make them interact
with things.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils
from log import log

@utils.add_cmd
def spawnclient(irc, source, args):
    """<nick> <ident> <host>

    Admin-only. Spawns the specified PseudoClient on the PyLink server.
    Note: this doesn't check the validity of any fields you give it!"""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick, ident, host = args[:3]
    except ValueError:
        irc.msg(source, "Error: Not enough arguments. Needs 3: nick, user, host.")
        return
    irc.proto.spawnClient(nick, ident, host)

@utils.add_cmd
def quit(irc, source, args):
    """<target> [<reason>]

    Admin-only. Quits the PyLink client with nick <target>, if one exists."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick = args[0]
    except IndexError:
        irc.msg(source, "Error: Not enough arguments. Needs 1-2: nick, reason (optional).")
        return
    if irc.pseudoclient.uid == utils.nickToUid(irc, nick):
        irc.msg(source, "Error: Cannot quit the main PyLink PseudoClient!")
        return
    u = utils.nickToUid(irc, nick)
    quitmsg =  ' '.join(args[1:]) or 'Client Quit'
    irc.proto.quitClient(u, quitmsg)
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_QUIT', {'text': quitmsg, 'parse_as': 'QUIT'}])

def joinclient(irc, source, args):
    """<target> <channel1>,[<channel2>], etc.

    Admin-only. Joins <target>, the nick of a PyLink client, to a comma-separated list of channels."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick = args[0]
        clist = args[1].split(',')
        if not clist:
            raise IndexError
    except IndexError:
        irc.msg(source, "Error: Not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = utils.nickToUid(irc, nick)
    for channel in clist:
        if not utils.isChannel(channel):
            irc.msg(source, "Error: Invalid channel name %r." % channel)
            return
        irc.proto.joinClient(u, channel)
        irc.callHooks([u, 'PYLINK_BOTSPLUGIN_JOIN', {'channel': channel, 'users': [u],
                                                'modes': irc.channels[channel].modes,
                                                'parse_as': 'JOIN'}])
utils.add_cmd(joinclient, name='join')

@utils.add_cmd
def nick(irc, source, args):
    """<target> <newnick>

    Admin-only. Changes the nick of <target>, a PyLink client, to <newnick>."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick = args[0]
        newnick = args[1]
    except IndexError:
        irc.msg(source, "Error: Not enough arguments. Needs 2: nick, newnick.")
        return
    u = utils.nickToUid(irc, nick)
    if newnick in ('0', u):
        newnick = u
    elif not utils.isNick(newnick):
        irc.msg(source, 'Error: Invalid nickname %r.' % newnick)
        return
    irc.proto.nickClient(u, newnick)
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_NICK', {'newnick': newnick, 'oldnick': nick, 'parse_as': 'NICK'}])

@utils.add_cmd
def part(irc, source, args):
    """<target> <channel1>,[<channel2>],... [<reason>]

    Admin-only. Parts <target>, the nick of a PyLink client, from a comma-separated list of channels."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick = args[0]
        clist = args[1].split(',')
        reason = ' '.join(args[2:])
    except IndexError:
        irc.msg(source, "Error: Not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = utils.nickToUid(irc, nick)
    for channel in clist:
        if not utils.isChannel(channel):
            irc.msg(source, "Error: Invalid channel name %r." % channel)
            return
        irc.proto.partClient(u, channel, reason)
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_PART', {'channels': clist, 'text': reason, 'parse_as': 'PART'}])

@utils.add_cmd
def kick(irc, source, args):
    """<source> <channel> <user> [<reason>]

    Admin-only. Kicks <user> from <channel> via <source>, where <source> is the nick of a PyLink client."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick = args[0]
        channel = args[1]
        target = args[2]
        reason = ' '.join(args[3:])
    except IndexError:
        irc.msg(source, "Error: Not enough arguments. Needs 3-4: source nick, channel, target, reason (optional).")
        return
    u = utils.nickToUid(irc, nick) or nick
    targetu = utils.nickToUid(irc, target)
    if not utils.isChannel(channel):
        irc.msg(source, "Error: Invalid channel name %r." % channel)
        return
    if utils.isInternalServer(irc, u):
        irc.proto.kickServer(u, channel, targetu, reason)
    else:
        irc.proto.kickClient(u, channel, targetu, reason)
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_KICK', {'channel': channel, 'target': targetu, 'text': reason, 'parse_as': 'KICK'}])

@utils.add_cmd
def mode(irc, source, args):
    """<source> <target> <modes>

    Admin-only. Sets modes <modes> on <target> from <source>, where <source> is either the nick of a PyLink client, or the SID of a PyLink server. <target> can be either a nick or a channel."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        modesource, target, modes = args[0], args[1], args[2:]
    except IndexError:
        irc.msg(source, 'Error: Not enough arguments. Needs 3: source nick, target, modes to set.')
        return
    target = utils.nickToUid(irc, target) or target
    if not (target in irc.users or target in irc.channels):
        irc.msg(source, "Error: Invalid channel or nick %r." % target)
        return
    elif target in irc.users and not irc.proto.allow_forceset_usermodes:
        irc.msg(source, "Error: this IRCd does not allow forcing user mode "
                        "changes on other servers' users!")
        return
    parsedmodes = utils.parseModes(irc, target, modes)
    if not parsedmodes:
        irc.msg(source, "Error: No valid modes were given.")
        return
    if utils.isInternalServer(irc, modesource):
        # Setting modes from a server.
        irc.proto.modeServer(modesource, target, parsedmodes)
    else:
        # Setting modes from a client.
        modesource = utils.nickToUid(irc, modesource)
        irc.proto.modeClient(modesource, target, parsedmodes)
    irc.callHooks([modesource, 'PYLINK_BOTSPLUGIN_MODE',
                   {'target': target, 'modes': parsedmodes, 'parse_as': 'MODE'}])

@utils.add_cmd
def msg(irc, source, args):
    """<source> <target> <text>

    Admin-only. Sends message <text> from <source>, where <source> is the nick of a PyLink client."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        msgsource, target, text = args[0], args[1], ' '.join(args[2:])
    except IndexError:
        irc.msg(source, 'Error: Not enough arguments. Needs 3: source nick, target, text.')
        return
    sourceuid = utils.nickToUid(irc, msgsource)
    if not sourceuid:
        irc.msg(source, 'Error: Unknown user %r.' % msgsource)
        return
    if not utils.isChannel(target):
        real_target = utils.nickToUid(irc, target)
        if real_target is None:
            irc.msg(source, 'Error: Unknown user %r.' % target)
            return
    else:
        real_target = target
    if not text:
        irc.msg(source, 'Error: No text given.')
        return
    irc.proto.messageClient(sourceuid, real_target, text)
    irc.callHooks([sourceuid, 'PYLINK_BOTSPLUGIN_MSG', {'target': real_target, 'text': text, 'parse_as': 'PRIVMSG'}])
