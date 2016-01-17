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
        irc.reply("Error: Not enough arguments. Needs 3: nick, user, host.")
        return
    irc.proto.spawnClient(nick, ident, host, manipulatable=True)

@utils.add_cmd
def quit(irc, source, args):
    """<target> [<reason>]

    Admin-only. Quits the PyLink client with nick <target>, if one exists."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        nick = args[0]
    except IndexError:
        irc.reply("Error: Not enough arguments. Needs 1-2: nick, reason (optional).")
        return
    if irc.pseudoclient.uid == irc.nickToUid(nick):
        irc.reply("Error: Cannot quit the main PyLink PseudoClient!")
        return
    u = irc.nickToUid(nick)
    quitmsg =  ' '.join(args[1:]) or 'Client Quit'
    if not utils.isManipulatableClient(irc, u):
        irc.reply("Error: Cannot force quit a protected PyLink services client.")
        return
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
        irc.reply("Error: Not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = irc.nickToUid(nick)
    if not utils.isManipulatableClient(irc, u):
        irc.reply("Error: Cannot force join a protected PyLink services client.")
        return
    for channel in clist:
        if not utils.isChannel(channel):
            irc.reply("Error: Invalid channel name %r." % channel)
            return
        irc.proto.join(u, channel)
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
        irc.reply("Error: Not enough arguments. Needs 2: nick, newnick.")
        return
    u = irc.nickToUid(nick)
    if newnick in ('0', u):
        newnick = u
    elif not utils.isNick(newnick):
        irc.reply('Error: Invalid nickname %r.' % newnick)
        return
    elif not utils.isManipulatableClient(irc, u):
        irc.reply("Error: Cannot force nick changes for a protected PyLink services client.")
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
        irc.reply("Error: Not enough arguments. Needs 2: nick, comma separated list of channels.")
        return
    u = irc.nickToUid(nick)
    if not utils.isManipulatableClient(irc, u):
        irc.reply("Error: Cannot force part a protected PyLink services client.")
        return
    for channel in clist:
        if not utils.isChannel(channel):
            irc.reply("Error: Invalid channel name %r." % channel)
            return
        irc.proto.partClient(u, channel, reason)
    irc.callHooks([u, 'PYLINK_BOTSPLUGIN_PART', {'channels': clist, 'text': reason, 'parse_as': 'PART'}])

@utils.add_cmd
def msg(irc, source, args):
    """<source> <target> <text>

    Admin-only. Sends message <text> from <source>, where <source> is the nick of a PyLink client."""
    utils.checkAuthenticated(irc, source, allowOper=False)
    try:
        msgsource, target, text = args[0], args[1], ' '.join(args[2:])
    except IndexError:
        irc.reply('Error: Not enough arguments. Needs 3: source nick, target, text.')
        return
    sourceuid = irc.nickToUid(msgsource)
    if not sourceuid:
        irc.reply('Error: Unknown user %r.' % msgsource)
        return
    if not utils.isChannel(target):
        real_target = irc.nickToUid(target)
        if real_target is None:
            irc.reply('Error: Unknown user %r.' % target)
            return
    else:
        real_target = target
    if not text:
        irc.reply('Error: No text given.')
        return
    irc.proto.message(sourceuid, real_target, text)
    irc.callHooks([sourceuid, 'PYLINK_BOTSPLUGIN_MSG', {'target': real_target, 'text': text, 'parse_as': 'PRIVMSG'}])
