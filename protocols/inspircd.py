import time
import sys
import os
import re
from copy import copy

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import utils
from log import log

from classes import *

casemapping = 'rfc1459'

# Raw commands sent from servers vary from protocol to protocol. Here, we map
# non-standard names to our hook handlers, so plugins get the information they need.

# XXX figure out a way to not force-map ENCAP to KNOCK, since other commands are sent
# through it too.
hook_map = {'FJOIN': 'JOIN', 'RSQUIT': 'SQUIT', 'FMODE': 'MODE',
            'FTOPIC': 'TOPIC', 'ENCAP': 'KNOCK', 'OPERTYPE': 'MODE',
            'FHOST': 'CHGHOST', 'FIDENT': 'CHGIDENT', 'FNAME': 'CHGNAME'}

def _send(irc, sid, msg):
    irc.send(':%s %s' % (sid, msg))

def spawnClient(irc, nick, ident='null', host='null', realhost=None, modes=set(),
        server=None, ip='0.0.0.0', realname=None, ts=None):
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
    irc.servers[server].users.append(uid)
    _send(irc, server, "UID {uid} {ts} {nick} {realhost} {host} {ident} {ip}"
                    " {ts} {modes} + :{realname}".format(ts=ts, host=host,
                                             nick=nick, ident=ident, uid=uid,
                                             modes=raw_modes, ip=ip, realname=realname,
                                             realhost=realhost))
    return u

def joinClient(irc, client, channel):
    # InspIRCd doesn't distinguish between burst joins and regular joins,
    # so what we're actually doing here is sending FJOIN from the server,
    # on behalf of the clients that call it.
    channel = channel.lower()
    server = utils.isInternalClient(irc, client)
    if not server:
        log.error('(%s) Error trying to join client %r to %r (no such pseudoclient exists)', irc.name, client, channel)
        raise LookupError('No such PyLink PseudoClient exists.')
    # One channel per line here!
    _send(irc, server, "FJOIN {channel} {ts} {modes} :,{uid}".format(
            ts=irc.channels[channel].ts, uid=client, channel=channel,
            modes=utils.joinModes(irc.channels[channel].modes)))
    irc.channels[channel].users.add(client)
    irc.users[client].channels.add(channel)

def sjoinServer(irc, server, channel, users, ts=None):
    channel = channel.lower()
    server = server or irc.sid
    assert users, "sjoinServer: No users sent?"
    log.debug('(%s) sjoinServer: got %r for users', irc.name, users)
    if not server:
        raise LookupError('No such PyLink PseudoClient exists.')
    if ts is None:
        ts = irc.channels[channel].ts
    log.debug("sending SJOIN to %s%s with ts %s (that's %r)", channel, irc.name, ts, 
              time.strftime("%c", time.localtime(ts)))
    ''' TODO: handle this properly!
    if modes is None:
        modes = irc.channels[channel].modes
    else:
        utils.applyModes(irc, channel, modes)
    '''
    modes = irc.channels[channel].modes
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
    utils.applyModes(irc, channel, changedmodes)
    namelist = ' '.join(namelist)
    _send(irc, server, "FJOIN {channel} {ts} {modes} :{users}".format(
            ts=ts, users=namelist, channel=channel,
            modes=utils.joinModes(modes)))
    irc.channels[channel].users.update(uids)

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

def _sendModes(irc, numeric, target, modes, ts=None):
    # -> :9PYAAAAAA FMODE #pylink 1433653951 +os 9PYAAAAAA
    # -> :9PYAAAAAA MODE 9PYAAAAAA -i+w
    joinedmodes = utils.joinModes(modes)
    utils.applyModes(irc, target, modes)
    if utils.isChannel(target):
        ts = ts or irc.channels[target.lower()].ts
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

def topicServer(irc, numeric, target, text):
    if not utils.isInternalServer(irc, numeric):
        raise LookupError('No such PyLink PseudoServer exists.')
    ts = int(time.time())
    servername = irc.servers[numeric].name
    _send(irc, numeric, 'FTOPIC %s %s %s :%s' % (target, ts, servername, text))

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

def connect(irc):
    ts = irc.start_ts
    irc.uidgen = {}

    f = irc.send
    f('CAPAB START 1202')
    f('CAPAB CAPABILITIES :PROTOCOL=1202')
    f('CAPAB END')
    f('SERVER {host} {Pass} 0 {sid} :PyLink Service'.format(host=irc.serverdata["hostname"],
      Pass=irc.serverdata["sendpass"], sid=irc.sid))
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

def handle_privmsg(irc, source, command, args):
    return {'target': args[0], 'text': args[1]}

def handle_kill(irc, source, command, args):
    killed = args[0]
    data = irc.users.get(killed)
    if data:
        removeClient(irc, killed)
    return {'target': killed, 'text': args[1], 'userdata': data}

def handle_kick(irc, source, command, args):
    # :70MAAAAAA KICK #endlessvoid 70MAAAAAA :some reason
    channel = args[0].lower()
    kicked = args[1]
    handle_part(irc, kicked, 'KICK', [channel, args[2]])
    return {'channel': channel, 'target': kicked, 'text': args[2]}

def handle_part(irc, source, command, args):
    channels = args[0].lower().split(',')
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
    return {'channels': channels, 'text': reason}

def handle_error(irc, numeric, command, args):
    irc.connected.clear()
    raise ProtocolError('Received an ERROR, killing!')

def handle_fjoin(irc, servernumeric, command, args):
    # :70M FJOIN #chat 1423790411 +AFPfjnt 6:5 7:5 9:5 :o,1SRAABIT4 v,1IOAAF53R <...>
    channel = args[0].lower()
    # InspIRCd sends each user's channel data in the form of 'modeprefix(es),UID'
    userlist = args[-1].split()
    our_ts = irc.channels[channel].ts
    their_ts = int(args[1])
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
        modeprefix, user = user.split(',', 1)
        namelist.append(user)
        irc.users[user].channels.add(channel)
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
    irc.servers[numeric].users.append(uid)
    return {'uid': uid, 'ts': ts, 'nick': nick, 'realhost': realhost, 'host': host, 'ident': ident, 'ip': ip}

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
    oldnick = irc.users[user].nick
    irc.users[user].nick = user
    return {'target': user, 'ts': int(args[1]), 'oldnick': oldnick}

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
            # can use InspIRCd as a model here and assign their mode map to our cmodes list.
            for modepair in args[2:]:
                name, char = modepair.split('=')
                if name == 'reginvite':  # Reginvite? That's a dumb name.
                    name = 'regonly'
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

def spawnServer(irc, name, sid=None, uplink=None, desc='PyLink Server'):
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
    _send(irc, sid, 'ENDBURST')
    return sid

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
