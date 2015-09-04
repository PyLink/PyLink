import sys
import os

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log
from classes import *

def _send(irc, sid, msg):
    irc.send(':%s %s' % (sid, msg))

def parseArgs(args):
    """<arg list>
    Parses a string of RFC1459-style arguments split into a list, where ":" may
    be used for multi-word arguments that last until the end of a line.
    """
    real_args = []
    for idx, arg in enumerate(args):
        real_args.append(arg)
        # If the argument starts with ':' and ISN'T the first argument.
        # The first argument is used for denoting the source UID/SID.
        if arg.startswith(':') and idx != 0:
            # : is used for multi-word arguments that last until the end
            # of the message. We can use list splicing here to turn them all
            # into one argument.
            # Set the last arg to a joined version of the remaining args
            arg = args[idx:]
            arg = ' '.join(arg)[1:]
            # Cut the original argument list right before the multi-word arg,
            # and then append the multi-word arg.
            real_args = args[:idx]
            real_args.append(arg)
            break
    return real_args

def parseTS6Args(args):
    """<arg list>

    Similar to parseArgs(), but stripping leading colons from the first argument
    of a line (usually the sender field)."""
    args = parseArgs(args)
    args[0] = args[0].split(':', 1)[1]
    return args

### OUTGOING COMMANDS

def _sendKick(irc, numeric, channel, target, reason=None):
    """<irc object> <kicker client numeric>

    Sends a kick from a PyLink PseudoClient."""
    channel = utils.toLower(irc, channel)
    if not reason:
        reason = 'No reason given'
    _send(irc, numeric, 'KICK %s %s :%s' % (channel, target, reason))
    # We can pretend the target left by its own will; all we really care about
    # is that the target gets removed from the channel userlist, and calling
    # handle_part() does that just fine.
    handle_part(irc, target, 'KICK', [channel])

def kickClient(irc, numeric, channel, target, reason=None):
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _sendKick(irc, numeric, channel, target, reason=reason)

def kickServer(irc, numeric, channel, target, reason=None):
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    _sendKick(irc, numeric, channel, target, reason=reason)

def nickClient(irc, numeric, newnick):
    """<irc object> <client numeric> <new nickname>

    Changes the nick of a PyLink PseudoClient."""
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'NICK %s %s' % (newnick, int(time.time())))
    irc.users[numeric].nick = newnick

def removeClient(irc, numeric):
    """<irc object> <client numeric>

    Removes a client from our internal databases, regardless
    of whether it's one of our pseudoclients or not."""
    for c, v in irc.channels.copy().items():
        v.removeuser(numeric)
        # Clear empty non-permanent channels.
        if not (irc.channels[c].users or ((irc.cmodes.get('permanent'), None) in irc.channels[c].modes)):
            del irc.channels[c]

    sid = numeric[:3]
    log.debug('Removing client %s from irc.users', numeric)
    del irc.users[numeric]
    log.debug('Removing client %s from irc.servers[%s]', numeric, sid)
    irc.servers[sid].users.discard(numeric)

def partClient(irc, client, channel, reason=None):
    channel = utils.toLower(irc, channel)
    if not utils.isInternalClient(irc, client):
        log.error('(%s) Error trying to part client %r to %r (no such pseudoclient exists)', irc.name, client, channel)
        raise LookupError('No such PyLink PseudoClient exists.')
    msg = "PART %s" % channel
    if reason:
        msg += " :%s" % reason
    _send(irc, client, msg)
    handle_part(irc, client, 'PART', [channel])

def quitClient(irc, numeric, reason):
    """<irc object> <client numeric>

    Quits a PyLink PseudoClient."""
    if utils.isInternalClient(irc, numeric):
        _send(irc, numeric, "QUIT :%s" % reason)
        removeClient(irc, numeric)
    else:
        raise LookupError("No such PyLink PseudoClient exists.")

def messageClient(irc, numeric, target, text):
    """<irc object> <client numeric> <text>

    Sends PRIVMSG <text> from PyLink client <client numeric>."""
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'PRIVMSG %s :%s' % (target, text))

def noticeClient(irc, numeric, target, text):
    """<irc object> <client numeric> <text>

    Sends NOTICE <text> from PyLink client <client numeric>."""
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'NOTICE %s :%s' % (target, text))

def topicClient(irc, numeric, target, text):
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'TOPIC %s :%s' % (target, text))
    irc.channels[target].topic = text
    irc.channels[target].topicset = True

### HANDLERS

def handle_privmsg(irc, source, command, args):
    # <- :70MAAAAAA PRIVMSG #dev :afasfsa
    # <- :70MAAAAAA NOTICE 0ALAAAAAA :afasfsa
    target = args[0]
    # We use lowercase channels internally, but uppercase UIDs.
    if utils.isChannel(target):
        target = utils.toLower(irc, target)
    return {'target': target, 'text': args[1]}

handle_notice = handle_privmsg

def handle_kill(irc, source, command, args):
    killed = args[0]
    data = irc.users.get(killed)
    if data:
        removeClient(irc, killed)
    return {'target': killed, 'text': args[1], 'userdata': data}

def handle_kick(irc, source, command, args):
    # :70MAAAAAA KICK #endlessvoid 70MAAAAAA :some reason
    channel = utils.toLower(irc, args[0])
    kicked = args[1]
    handle_part(irc, kicked, 'KICK', [channel, args[2]])
    return {'channel': channel, 'target': kicked, 'text': args[2]}

def handle_error(irc, numeric, command, args):
    irc.connected.clear()
    raise ProtocolError('Received an ERROR, killing!')

def handle_nick(irc, numeric, command, args):
    # <- :70MAAAAAA NICK GL-devel 1434744242
    oldnick = irc.users[numeric].nick
    newnick = irc.users[numeric].nick = args[0]
    return {'newnick': newnick, 'oldnick': oldnick, 'ts': int(args[1])}

def handle_quit(irc, numeric, command, args):
    # <- :1SRAAGB4T QUIT :Quit: quit message goes here
    removeClient(irc, numeric)
    return {'text': args[0]}

def handle_save(irc, numeric, command, args):
    # This is used to handle nick collisions. Here, the client Derp_ already exists,
    # so trying to change nick to it will cause a nick collision. On InspIRCd,
    # this will simply set the collided user's nick to its UID.

    # <- :70MAAAAAA PRIVMSG 0AL000001 :nickclient PyLink Derp_
    # -> :0AL000001 NICK Derp_ 1433728673
    # <- :70M SAVE 0AL000001 1433728673
    user = args[0]
    oldnick = irc.users[user].nick
    irc.users[user].nick = user
    return {'target': user, 'ts': int(args[1]), 'oldnick': oldnick}

def handle_squit(irc, numeric, command, args):
    # :70M SQUIT 1ML :Server quit by GL!gl@0::1
    split_server = args[0]
    affected_users = []
    log.info('(%s) Netsplit on server %s', irc.name, split_server)
    # Prevent RuntimeError: dictionary changed size during iteration
    old_servers = irc.servers.copy()
    for sid, data in old_servers.items():
        if data.uplink == split_server:
            log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
            args = handle_squit(irc, sid, 'SQUIT', [sid, "PyLink: Automatically splitting leaf servers of %s" % sid])
            affected_users += args['users']
    for user in irc.servers[split_server].users.copy():
        affected_users.append(user)
        log.debug('Removing client %s (%s)', user, irc.users[user].nick)
        removeClient(irc, user)
    del irc.servers[split_server]
    log.debug('(%s) Netsplit affected users: %s', irc.name, affected_users)
    return {'target': split_server, 'users': affected_users}

def handle_mode(irc, numeric, command, args):
    # In InspIRCd, MODE is used for setting user modes and
    # FMODE is used for channel modes:
    # <- :70MAAAAAA MODE 70MAAAAAA -i+xc
    target = args[0]
    modestrings = args[1:]
    changedmodes = utils.parseModes(irc, numeric, modestrings)
    utils.applyModes(irc, target, changedmodes)
    return {'target': target, 'modes': changedmodes}

def handle_topic(irc, numeric, command, args):
    # <- :70MAAAAAA TOPIC #test :test
    channel = utils.toLower(irc, args[0])
    topic = args[1]
    ts = int(time.time())
    irc.channels[channel].topic = topic
    irc.channels[channel].topicset = True
    return {'channel': channel, 'setter': numeric, 'ts': ts, 'topic': topic}

def handle_part(irc, source, command, args):
    channels = utils.toLower(irc, args[0]).split(',')
    for channel in channels:
        # We should only get PART commands for channels that exist, right??
        irc.channels[channel].removeuser(source)
        try:
            irc.users[source].channels.discard(channel)
        except KeyError:
            log.debug("(%s) handle_part: KeyError trying to remove %r from %r's channel list?", irc.name, channel, source)
        try:
            reason = args[1]
        except IndexError:
            reason = ''
        # Clear empty non-permanent channels.
        if not (irc.channels[channel].users or ((irc.cmodes.get('permanent'), None) in irc.channels[channel].modes)):
            del irc.channels[channel]
    return {'channels': channels, 'text': reason}
