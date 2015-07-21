import time
import sys
import os
import re
from copy import copy

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log

from classes import *
# Shared with inspircd module because the output is the same.
from inspircd import nickClient, kickServer, kickClient, _sendKick, quitClient, \
    removeClient, partClient, messageClient, noticeClient, topicClient
from inspircd import handle_privmsg, handle_kill, handle_kick, handle_error, \
    handle_quit

hook_map = {'SJOIN': 'JOIN'}

def _send(irc, sid, msg):
    irc.send(':%s %s' % (sid, msg))

def spawnClient(irc, nick, ident='null', host='null', realhost=None, modes=set(),
        server=None, ip='0.0.0.0', realname=None):
    server = server or irc.sid
    if not utils.isInternalServer(irc, server):
        raise ValueError('Server %r is not a PyLink internal PseudoServer!' % server)
    # We need a separate UID generator instance for every PseudoServer
    # we spawn. Otherwise, things won't wrap around properly.
    if server not in irc.uidgen:
        irc.uidgen[server] = utils.TS6UIDGenerator(server)
    uid = irc.uidgen[server].next_uid()
    # UID:
    # parameters: nickname, hopcount, nickTS, umodes, username,
    # visible hostname, IP address, UID, gecos
    ts = int(time.time())
    realname = realname or irc.botdata['realname']
    realhost = realhost or host
    raw_modes = utils.joinModes(modes)
    u = irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
        realhost=realhost, ip=ip, modes=modes)
    irc.servers[server].users.append(uid)
    _send(irc, server, "UID {nick} 1 {ts} {modes} {ident} {host} {ip} {uid} "
                    ":{realname}".format(ts=ts, host=host,
                                         nick=nick, ident=ident, uid=uid,
                                         modes=raw_modes, ip=ip, realname=realname))
    return u

def joinClient(irc, client, channel):
    channel = channel.lower()
    server = utils.isInternalClient(irc, client)
    # JOIN:
    # parameters: channelTS, channel, '+' (a plus sign)
    if not server:
        log.error('(%s) Error trying to join client %r to %r (no such pseudoclient exists)', irc.name, client, channel)
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, client, "JOIN {ts} {channel} +".format(
            ts=irc.channels[channel].ts, channel=channel))
    irc.channels[channel].users.add(client)
    irc.users[client].channels.add(channel)

def sjoinServer(irc, server, channel, users, ts=None):
    # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L821
    # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist

    # Broadcasts a channel creation or bursts a channel.

    # The nicklist consists of users joining the channel, with status prefixes for
    # their status ('@+', '@', '+' or ''), for example:
    # '@+1JJAAAAAB +2JJAAAA4C 1JJAAAADS'. All users must be behind the source server
    # so it is not possible to use this message to force users to join a channel.
    channel = channel.lower()
    server = server or irc.sid
    assert users, "sjoinServer: No users sent?"
    if not server:
        raise LookupError('No such PyLink PseudoClient exists.')
    if ts is None:
        ts = irc.channels[channel].ts
    log.debug("sending SJOIN to %s%s with ts %s (that's %r)", channel, irc.name, ts, 
              time.strftime("%c", time.localtime(ts)))
    modes = irc.channels[channel].modes
    uids = []
    changedmodes = []
    namelist = []
    # We take <users> as a list of (prefixmodes, uid) pairs.
    for userpair in users:
        assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
        prefixes, user = userpair
        prefixchars = ''.join([irc.prefixmodes[prefix] for prefix in prefixes])
        namelist.append(prefixchars+user)
        uids.append(user)
        for m in prefixes:
            changedmodes.append(('+%s' % m, user))
        try:
            irc.users[user].channels.add(channel)
        except KeyError:  # Not initialized yet?
            log.debug("(%s) sjoinServer: KeyError trying to add %r to %r's channel list?", irc.name, channel, user)
    utils.applyModes(irc, channel, changedmodes)
    namelist = ' '.join(namelist)
    _send(irc, server, "SJOIN {ts} {channel} {modes} :{users}".format(
            ts=ts, users=namelist, channel=channel,
            modes=utils.joinModes(modes)))
    irc.channels[channel].users.update(uids)

'''
def partClient(irc, client, channel, reason=None):
    channel = channel.lower()
    if not utils.isInternalClient(irc, client):
        log.error('(%s) Error trying to part client %r to %r (no such pseudoclient exists)', irc.name, client, channel)
        raise LookupError('No such PyLink PseudoClient exists.')
    msg = "PART %s" % channel
    if reason:
        msg += " :%s" % reason
    _send(irc, client, msg)
    handle_part(irc, client, 'PART', [channel])

def removeClient(irc, numeric):
    """<irc object> <client numeric>

    Removes a client from our internal databases, regardless
    of whether it's one of our pseudoclients or not."""
    for v in irc.channels.values():
        v.removeuser(numeric)
    sid = numeric[:3]
    log.debug('Removing client %s from irc.users', numeric)
    del irc.users[numeric]
    log.debug('Removing client %s from irc.servers[%s]', numeric, sid)
    irc.servers[sid].users.remove(numeric)

def quitClient(irc, numeric, reason):
    """<irc object> <client numeric>

    Quits a PyLink PseudoClient."""
    if utils.isInternalClient(irc, numeric):
        _send(irc, numeric, "QUIT :%s" % reason)
        removeClient(irc, numeric)
    else:
        raise LookupError("No such PyLink PseudoClient exists. If you're trying to remove "
                          "a user that's not a PyLink PseudoClient from "
                          "the internal state, use removeClient() instead.")

def _sendKick(irc, numeric, channel, target, reason=None):
    """<irc object> <kicker client numeric>

    Sends a kick from a PyLink PseudoClient."""
    channel = channel.lower()
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
'''

def _sendModes(irc, numeric, target, modes, ts=None):
    utils.applyModes(irc, target, modes)
    if utils.isChannel(target):
        ts = ts or irc.channels[target.lower()].ts
        # TMODE:
        # parameters: channelTS, channel, cmode changes, opt. cmode parameters...
        
        # On output, at most ten cmode parameters should be sent; if there are more,
        # multiple TMODE messages should be sent.
        while modes[:10]:
            joinedmodes = utils.joinModes(modes[:10])
            _send(irc, numeric, 'TMODE %s %s %s' % (target, ts, joinedmodes))
    else:
        joinedmodes = utils.joinModes(modes)
        _send(irc, numeric, 'MODE %s %s' % (target, joinedmodes))

def modeClient(irc, numeric, target, modes, ts=None):
    """<irc object> <client numeric> <list of modes>

    Sends modes from a PyLink PseudoClient. <list of modes> should be
    a list of (mode, arg) tuples, in the format of utils.parseModes() output.
    """
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _sendModes(irc, numeric, target, modes, ts=ts)

def modeServer(irc, numeric, target, modes, ts=None):
    """<irc object> <server SID> <list of modes>

    Sends modes from a PyLink PseudoServer. <list of modes> should be
    a list of (mode, arg) tuples, in the format of utils.parseModes() output.
    """
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    _sendModes(irc, numeric, target, modes, ts=ts)

def killServer(irc, numeric, target, reason):
    """<irc object> <server SID> <target> <reason>

    Sends a kill to <target> from a PyLink PseudoServer.
    """
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    # KILL:
    # parameters: target user, path

    # The format of the path parameter is some sort of description of the source of
    # the kill followed by a space and a parenthesized reason. To avoid overflow,
    # it is recommended not to add anything to the path.

    _send(irc, numeric, 'KILL %s :Killed (%s)' % (target, reason))
    removeClient(irc, target)

def killClient(irc, numeric, target, reason):
    """<irc object> <client numeric> <target> <reason>

    Sends a kill to <target> from a PyLink PseudoClient.
    """
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'KILL %s :Killed (%s)' % (target, reason))
    removeClient(irc, target)

'''
def messageClient(irc, numeric, target, text):
    """<irc object> <client numeric> <text>

    Sends PRIVMSG <text> from PyLink client <client numeric>."""
    # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L649
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
'''
def topicServer(irc, numeric, target, text):
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    # TB
    # capab: TB
    # source: server
    # propagation: broadcast
    # parameters: channel, topicTS, opt. topic setter, topic
    ts = int(time.time())
    servername = irc.servers[numeric].name
    _send(irc, numeric, 'TB %s %s %s :%s' % (target, ts, servername, text))

def inviteClient(irc, numeric, target, channel):
    """<irc object> <client numeric> <text>

    Invites <target> to <channel> to <text> from PyLink client <client numeric>."""
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'INVITE %s %s %s' % (target, channel, irc.channels[channel].ts))

def knockClient(irc, numeric, target, text):
    """<irc object> <client numeric> <text>

    Knocks on <channel> with <text> from PyLink client <client numeric>."""
    if 'KNOCK' not in irc.caps:
        log.debug('(%s) knockClient: Dropping KNOCK to %r since the IRCd '
                  'doesn\'t support it.', irc.name, target)
        return
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    # No text value is supported here; drop it.
    _send(irc, numeric, 'KNOCK %s' % target)

def updateClient(irc, numeric, field, text):
    """<irc object> <client numeric> <field> <text>

    Changes the <field> field of <target> PyLink PseudoClient <client numeric>."""
    field = field.upper()
    if field == 'HOST':
        handle_chghost(irc, numeric, 'PYLINK_UPDATECLIENT_HOST', [text])
        _send(irc, irc.sid, 'CHGHOST %s :%s' % (numeric, text))
    else:
        raise NotImplementedError("Changing field %r of a client is unsupported by this protocol." % field)

def pingServer(irc, source=None, target=None):
    source = source or irc.sid
    if source is None:
        return
    if target is not None:
        _send(irc, source, 'PING %s %s' % (source, target))
    else:
        _send(irc, source, 'PING %s' % source)

def connect(irc):
    ts = irc.start_ts
    irc.uidgen = {}

    f = irc.send

    # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L55
    f('PASS %s TS 6 %s' % (irc.serverdata["sendpass"], irc.sid))

    # We request the following capabilities (for charybdis):

    # QS: SQUIT doesn't send recursive quits for each users; required
    # by charybdis (Source: https://github.com/grawity/irc-docs/blob/master/server/ts-capab.txt)

    # ENCAP: message encapsulation for certain commands, only because
    # charybdis requires it to link

    # EX: Support for ban exemptions (+e)
    # IE: Support for invite exemptions (+e)
    # CHW: Allow sending messages to @#channel and the like.
    # KNOCK: support for /knock
    # SAVE: support for SAVE (forces user to UID in nick collision)
    # SERVICES: adds mode +r (only registered users can join a channel)
    # TB: topic burst command; we send this in topicServer
    # EUID: extended UID command, which includes real hostname + account data info,
    #       and allows sending CHGHOST without ENCAP.
    f('CAPAB :QS ENCAP EX CHW IE KNOCK SAVE SERVICES TB EUID')

    f('SERVER %s 0 :PyLink Service' % irc.serverdata["hostname"])

def handle_ping(irc, source, command, args):
    # PING:
    # source: any
    # parameters: origin, opt. destination server
    # PONG:
    # source: server
    # parameters: origin, destination

    # Sends a PING to the destination server, which will reply with a PONG. If the
    # destination server parameter is not present, the server receiving the message
    # must reply.
    try:
        destination = args[1]
    except IndexError:
        destination = irc.sid
    if utils.isInternalServer(irc, destination):
        _send(irc, destination, 'PONG %s %s' % (destination, source))

def handle_pong(irc, source, command, args):
    if source == irc.uplink:
        irc.lastping = time.time()

'''
def handle_privmsg(irc, source, command, args):
    return {'target': args[0], 'text': args[1]}

def handle_kill(irc, source, command, args):
    killed = args[0]
    data = irc.users[killed]
    removeClient(irc, killed)
    return {'target': killed, 'text': args[1], 'userdata': data}

def handle_kick(irc, source, command, args):
    # :70MAAAAAA KICK #endlessvoid 70MAAAAAA :some reason
    channel = args[0].lower()
    kicked = args[1]
    handle_part(irc, kicked, 'KICK', [channel, args[2]])
    return {'channel': channel, 'target': kicked, 'text': args[2]}
'''

def handle_part(irc, source, command, args):
    channels = args[0].lower().split(',')
    # We should only get PART commands for channels that exist, right??
    for channel in channels:
        irc.channels[channel].removeuser(source)
        try:
            irc.users[source].channels.discard(channel)
        except KeyError:
            log.debug("(%s) handle_part: KeyError trying to remove %r from %r's channel list?", irc.name, channel, source)
        try:
            reason = args[1]
        except IndexError:
            reason = ''
    return {'channels': channels, 'text': reason}

'''
def handle_error(irc, numeric, command, args):
    irc.connected = False
    raise ProtocolError('Received an ERROR, killing!')
'''

def handle_sjoin(irc, servernumeric, command, args):
    # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist
    channel = args[1].lower()
    userlist = args[-1].split()
    our_ts = irc.channels[channel].ts
    their_ts = int(args[0])
    if their_ts < our_ts:
        # Channel timestamp was reset on burst
        log.debug('(%s) Setting channel TS of %s to %s from %s',
                  irc.name, channel, their_ts, our_ts)
        irc.channels[channel].ts = their_ts
    modestring = args[2:-1] or args[2]
    parsedmodes = utils.parseModes(irc, channel, modestring)
    utils.applyModes(irc, channel, parsedmodes)
    namelist = []
    for user in userlist:
        # charybdis sends this in the form "@+UID1, +UID2, UID3, @UID4"
        modeprefix = ''
        r = re.search(r'([%s]*)(.*)' % ''.join(irc.prefixmodes.values()), user)
        user = r.group(2)
        for m in r.group(1):
            # Iterate over the mapping of prefix chars to prefixes, and
            # find the characters that match.
            for char, prefix in irc.prefixmodes.items():
                if m == prefix:
                    modeprefix += char
        namelist.append(user)
        irc.users[user].channels.add(channel)
        utils.applyModes(irc, channel, [('+%s' % mode, user) for mode in modeprefix])
        irc.channels[channel].users.add(user)
    return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts}

def handle_join(irc, numeric, command, args):
    # parameters: channelTS, channel, '+' (a plus sign)
    ts = int(args[0])
    if args[0] == '0':
        # /join 0; part the user from all channels
        oldchans = list(irc.users[numeric].channels)
        for channel in irc.users[numeric].channels:
            irc.channels[channel].discard(numeric)
        irc.users[numeric].channels = set()
        return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
    else:
        channel = args[1].lower()
        irc.channels[channel].add(numeric)
        irc.users[numeric].channels.add(numeric)
    # We send users and modes here because SJOIN and JOIN both use one hook,
    # for simplicity's sake (with plugins).
    return {'channel': channel, 'users': [numeric], 'modes':
            irc.channels[channel].modes, 'ts': ts}

def handle_euid(irc, numeric, command, args):
    # <- :42X EUID GL 1 1437448431 +ailoswz ~gl 0::1 0::1 42XAAAAAB real hostname, account name :realname
    nick = args[0]
    ts, modes, ident, host, ip, uid, realhost = args[2:9]
    realname = [-1]
    irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
    parsedmodes = utils.parseModes(irc, uid, [modes])
    log.debug('Applying modes %s for %s', parsedmodes, uid)
    utils.applyModes(irc, uid, parsedmodes)
    irc.servers[numeric].users.append(uid)
    return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

'''
def handle_quit(irc, numeric, command, args):
    # <- :1SRAAGB4T QUIT :Quit: quit message goes here
    removeClient(irc, numeric)
    return {'text': args[0]}

def handle_server(irc, numeric, command, args):
    # SERVER is sent by our uplink or any other server to introduce others.
    # <- :00A SERVER test.server * 1 00C :testing raw message syntax
    # <- :70M SERVER millennium.overdrive.pw * 1 1ML :a relatively long period of time... (Fremont, California)
    servername = args[0].lower()
    sid = args[3]
    sdesc = args[-1]
    irc.servers[sid] = IrcServer(numeric, servername)
    return {'name': servername, 'sid': args[3], 'text': sdesc}
'''

# XXX This is where I left off.

def handle_nick(irc, numeric, command, args):
    # <- :70MAAAAAA NICK GL-devel 1434744242
    oldnick = irc.users[numeric].nick
    newnick = irc.users[numeric].nick = args[0]
    return {'newnick': newnick, 'oldnick': oldnick, 'ts': int(args[1])}

def handle_save(irc, numeric, command, args):
    # This is used to handle nick collisions. Here, the client Derp_ already exists,
    # so trying to change nick to it will cause a nick collision. On InspIRCd,
    # this will simply set the collided user's nick to its UID.

    # <- :70MAAAAAA PRIVMSG 0AL000001 :nickclient PyLink Derp_
    # -> :0AL000001 NICK Derp_ 1433728673
    # <- :70M SAVE 0AL000001 1433728673
    user = args[0]
    irc.users[user].nick = user
    return {'target': user, 'ts': int(args[1])}

def handle_fmode(irc, numeric, command, args):
    # <- :70MAAAAAA FMODE #chat 1433653462 +hhT 70MAAAAAA 70MAAAAAD
    channel = args[0].lower()
    modes = args[2:]
    changedmodes = utils.parseModes(irc, channel, modes)
    utils.applyModes(irc, channel, changedmodes)
    ts = int(args[1])
    return {'target': channel, 'modes': changedmodes, 'ts': ts}

def handle_mode(irc, numeric, command, args):
    # In InspIRCd, MODE is used for setting user modes and
    # FMODE is used for channel modes:
    # <- :70MAAAAAA MODE 70MAAAAAA -i+xc
    target = args[0]
    modestrings = args[1:]
    changedmodes = utils.parseModes(irc, numeric, modestrings)
    utils.applyModes(irc, target, changedmodes)
    return {'target': target, 'modes': changedmodes}

def handle_squit(irc, numeric, command, args):
    # :70M SQUIT 1ML :Server quit by GL!gl@0::1
    split_server = args[0]
    affected_users = []
    log.info('(%s) Netsplit on server %s', irc.name, split_server)
    # Prevent RuntimeError: dictionary changed size during iteration
    old_servers = copy(irc.servers)
    for sid, data in old_servers.items():
        if data.uplink == split_server:
            log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
            args = handle_squit(irc, sid, 'SQUIT', [sid, "PyLink: Automatically splitting leaf servers of %s" % sid])
            affected_users += args['users']
    for user in copy(irc.servers[split_server].users):
        affected_users.append(user)
        log.debug('Removing client %s (%s)', user, irc.users[user].nick)
        removeClient(irc, user)
    del irc.servers[split_server]
    log.debug('(%s) Netsplit affected users: %s', irc.name, affected_users)
    return {'target': split_server, 'users': affected_users}

def handle_rsquit(irc, numeric, command, args):
    # <- :1MLAAAAIG RSQUIT :ayy.lmao
    # <- :1MLAAAAIG RSQUIT ayy.lmao :some reason
    # RSQUIT is sent by opers to squit remote servers.
    # Strangely, it takes a server name instead of a SID, and is
    # allowed to be ignored entirely.
    # If we receive a remote SQUIT, split the target server
    # ONLY if the sender is identified with us.
    target = args[0]
    for (sid, server) in irc.servers.items():
        if server.name == target:
            target = sid
    if utils.isInternalServer(irc, target):
        if irc.users[numeric].identified:
            uplink = irc.servers[target].uplink
            reason = 'Requested by %s' % irc.users[numeric].nick
            _send(irc, uplink, 'SQUIT %s :%s' % (target, reason))
            return handle_squit(irc, numeric, 'SQUIT', [target, reason])
        else:
            utils.msg(irc, numeric, 'Error: you are not authorized to split servers!', notice=True)

def handle_idle(irc, numeric, command, args):
    """Handle the IDLE command, sent between servers in remote WHOIS queries."""
    # <- :70MAAAAAA IDLE 1MLAAAAIG
    # -> :1MLAAAAIG IDLE 70MAAAAAA 1433036797 319
    sourceuser = numeric
    targetuser = args[0]
    _send(irc, targetuser, 'IDLE %s %s 0' % (sourceuser, irc.users[targetuser].ts))

def handle_events(irc, data):
    # TS6 messages:
    # :42X COMMAND arg1 arg2 :final long arg
    # :42XAAAAAA PRIVMSG #somewhere :hello!
    args = data.split()
    if not args:
        # No data??
        return
    if args[0] == 'PASS':
        # <- PASS $somepassword TS 6 :42X
        if args[1] != irc.serverdata['recvpass']:
            # Check if recvpass is correct
            raise ProtocolError('Error: recvpass from uplink server %s does not match configuration!' % servername)
        if 'TS 6' not in data:
            raise ProtocolError("Remote protocol version is too old! Is this even TS6?")
        # Server name and SID are sent in different messages, grr
        numeric = data.rsplit(':', 1)[1]
        log.debug('(%s) Found uplink SID as %r', irc.name, numeric)
        irc.servers[numeric] = IrcServer(None, 'unknown')
        irc.uplink = numeric
        return
    elif args[0] == 'SERVER':
        # <- SERVER charybdis.midnight.vpn 1 :charybdis test server
        sname = args[1].lower()
        log.debug('(%s) Found uplink server name as %r', irc.name, sname)
        irc.servers[irc.uplink].name = sname
    elif args[0] == 'CAPAB':
        # We only get a list of keywords here. Charybdis obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :BAN CHW CLUSTER ENCAP EOPMOD EUID EX IE KLN KNOCK MLOCK QS RSFNC SAVE SERVICES TB UNKLN
        irc.caps = caps = data.split(':', 1)[1].split()
        for required_cap in ('EUID', 'SAVE', 'TB', 'ENCAP'):
            if required_cap not in caps:
                raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

        # Valid keywords (from mostly InspIRCd's named modes):
        # admin allowinvite autoop ban banexception blockcolor
        # c_registered exemptchanops filter forward flood halfop history invex
        # inviteonly joinflood key kicknorejoin limit moderated nickflood
        # noctcp noextmsg nokick noknock nonick nonotice official-join op
        # operonly opmoderated owner permanent private redirect regonly
        # regmoderated secret sslonly stripcolor topiclock voice

        # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L80
        chary_cmodes = { # TS6 generic modes:
                        'op': 'o', 'voice': 'v', 'ban': 'b', 'key': 'k', 'limit':
                        'l', 'moderated': 'm', 'noextmsg': 'n', 'noknock': 'p',
                        'secret': 's', 'topiclock': 't',
                         # charybdis-specific modes:
                         'quiet': 'q', 'redirect': 'f', 'freetarget': 'F',
                         'joinflood': 'j', 'largebanlist': 'L', 'permanent': 'P',
                         'c_noforwards': 'Q', 'stripcolor': 'c', 'allowinvite':
                         'g', 'opmoderated': 'z',
                         # Now, map all the ABCD type modes:
                         '*A': 'beI', '*B': 'k', '*C': 'l', '*D': 'mnprst'}
        if 'EX' in caps:
            chary_cmodes['banexception'] = 'e'
        if 'IE' in caps:
            chary_cmodes['invex'] = 'I'
        if 'SERVICES' in caps:
            chary_cmodes['regonly'] = 'r'

        irc.cmodes.update(chary_cmodes)

        # Same thing with umodes:
        # bot callerid cloak deaf_commonchan helpop hidechans hideoper invisible oper regdeaf servprotect showwhois snomask u_registered u_stripcolor wallops
        chary_umodes = {'deaf': 'D', 'servprotect': 'S', 'u_admin': 'a',
                        'invisible': 'i', 'oper': 'o', 'wallops': 'w',
                        'snomask': 's', 'u_noforward': 'Q', 'regdeaf': 'R',
                        'callerid': 'g', 'chary_operwall': 'z', 'chary_locops':
                        'l',
                         # Now, map all the ABCD type modes:
                         '*A': '', '*B': '', '*C': '', '*D': 'DSAiowQRglszZ'}
        irc.umodes.update(chary_umodes)
        # TODO: support module-created modes like +O, +S, etc.
        # Does charybdis propagate these? If so, how?
        irc.connected.set()
    try:
        real_args = []
        for arg in args:
            real_args.append(arg)
            # If the argument starts with ':' and ISN'T the first argument.
            # The first argument is used for denoting the source UID/SID.
            if arg.startswith(':') and args.index(arg) != 0:
                # : is used for multi-word arguments that last until the end
                # of the message. We can use list splicing here to turn them all
                # into one argument.
                index = args.index(arg)  # Get the array index of the multi-word arg
                # Set the last arg to a joined version of the remaining args
                arg = args[index:]
                arg = ' '.join(arg)[1:]
                # Cut the original argument list right before the multi-word arg,
                # and then append the multi-word arg.
                real_args = args[:index]
                real_args.append(arg)
                break
        real_args[0] = real_args[0].split(':', 1)[1]
        args = real_args

        numeric = args[0]
        command = args[1]
        args = args[2:]
    except IndexError:
        return

    # We will do wildcard event handling here. Unhandled events are just ignored.
    try:
        func = globals()['handle_'+command.lower()]
    except KeyError:  # unhandled event
        pass
    else:
        parsed_args = func(irc, numeric, command, args)
        if parsed_args is not None:
            return [numeric, command, parsed_args]

def spawnServer(irc, name, sid=None, uplink=None, desc='PyLink Server', endburst=True):
    # -> :0AL SERVER test.server * 1 0AM :some silly pseudoserver
    uplink = uplink or irc.sid
    name = name.lower()
    if sid is None:  # No sid given; generate one!
        irc.sidgen = utils.TS6SIDGenerator(irc.serverdata["sidrange"])
        sid = irc.sidgen.next_sid()
    assert len(sid) == 3, "Incorrect SID length"
    if sid in irc.servers:
        raise ValueError('A server with SID %r already exists!' % sid)
    for server in irc.servers.values():
        if name == server.name:
            raise ValueError('A server named %r already exists!' % name)
    if not utils.isInternalServer(irc, uplink):
        raise ValueError('Server %r is not a PyLink internal PseudoServer!' % uplink)
    if not utils.isServerName(name):
        raise ValueError('Invalid server name %r' % name)
    _send(irc, uplink, 'SERVER %s * 1 %s :%s' % (name, sid, desc))
    irc.servers[sid] = IrcServer(uplink, name, internal=True)
    if endburst:
        endburstServer(irc, sid)
    return sid

def endburstServer(irc, sid):
    _send(irc, sid, 'ENDBURST')
    irc.servers[sid].has_bursted = True

def handle_ftopic(irc, numeric, command, args):
    # <- :70M FTOPIC #channel 1434510754 GLo|o|!GLolol@escape.the.dreamland.ca :Some channel topic
    channel = args[0].lower()
    ts = args[1]
    setter = args[2]
    topic = args[-1]
    irc.channels[channel].topic = topic
    irc.channels[channel].topicset = True
    return {'channel': channel, 'setter': setter, 'ts': ts, 'topic': topic}

def handle_topic(irc, numeric, command, args):
    # <- :70MAAAAAA TOPIC #test :test
    channel = args[0].lower()
    topic = args[1]
    ts = int(time.time())
    irc.channels[channel].topic = topic
    irc.channels[channel].topicset = True
    return {'channel': channel, 'setter': numeric, 'ts': ts, 'topic': topic}

def handle_invite(irc, numeric, command, args):
    # <- :70MAAAAAC INVITE 0ALAAAAAA #blah 0
    target = args[0]
    channel = args[1].lower()
    # We don't actually need to process this; it's just something plugins/hooks can use
    return {'target': target, 'channel': channel}

def handle_encap(irc, numeric, command, args):
    # <- :70MAAAAAA ENCAP * KNOCK #blah :agsdfas
    # From charybdis TS6 docs: https://github.com/grawity/irc-docs/blob/03ba884a54f1cef2193cd62b6a86803d89c1ac41/server/ts6.txt

    # ENCAP
    # source: any
    # parameters: target server mask, subcommand, opt. parameters...

    # Sends a command to matching servers. Propagation is independent of
    # understanding the subcommand.

    targetmask = args[0]
    real_command = args[1]
    if targetmask == '*' and real_command == 'KNOCK':
        channel = args[2].lower()
        text = args[3]
        return {'encapcommand': real_command, 'channel': channel,
                'text': text}

def handle_notice(irc, numeric, command, args):
    # <- :70MAAAAAA NOTICE #dev :afasfsa
    # <- :70MAAAAAA NOTICE 0ALAAAAAA :afasfsa
    return {'target': args[0], 'text': args[1]}

def handle_opertype(irc, numeric, command, args):
    # This is used by InspIRCd to denote an oper up; there is no MODE
    # command sent for it.
    # <- :70MAAAAAB OPERTYPE Network_Owner
    omode = [('+o', None)]
    utils.applyModes(irc, numeric, omode)
    return {'target': numeric, 'modes': omode}

def handle_fident(irc, numeric, command, args):
    # :70MAAAAAB FHOST test
    # :70MAAAAAB FNAME :afdsafasf
    # :70MAAAAAB FIDENT test
    irc.users[numeric].ident = newident = args[0]
    return {'target': numeric, 'newident': newident}

def handle_fhost(irc, numeric, command, args):
    irc.users[numeric].host = newhost = args[0]
    return {'target': numeric, 'newhost': newhost}

def handle_fname(irc, numeric, command, args):
    irc.users[numeric].realname = newgecos = args[0]
    return {'target': numeric, 'newgecos': newgecos}

def handle_endburst(irc, numeric, command, args):
    return {}
