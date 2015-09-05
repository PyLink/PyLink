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

from ts6_common import nickClient, kickServer, kickClient, _sendKick, quitClient, \
    removeClient, partClient, messageClient, noticeClient, topicClient, parseTS6Args
from ts6_common import handle_privmsg, handle_kill, handle_kick, handle_error, \
    handle_quit, handle_nick, handle_save, handle_squit, handle_mode, handle_topic, \
    handle_notice, _send, handle_part

casemapping = 'rfc1459'

# Raw commands sent from servers vary from protocol to protocol. Here, we map
# non-standard names to our hook handlers, so plugins get the information they need.

hook_map = {'FJOIN': 'JOIN', 'RSQUIT': 'SQUIT', 'FMODE': 'MODE',
            'FTOPIC': 'TOPIC', 'OPERTYPE': 'MODE', 'FHOST': 'CHGHOST',
            'FIDENT': 'CHGIDENT', 'FNAME': 'CHGNAME'}

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
    ts = ts or int(time.time())
    realname = realname or irc.botdata['realname']
    realhost = realhost or host
    raw_modes = utils.joinModes(modes)
    u = irc.users[uid] = IrcUser(nick, ts, uid, ident=ident, host=host, realname=realname,
        realhost=realhost, ip=ip)
    utils.applyModes(irc, uid, modes)
    irc.servers[server].users.add(uid)
    _send(irc, server, "UID {uid} {ts} {nick} {realhost} {host} {ident} {ip}"
                    " {ts} {modes} + :{realname}".format(ts=ts, host=host,
                                             nick=nick, ident=ident, uid=uid,
                                             modes=raw_modes, ip=ip, realname=realname,
                                             realhost=realhost))
    if ('o', None) in modes or ('+o', None) in modes:
        _operUp(irc, uid, opertype=opertype or 'IRC_Operator')
    return u

def joinClient(irc, client, channel):
    # InspIRCd doesn't distinguish between burst joins and regular joins,
    # so what we're actually doing here is sending FJOIN from the server,
    # on behalf of the clients that call it.
    channel = utils.toLower(irc, channel)
    server = utils.isInternalClient(irc, client)
    if not server:
        log.error('(%s) Error trying to join client %r to %r (no such pseudoclient exists)', irc.name, client, channel)
        raise LookupError('No such PyLink PseudoClient exists.')
    # Strip out list-modes, they shouldn't be ever sent in FJOIN.
    modes = [m for m in irc.channels[channel].modes if m[0] not in irc.cmodes['*A']]
    _send(irc, server, "FJOIN {channel} {ts} {modes} :,{uid}".format(
            ts=irc.channels[channel].ts, uid=client, channel=channel,
            modes=utils.joinModes(modes)))
    irc.channels[channel].users.add(client)
    irc.users[client].channels.add(channel)

def sjoinServer(irc, server, channel, users, ts=None):
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
    # Strip out list-modes, they shouldn't be ever sent in FJOIN.
    modes = [m for m in irc.channels[channel].modes if m[0] not in irc.cmodes['*A']]
    uids = []
    changedmodes = []
    namelist = []
    # We take <users> as a list of (prefixmodes, uid) pairs.
    for userpair in users:
        assert len(userpair) == 2, "Incorrect format of userpair: %r" % userpair
        prefixes, user = userpair
        namelist.append(','.join(userpair))
        uids.append(user)
        for m in prefixes:
            changedmodes.append(('+%s' % m, user))
        try:
            irc.users[user].channels.add(channel)
        except KeyError:  # Not initialized yet?
            log.debug("(%s) sjoinServer: KeyError trying to add %r to %r's channel list?", irc.name, channel, user)
    if ts <= orig_ts:
        # Only save our prefix modes in the channel state if our TS is lower than or equal to theirs.
        utils.applyModes(irc, channel, changedmodes)
    namelist = ' '.join(namelist)
    _send(irc, server, "FJOIN {channel} {ts} {modes} :{users}".format(
            ts=ts, users=namelist, channel=channel,
            modes=utils.joinModes(modes)))
    irc.channels[channel].users.update(uids)

def _operUp(irc, target, opertype=None):
    userobj = irc.users[target]
    try:
        otype = opertype or userobj.opertype
    except AttributeError:
        log.debug('(%s) opertype field for %s (%s) isn\'t filled yet!',
                  irc.name, target, userobj.nick)
        # whatever, this is non-standard anyways.
        otype = 'IRC_Operator'
    log.debug('(%s) Sending OPERTYPE from %s to oper them up.',
              irc.name, target)
    userobj.opertype = otype
    _send(irc, target, 'OPERTYPE %s' % otype)

def _sendModes(irc, numeric, target, modes, ts=None):
    # -> :9PYAAAAAA FMODE #pylink 1433653951 +os 9PYAAAAAA
    # -> :9PYAAAAAA MODE 9PYAAAAAA -i+w
    log.debug('(%s) inspircd._sendModes: received %r for mode list', irc.name, modes)
    if ('+o', None) in modes and not utils.isChannel(target):
        # https://github.com/inspircd/inspircd/blob/master/src/modules/m_spanningtree/opertype.cpp#L26-L28
        # Servers need a special command to set umode +o on people.
        # Why isn't this documented anywhere, InspIRCd?
        _operUp(irc, target)
    utils.applyModes(irc, target, modes)
    joinedmodes = utils.joinModes(modes)
    if utils.isChannel(target):
        ts = ts or irc.channels[utils.toLower(irc, target)].ts
        _send(irc, numeric, 'FMODE %s %s %s' % (target, ts, joinedmodes))
    else:
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
    _send(irc, numeric, 'KILL %s :%s' % (target, reason))
    # We don't need to call removeClient here, since the remote server
    # will send a QUIT from the target if the command succeeds.

def killClient(irc, numeric, target, reason):
    """<irc object> <client numeric> <target> <reason>

    Sends a kill to <target> from a PyLink PseudoClient.
    """
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'KILL %s :%s' % (target, reason))
    # We don't need to call removeClient here, since the remote server
    # will send a QUIT from the target if the command succeeds.

def topicServer(irc, numeric, target, text):
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    ts = int(time.time())
    servername = irc.servers[numeric].name
    _send(irc, numeric, 'FTOPIC %s %s %s :%s' % (target, ts, servername, text))
    irc.channels[target].topic = text
    irc.channels[target].topicset = True

def inviteClient(irc, numeric, target, channel):
    """<irc object> <client numeric> <text>

    Invites <target> to <channel> to <text> from PyLink client <client numeric>."""
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'INVITE %s %s' % (target, channel))

def knockClient(irc, numeric, target, text):
    """<irc object> <client numeric> <text>

    Knocks on <channel> with <text> from PyLink client <client numeric>."""
    if not utils.isInternalClient(irc, numeric):
        raise LookupError('No such PyLink PseudoClient exists.')
    _send(irc, numeric, 'ENCAP * KNOCK %s :%s' % (target, text))

def updateClient(irc, numeric, field, text):
    """<irc object> <client numeric> <field> <text>

    Changes the <field> field of <target> PyLink PseudoClient <client numeric>."""
    field = field.upper()
    if field == 'IDENT':
        irc.users[numeric].ident = text
        _send(irc, numeric, 'FIDENT %s' % text)
    elif field == 'HOST':
        irc.users[numeric].host = text
        _send(irc, numeric, 'FHOST %s' % text)
    elif field in ('REALNAME', 'GECOS'):
        irc.users[numeric].realname = text
        _send(irc, numeric, 'FNAME :%s' % text)
    else:
        raise NotImplementedError("Changing field %r of a client is unsupported by this protocol." % field)

def pingServer(irc, source=None, target=None):
    source = source or irc.sid
    target = target or irc.uplink
    if not (target is None or source is None):
        _send(irc, source, 'PING %s %s' % (source, target))

def numericServer(irc, source, numeric, text):
    raise NotImplementedError("Numeric sending is not yet implemented by this "
                              "protocol module. WHOIS requests are handled "
                              "locally by InspIRCd servers, so there is no "
                              "need for PyLink to send numerics directly yet.")

def awayClient(irc, source, text):
    """<irc object> <numeric> <text>

    Sends an AWAY message with text <text> from PyLink client <numeric>.
    <text> can be an empty string to unset AWAY status."""
    if text:
        _send(irc, source, 'AWAY %s :%s' % (int(time.time()), text))
    else:
        _send(irc, source, 'AWAY')

def connect(irc):
    ts = irc.start_ts

    f = irc.send
    f('CAPAB START 1202')
    f('CAPAB CAPABILITIES :PROTOCOL=1202')
    f('CAPAB END')
    f('SERVER {host} {Pass} 0 {sid} :{sdesc}'.format(host=irc.serverdata["hostname"],
      Pass=irc.serverdata["sendpass"], sid=irc.sid,
      sdesc=irc.serverdata.get('serverdesc') or irc.botdata['serverdesc']))
    f(':%s BURST %s' % (irc.sid, ts))
    f(':%s ENDBURST' % (irc.sid))

def handle_ping(irc, source, command, args):
    # <- :70M PING 70M 0AL
    # -> :0AL PONG 0AL 70M
    if utils.isInternalServer(irc, args[1]):
        _send(irc, args[1], 'PONG %s %s' % (args[1], source))

def handle_pong(irc, source, command, args):
    if source == irc.uplink and args[1] == irc.sid:
        irc.lastping = time.time()

def handle_fjoin(irc, servernumeric, command, args):
    # :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :o,1SRAABIT4 v,1IOAAF53R <...>
    channel = utils.toLower(irc, args[0])
    # InspIRCd sends each user's channel data in the form of 'modeprefix(es),UID'
    userlist = args[-1].split()
    our_ts = irc.channels[channel].ts
    their_ts = int(args[1])
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
    for user in userlist:
        modeprefix, user = user.split(',', 1)
        namelist.append(user)
        irc.users[user].channels.add(channel)
        if their_ts <= our_ts:
            utils.applyModes(irc, channel, [('+%s' % mode, user) for mode in modeprefix])
        irc.channels[channel].users.add(user)
    return {'channel': channel, 'users': namelist, 'modes': parsedmodes, 'ts': their_ts}

def handle_uid(irc, numeric, command, args):
    # :70M UID 70MAAAAAB 1429934638 GL 0::1 hidden-7j810p.9mdf.lrek.0000.0000.IP gl 0::1 1429934638 +Wioswx +ACGKNOQXacfgklnoqvx :realname
    uid, ts, nick, realhost, host, ident, ip = args[0:7]
    realname = args[-1]
    irc.users[uid] = IrcUser(nick, ts, uid, ident, host, realname, realhost, ip)
    parsedmodes = utils.parseModes(irc, uid, [args[8], args[9]])
    log.debug('Applying modes %s for %s', parsedmodes, uid)
    utils.applyModes(irc, uid, parsedmodes)
    irc.servers[numeric].users.add(uid)
    return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

def handle_server(irc, numeric, command, args):
    # SERVER is sent by our uplink or any other server to introduce others.
    # <- :00A SERVER test.server * 1 00C :testing raw message syntax
    # <- :70M SERVER millennium.overdrive.pw * 1 1ML :a relatively long period of time... (Fremont, California)
    servername = args[0].lower()
    sid = args[3]
    sdesc = args[-1]
    irc.servers[sid] = IrcServer(numeric, servername)
    return {'name': servername, 'sid': args[3], 'text': sdesc}

def handle_fmode(irc, numeric, command, args):
    # <- :70MAAAAAA FMODE #chat 1433653462 +hhT 70MAAAAAA 70MAAAAAD
    channel = utils.toLower(irc, args[0])
    modes = args[2:]
    changedmodes = utils.parseModes(irc, channel, modes)
    utils.applyModes(irc, channel, changedmodes)
    ts = int(args[1])
    return {'target': channel, 'modes': changedmodes, 'ts': ts}


def handle_idle(irc, numeric, command, args):
    """Handle the IDLE command, sent between servers in remote WHOIS queries."""
    # <- :70MAAAAAA IDLE 1MLAAAAIG
    # -> :1MLAAAAIG IDLE 70MAAAAAA 1433036797 319
    sourceuser = numeric
    targetuser = args[0]
    _send(irc, targetuser, 'IDLE %s %s 0' % (sourceuser, irc.users[targetuser].ts))

def handle_events(irc, data):
    # Each server message looks something like this:
    # :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :v,1SRAAESWE
    # :<sid> <command> <argument1> <argument2> ... :final multi word argument
    args = data.split(" ")
    if not args:
        # No data??
        return
    if args[0] == 'SERVER':
       # <- SERVER whatever.net abcdefgh 0 10X :something
       servername = args[1].lower()
       numeric = args[4]
       if args[2] != irc.serverdata['recvpass']:
            # Check if recvpass is correct
            raise ProtocolError('Error: recvpass from uplink server %s does not match configuration!' % servername)
       irc.servers[numeric] = IrcServer(None, servername)
       irc.uplink = numeric
       return
    elif args[0] == 'CAPAB':
        # Capability negotiation with our uplink
        if args[1] == 'CHANMODES':
            # <- CAPAB CHANMODES :admin=&a allowinvite=A autoop=w ban=b banexception=e blockcolor=c c_registered=r exemptchanops=X filter=g flood=f halfop=%h history=H invex=I inviteonly=i joinflood=j key=k kicknorejoin=J limit=l moderated=m nickflood=F noctcp=C noextmsg=n nokick=Q noknock=K nonick=N nonotice=T official-join=!Y op=@o operonly=O opmoderated=U owner=~q permanent=P private=p redirect=L reginvite=R regmoderated=M secret=s sslonly=z stripcolor=S topiclock=t voice=+v

            # Named modes are essential for a cross-protocol IRC service. We
            # can use InspIRCd as a model here and assign a similar mode map to our cmodes list.
            for modepair in args[2:]:
                name, char = modepair.split('=')
                if name == 'reginvite':  # Reginvite? That's a dumb name.
                    name = 'regonly'
                if name == 'founder':  # Channel mode +q
                    # Founder, owner; same thing. m_customprefix allows you to name it anything you like
                    # (the former is config default, but I personally prefer the latter.)
                    name = 'owner'
                # We don't really care about mode prefixes; just the mode char
                irc.cmodes[name.lstrip(':')] = char[-1]
        elif args[1] == 'USERMODES':
            # <- CAPAB USERMODES :bot=B callerid=g cloak=x deaf_commonchan=c helpop=h hidechans=I hideoper=H invisible=i oper=o regdeaf=R servprotect=k showwhois=W snomask=s u_registered=r u_stripcolor=S wallops=w
            # Ditto above.
            for modepair in args[2:]:
                name, char = modepair.split('=')
                irc.umodes[name.lstrip(':')] = char
        elif args[1] == 'CAPABILITIES':
            # <- CAPAB CAPABILITIES :NICKMAX=21 CHANMAX=64 MAXMODES=20 IDENTMAX=11 MAXQUIT=255 MAXTOPIC=307 MAXKICK=255 MAXGECOS=128 MAXAWAY=200 IP6SUPPORT=1 PROTOCOL=1202 PREFIX=(Yqaohv)!~&@%+ CHANMODES=IXbegw,k,FHJLfjl,ACKMNOPQRSTUcimnprstz USERMODES=,,s,BHIRSWcghikorwx GLOBOPS=1 SVSPART=1
            caps = dict([x.lstrip(':').split('=') for x in args[2:]])
            protocol_version = int(caps['PROTOCOL'])
            if protocol_version < 1202:
                raise ProtocolError("Remote protocol version is too old! At least 1202 (InspIRCd 2.0.x) is needed. (got %s)" % protocol_version)
            irc.maxnicklen = int(caps['NICKMAX'])
            irc.maxchanlen = int(caps['CHANMAX'])
            # Modes are divided into A, B, C, and D classes
            # See http://www.irc.org/tech_docs/005.html

            # FIXME: Find a better way to assign/store this.
            irc.cmodes['*A'], irc.cmodes['*B'], irc.cmodes['*C'], irc.cmodes['*D'] \
                = caps['CHANMODES'].split(',')
            irc.umodes['*A'], irc.umodes['*B'], irc.umodes['*C'], irc.umodes['*D'] \
                = caps['USERMODES'].split(',')
            prefixsearch = re.search(r'\(([A-Za-z]+)\)(.*)', caps['PREFIX'])
            irc.prefixmodes = dict(zip(prefixsearch.group(1), prefixsearch.group(2)))
            log.debug('(%s) irc.prefixmodes set to %r', irc.name, irc.prefixmodes)
            # Sanity check: set this AFTER we fetch the capabilities for the network!
            irc.connected.set()
    try:
        args = parseTS6Args(args)
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

def spawnServer(irc, name, sid=None, uplink=None, desc=None):
    # -> :0AL SERVER test.server * 1 0AM :some silly pseudoserver
    uplink = uplink or irc.sid
    name = name.lower()
    desc = desc or irc.serverdata.get('serverdesc') or irc.botdata['serverdesc']
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
    _send(irc, sid, 'ENDBURST')
    return sid

def squitServer(irc, source, target, text='No reason given'):
    # -> :9PY SQUIT 9PZ :blah, blah
    _send(irc, source, 'SQUIT %s :%s' % (target, text))
    handle_squit(irc, source, 'SQUIT', [target, text])

def handle_ftopic(irc, numeric, command, args):
    # <- :70M FTOPIC #channel 1434510754 GLo|o|!GLolol@escape.the.dreamland.ca :Some channel topic
    channel = utils.toLower(irc, args[0])
    ts = args[1]
    setter = args[2]
    topic = args[-1]
    irc.channels[channel].topic = topic
    irc.channels[channel].topicset = True
    return {'channel': channel, 'setter': setter, 'ts': ts, 'topic': topic}

def handle_invite(irc, numeric, command, args):
    # <- :70MAAAAAC INVITE 0ALAAAAAA #blah 0
    target = args[0]
    channel = utils.toLower(irc, args[1])
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
        channel = utils.toLower(irc, args[2])
        text = args[3]
        return {'parse_as': real_command, 'channel': channel,
                'text': text}

def handle_opertype(irc, numeric, command, args):
    # This is used by InspIRCd to denote an oper up; there is no MODE
    # command sent for it.
    # <- :70MAAAAAB OPERTYPE Network_Owner
    omode = [('+o', None)]
    irc.users[numeric].opertype = opertype = args[0]
    utils.applyModes(irc, numeric, omode)
    # OPERTYPE is essentially umode +o and metadata in one command;
    # we'll call that too.
    irc.callHooks([numeric, 'PYLINK_CLIENT_OPERED', {'text': opertype}])
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

def handle_away(irc, numeric, command, args):
    # <- :1MLAAAAIG AWAY 1439371390 :Auto-away
    try:
        ts = args[0]
        irc.users[numeric].away = text = args[1]
        return {'text': text, 'ts': ts}
    except IndexError:  # User is unsetting away status
        irc.users[numeric].away = ''
        return {'text': ''}
