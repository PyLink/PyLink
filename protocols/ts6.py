import time
import sys
import os
import re

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log

from classes import *
# Shared with inspircd module because the output is the same.
from inspircd import nickClient, kickServer, kickClient, _sendKick, quitClient, \
    removeClient, partClient, messageClient, noticeClient, topicClient
from inspircd import handle_privmsg, handle_kill, handle_kick, handle_error, \
    handle_quit, handle_nick, handle_save, handle_squit, handle_mode, handle_topic, \
    handle_notice

casemapping = 'rfc1459'
hook_map = {'SJOIN': 'JOIN', 'TB': 'TOPIC', 'TMODE': 'MODE', 'BMASK': 'MODE'}

def _send(irc, sid, msg):
    irc.send(':%s %s' % (sid, msg))

def spawnClient(irc, nick, ident='null', host='null', realhost=None, modes=set(),
        server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None):
    server = server or irc.sid
    if not utils.isInternalServer(irc, server):
        raise ValueError('Server %r is not a PyLink internal PseudoServer!' % server)
    # We need a separate UID generator instance for every PseudoServer
    # we spawn. Otherwise, things won't wrap around properly.
    if server not in irc.uidgen:
        irc.uidgen[server] = utils.TS6UIDGenerator(server)
    uid = irc.uidgen[server].next_uid()
    # EUID:
    # parameters: nickname, hopcount, nickTS, umodes, username,
    # visible hostname, IP address, UID, real hostname, account name, gecos
    ts = ts or int(time.time())
    realname = realname or irc.botdata['realname']
    realhost = realhost or host
    raw_modes = utils.joinModes(modes)
    u = irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
        realhost=realhost, ip=ip)
    utils.applyModes(irc, uid, modes)
    irc.servers[server].users.append(uid)
    _send(irc, server, "EUID {nick} 1 {ts} {modes} {ident} {host} {ip} {uid} "
            "{realhost} * :{realname}".format(ts=ts, host=host,
            nick=nick, ident=ident, uid=uid,
            modes=raw_modes, ip=ip, realname=realname,
            realhost=realhost))
    return u

def joinClient(irc, client, channel):
    channel = utils.toLower(irc, channel)
    # JOIN:
    # parameters: channelTS, channel, '+' (a plus sign)
    if not utils.isInternalClient(irc, client):
        log.error('(%s) Error trying to join client %r to %r (no such pseudoclient exists)', irc.name, client, channel)
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, client, "JOIN {ts} {channel} +".format(ts=irc.channels[channel].ts, channel=channel))
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
    channel = utils.toLower(irc, channel)
    server = server or irc.sid
    assert users, "sjoinServer: No users sent?"
    log.debug('(%s) sjoinServer: got %r for users', irc.name, users)
    if not server:
        raise LookupError('No such PyLink PseudoClient exists.')
    orig_ts = irc.channels[channel].ts
    ts = ts or orig_ts
    if ts < orig_ts:
        # If the TS we're sending is lower than the one that existing, clear the
        # mode lists from our channel state and reset the timestamp.
        log.debug('(%s) sjoinServer: resetting TS of %r from %s to %s (clearing modes)',
                  irc.name, channel, orig_ts, ts)
        irc.channels[channel].ts = ts
        irc.channels[channel].modes.clear()
        for p in irc.channels[channel].prefixmodes.values():
            p.clear()
    log.debug("sending SJOIN to %s%s with ts %s (that's %r)", channel, irc.name, ts,
              time.strftime("%c", time.localtime(ts)))
    modes = [m for m in irc.channels[channel].modes if m[0] not in irc.cmodes['*A']]
    changedmodes = []
    while users[:10]:
        uids = []
        namelist = []
        # We take <users> as a list of (prefixmodes, uid) pairs.
        for userpair in users[:10]:
            assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
            prefixes, user = userpair
            prefixchars = ''
            for prefix in prefixes:
                pr = irc.prefixmodes.get(prefix)
                if pr:
                    prefixchars += pr
                    changedmodes.append(('+%s' % prefix, user))
            namelist.append(prefixchars+user)
            uids.append(user)
            try:
                irc.users[user].channels.add(channel)
            except KeyError:  # Not initialized yet?
                log.debug("(%s) sjoinServer: KeyError trying to add %r to %r's channel list?", irc.name, channel, user)
        users = users[10:]
        namelist = ' '.join(namelist)
        _send(irc, server, "SJOIN {ts} {channel} {modes} :{users}".format(
                ts=ts, users=namelist, channel=channel,
                modes=utils.joinModes(modes)))
        irc.channels[channel].users.update(uids)
    if ts <= orig_ts:
       # Only save our prefix modes in the channel state if our TS is lower than or equal to theirs.
        utils.applyModes(irc, channel, changedmodes)

def _sendModes(irc, numeric, target, modes, ts=None):
    utils.applyModes(irc, target, modes)
    if utils.isChannel(target):
        ts = ts or irc.channels[utils.toLower(irc, target)].ts
        # TMODE:
        # parameters: channelTS, channel, cmode changes, opt. cmode parameters...

        # On output, at most ten cmode parameters should be sent; if there are more,
        # multiple TMODE messages should be sent.
        while modes[:9]:
            joinedmodes = utils.joinModes(modes = [m for m in modes[:9] if m[0] not in irc.cmodes['*A']])
            modes = modes[9:]
            _send(irc, numeric, 'TMODE %s %s %s' % (ts, target, joinedmodes))
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

    assert target in irc.users, "Unknown target %r for killServer!" % target
    _send(irc, numeric, 'KILL %s :Killed (%s)' % (target, reason))
    removeClient(irc, target)

def killClient(irc, numeric, target, reason):
    """<irc object> <client numeric> <target> <reason>

    Sends a kill to <target> from a PyLink PseudoClient.
    """
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    assert target in irc.users, "Unknown target %r for killClient!" % target
    _send(irc, numeric, 'KILL %s :Killed (%s)' % (target, reason))
    removeClient(irc, target)

def topicServer(irc, numeric, target, text):
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    # TB
    # capab: TB
    # source: server
    # propagation: broadcast
    # parameters: channel, topicTS, opt. topic setter, topic
    ts = irc.channels[target].ts
    servername = irc.servers[numeric].name
    _send(irc, numeric, 'TB %s %s %s :%s' % (target, ts, servername, text))
    irc.channels[target].topic = text
    irc.channels[target].topicset = True

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
        irc.users[numeric].host = text
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

def numericServer(irc, source, numeric, target, text):
    _send(irc, source, '%s %s %s' % (numeric, target, text))

def awayClient(irc, source, text):
    """<irc object> <numeric> <text>

    Sends an AWAY message with text <text> from PyLink client <numeric>.
    <text> can be an empty string to unset AWAY status."""
    if text:
        _send(irc, source, 'AWAY :%s' % text)
    else:
        _send(irc, source, 'AWAY')

def connect(irc):
    ts = irc.start_ts

    f = irc.send
    # Valid keywords (from mostly InspIRCd's named modes):
    # admin allowinvite autoop ban banexception blockcolor
    # c_registered exemptchanops filter forward flood halfop history invex
    # inviteonly joinflood key kicknorejoin limit moderated nickflood
    # noctcp noextmsg nokick noknock nonick nonotice official-join op
    # operonly opmoderated owner permanent private redirect regonly
    # regmoderated secret sslonly stripcolor topiclock voice

    # https://github.com/grawity/irc-docs/blob/master/server/ts6.txt#L80
    chary_cmodes = { # TS6 generic modes:
                     # Note: charybdis +p has the effect of being both
                     # noknock AND private. Surprisingly, mapping it twice
                     # works pretty well: setting +p on a charybdis relay
                     # server sets +pK on an InspIRCd network.
                    'op': 'o', 'voice': 'v', 'ban': 'b', 'key': 'k', 'limit':
                    'l', 'moderated': 'm', 'noextmsg': 'n', 'noknock': 'p',
                    'secret': 's', 'topiclock': 't',
                     # charybdis-specific modes:
                    'quiet': 'q', 'redirect': 'f', 'freetarget': 'F',
                    'joinflood': 'j', 'largebanlist': 'L', 'permanent': 'P',
                    'c_noforwards': 'Q', 'stripcolor': 'c', 'allowinvite':
                    'g', 'opmoderated': 'z', 'noctcp': 'C',
                     # charybdis-specific modes provided by EXTENSIONS
                    'operonly': 'O', 'adminonly': 'A', 'sslonly': 'S',
                     # Now, map all the ABCD type modes:
                    '*A': 'beIq', '*B': 'k', '*C': 'l', '*D': 'mnprst'}

    if irc.serverdata.get('use_owner'):
        chary_cmodes['owner'] = 'y'
        irc.prefixmodes['y'] = '~'
    if irc.serverdata.get('use_admin'):
        chary_cmodes['admin'] = 'a'
        irc.prefixmodes['a'] = '!'
    if irc.serverdata.get('use_halfop'):
        chary_cmodes['halfop'] = 'h'
        irc.prefixmodes['h'] = '%'

    irc.cmodes.update(chary_cmodes)

    # Same thing with umodes:
    # bot callerid cloak deaf_commonchan helpop hidechans hideoper invisible oper regdeaf servprotect showwhois snomask u_registered u_stripcolor wallops
    chary_umodes = {'deaf': 'D', 'servprotect': 'S', 'u_admin': 'a',
                    'invisible': 'i', 'oper': 'o', 'wallops': 'w',
                    'snomask': 's', 'u_noforward': 'Q', 'regdeaf': 'R',
                    'callerid': 'g', 'chary_operwall': 'z', 'chary_locops':
                    'l',
                     # Now, map all the ABCD type modes:
                     '*A': '', '*B': '', '*C': '', '*D': 'DSaiowsQRgzl'}
    irc.umodes.update(chary_umodes)

    # Toggles support of shadowircd/elemental-ircd specific channel modes:
    # +T (no notice), +u (hidden ban list), +E (no kicks), +J (blocks kickrejoin),
    # +K (no repeat messages), +d (no nick changes), and user modes:
    # +B (bot), +C (blocks CTCP), +D (deaf), +V (no invites), +I (hides channel list)
    if irc.serverdata.get('use_elemental_modes'):
        elemental_cmodes = {'nonotice': 'T', 'hiddenbans': 'u', 'nokick': 'E',
                            'kicknorejoin': 'J', 'repeat': 'K', 'nonick': 'd'}
        irc.cmodes.update(elemental_cmodes)
        irc.cmodes['*D'] += ''.join(elemental_cmodes.values())
        elemental_umodes = {'u_noctcp': 'C', 'deaf': 'D', 'bot': 'B', 'u_noinvite': 'V',
                            'hidechans': 'I'}
        irc.umodes.update(elemental_umodes)
        irc.umodes['*D'] += ''.join(elemental_umodes.values())

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

    f('SERVER %s 0 :%s' % (irc.serverdata["hostname"],
                           irc.serverdata.get('serverdesc') or irc.botdata['serverdesc']))

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

def handle_part(irc, source, command, args):
    channels = utils.toLower(irc, args[0]).split(',')
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
        if not (irc.channels[channel].users or ((irc.cmodes.get('permanent'), None) in irc.channels[channel].modes)):
            del irc.channels[channel]
    return {'channels': channels, 'text': reason}

def handle_sjoin(irc, servernumeric, command, args):
    # parameters: channelTS, channel, simple modes, opt. mode parameters..., nicklist
    channel = utils.toLower(irc, args[1])
    userlist = args[-1].split()
    our_ts = irc.channels[channel].ts
    their_ts = int(args[0])
    if their_ts < our_ts:
        # Channel timestamp was reset on burst
        log.debug('(%s) Setting channel TS of %s to %s from %s',
                  irc.name, channel, their_ts, our_ts)
        irc.channels[channel].ts = their_ts
        irc.channels[channel].modes.clear()
        for p in irc.channels[channel].prefixmodes.values():
            p.clear()
    modestring = args[2:-1] or args[2]
    parsedmodes = utils.parseModes(irc, channel, modestring)
    utils.applyModes(irc, channel, parsedmodes)
    namelist = []
    log.debug('(%s) handle_sjoin: got userlist %r for %r', irc.name, userlist, channel)
    for userpair in userlist:
        # charybdis sends this in the form "@+UID1, +UID2, UID3, @UID4"
        r = re.search(r'([^\d]*)(.*)', userpair)
        user = r.group(2)
        modeprefix = r.group(1) or ''
        finalprefix = ''
        assert user, 'Failed to get the UID from %r; our regex needs updating?' % userpair
        log.debug('(%s) handle_sjoin: got modeprefix %r for user %r', irc.name, modeprefix, user)
        for m in modeprefix:
            # Iterate over the mapping of prefix chars to prefixes, and
            # find the characters that match.
            for char, prefix in irc.prefixmodes.items():
                if m == prefix:
                    finalprefix += char
        namelist.append(user)
        irc.users[user].channels.add(channel)
        if their_ts <= our_ts:
            utils.applyModes(irc, channel, [('+%s' % mode, user) for mode in finalprefix])
        irc.channels[channel].users.add(user)
    return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts}

def handle_join(irc, numeric, command, args):
    # parameters: channelTS, channel, '+' (a plus sign)
    ts = int(args[0])
    if args[0] == '0':
        # /join 0; part the user from all channels
        oldchans = irc.users[numeric].channels.copy()
        log.debug('(%s) Got /join 0 from %r, channel list is %r',
                  irc.name, numeric, oldchans)
        for channel in oldchans:
            irc.channels[channel].users.discard(numeric)
            irc.users[numeric].channels.discard(channel)
        return {'channels': oldchans, 'text': 'Left all channels.', 'parse_as': 'PART'}
    else:
        channel = utils.toLower(irc, args[1])
        our_ts = irc.channels[channel].ts
        if ts < our_ts:
            # Channel timestamp was reset on burst
            log.debug('(%s) Setting channel TS of %s to %s from %s',
                      irc.name, channel, ts, our_ts)
            irc.channels[channel].ts = ts
        irc.channels[channel].users.add(numeric)
        irc.users[numeric].channels.add(channel)
    # We send users and modes here because SJOIN and JOIN both use one hook,
    # for simplicity's sake (with plugins).
    return {'channel': channel, 'users': [numeric], 'modes':
            irc.channels[channel].modes, 'ts': ts}

def handle_euid(irc, numeric, command, args):
    # <- :42X EUID GL 1 1437505322 +ailoswz ~gl 127.0.0.1 127.0.0.1 42XAAAAAB * * :realname
    nick = args[0]
    ts, modes, ident, host, ip, uid, realhost = args[2:9]
    if realhost == '*':
        realhost = None
    realname = args[-1]
    log.debug('(%s) handle_euid got args: nick=%s ts=%s uid=%s ident=%s '
              'host=%s realname=%s realhost=%s ip=%s', irc.name, nick, ts, uid,
              ident, host, realname, realhost, ip)

    irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
    parsedmodes = utils.parseModes(irc, uid, [modes])
    log.debug('Applying modes %s for %s', parsedmodes, uid)
    utils.applyModes(irc, uid, parsedmodes)
    irc.servers[numeric].users.append(uid)
    return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

def handle_uid(irc, numeric, command, args):
    raise ProtocolError("Servers must use EUID to send users! This is a "
                        "requested capability; plain UID (received) is not "
                        "handled by us at all!")

def handle_server(irc, numeric, command, args):
    # parameters: server name, hopcount, sid, server description
    servername = args[0].lower()
    try:
        sid = args[2]
    except IndexError:
        # It is allowed to send JUPEd servers that exist without a SID.
        # That's not very fun to handle, though.
        # XXX: don't just save these by their server names; that's ugly!
        sid = servername
    sdesc = args[-1]
    irc.servers[sid] = IrcServer(numeric, servername)
    return {'name': servername, 'sid': sid, 'text': sdesc}

handle_sid = handle_server

def handle_tmode(irc, numeric, command, args):
    # <- :42XAAAAAB TMODE 1437450768 #endlessvoid -c+lkC 3 agte4
    channel = utils.toLower(irc, args[1])
    modes = args[2:]
    changedmodes = utils.parseModes(irc, channel, modes)
    utils.applyModes(irc, channel, changedmodes)
    ts = int(args[0])
    return {'target': channel, 'modes': changedmodes, 'ts': ts}

def handle_events(irc, data):
    # TS6 messages:
    # :42X COMMAND arg1 arg2 :final long arg
    # :42XAAAAAA PRIVMSG #somewhere :hello!
    args = data.split(" ")
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
        # According to the TS6 protocol documentation, we should send SVINFO
        # when we get our uplink's SERVER command.
        irc.send('SVINFO 6 6 0 :%s' % int(time.time()))
    elif args[0] == 'SQUIT':
        # What? Charybdis send this in a different format!
        # <- SQUIT 00A :Remote host closed the connection
        split_server = args[1]
        res = handle_squit(irc, split_server, 'SQUIT', [split_server])
        irc.callHooks([split_server, 'SQUIT', res])
    elif args[0] == 'CAPAB':
        # We only get a list of keywords here. Charybdis obviously assumes that
        # we know what modes it supports (indeed, this is a standard list).
        # <- CAPAB :BAN CHW CLUSTER ENCAP EOPMOD EUID EX IE KLN KNOCK MLOCK QS RSFNC SAVE SERVICES TB UNKLN
        irc.caps = caps = data.split(':', 1)[1].split()
        for required_cap in ('EUID', 'SAVE', 'TB', 'ENCAP', 'QS'):
            if required_cap not in caps:
                raise ProtocolError('%s not found in TS6 capabilities list; this is required! (got %r)' % (required_cap, caps))

        if 'EX' in caps:
            irc.cmodes['banexception'] = 'e'
        if 'IE' in caps:
            irc.cmodes['invex'] = 'I'
        if 'SERVICES' in caps:
            irc.cmodes['regonly'] = 'r'

        log.debug('(%s) irc.connected set!', irc.name)
        irc.connected.set()

        # Charybdis doesn't have the idea of an explicit endburst; but some plugins
        # like relay require it to know that the network's connected.
        # We'll set a timer to manually call endburst. It's not beautiful,
        # but it's the best we can do.
        endburst_timer = threading.Timer(1, irc.callHooks, args=([irc.uplink, 'ENDBURST', {}],))
        log.debug('(%s) Starting delay to send ENDBURST', irc.name)
        endburst_timer.start()
    try:
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

def spawnServer(irc, name, sid=None, uplink=None, desc='PyLink Server'):
    # -> :0AL SID test.server 1 0XY :some silly pseudoserver
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
    _send(irc, uplink, 'SID %s 1 %s :%s' % (name, sid, desc))
    irc.servers[sid] = IrcServer(uplink, name, internal=True)
    return sid

def handle_tb(irc, numeric, command, args):
    # <- :42X TB 1434510754 #channel GLo|o|!GLolol@escape.the.dreamland.ca :Some channel topic
    channel = args[1].lower()
    ts = args[0]
    setter = args[2]
    topic = args[-1]
    irc.channels[channel].topic = topic
    irc.channels[channel].topicset = True
    return {'channel': channel, 'setter': setter, 'ts': ts, 'topic': topic}

def handle_invite(irc, numeric, command, args):
    # <- :70MAAAAAC INVITE 0ALAAAAAA #blah 12345
    target = args[0]
    channel = args[1].lower()
    try:
        ts = args[3]
    except IndexError:
        ts = int(time.time())
    # We don't actually need to process this; it's just something plugins/hooks can use
    return {'target': target, 'channel': channel}

def handle_chghost(irc, numeric, command, args):
    target = args[0]
    irc.users[target].host = newhost = args[1]
    return {'target': numeric, 'newhost': newhost}

def handle_bmask(irc, numeric, command, args):
    # <- :42X BMASK 1424222769 #dev b :*!test@*.isp.net *!badident@*
    # This is used for propagating bans, not TMODE!
    channel = args[1].lower()
    mode = args[2]
    ts = int(args[0])
    modes = []
    for ban in args[-1].split():
        modes.append(('+%s' % mode, ban))
    utils.applyModes(irc, channel, modes)
    return {'target': channel, 'modes': modes, 'ts': ts}

def handle_whois(irc, numeric, command, args):
    # <- :42XAAAAAB WHOIS 5PYAAAAAA :pylink-devel
    return {'target': args[0]}

def handle_472(irc, numeric, command, args):
    # <- :charybdis.midnight.vpn 472 GL|devel O :is an unknown mode char to me
    # 472 is sent to us when one of our clients tries to set a mode the server
    # doesn't support. In this case, we'll raise a warning to alert the user
    # about it.
    badmode = args[1]
    reason = args[-1]
    setter = args[0]
    charlist = {'A': 'chm_adminonly', 'O': 'chm_operonly', 'S': 'chm_sslonly'}
    if badmode in charlist:
        log.warning('(%s) User %r attempted to set channel mode %r, but the '
                    'extension providing it isn\'t loaded! To prevent possible'
                    ' desyncs, try adding the line "loadmodule "extensions/%s.so";" to '
                    'your IRCd configuration.', irc.name, setter, badmode,
                    charlist[badmode])

def handle_away(irc, numeric, command, args):
    # <- :6ELAAAAAB AWAY :Auto-away

    try:
        irc.users[numeric].away = text = args[0]
    except IndexError:  # User is unsetting away status
        irc.users[numeric].away = text = ''
    return {'text': text}

