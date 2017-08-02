# relay.py: PyLink Relay plugin
import time
import threading
import string
from collections import defaultdict
import inspect

from pylinkirc import utils, world, conf, structures
from pylinkirc.log import log
from pylinkirc.coremods import permissions

# Sets the timeout to wait for as individual servers / the PyLink daemon to start up.
TCONDITION_TIMEOUT = 2

### GLOBAL (statekeeping) VARIABLES
relayusers = defaultdict(dict)
relayservers = defaultdict(dict)
spawnlocks = defaultdict(threading.RLock)
spawnlocks_servers = defaultdict(threading.RLock)

dbname = utils.getDatabaseName('pylinkrelay')
datastore = structures.PickleDataStore('pylinkrelay', dbname)
db = datastore.store

default_permissions = {"*!*@*": ['relay.linked'],
                       "$ircop": ['relay.create', 'relay.linkacl*',
                                  'relay.destroy', 'relay.link', 'relay.delink',
                                  'relay.claim']}

### INTERNAL FUNCTIONS

def initialize_all(irc):
    """Initializes all relay channels for the given IRC object."""

    # Wait for all IRC objects to be created first. This prevents
    # relay servers from being spawned too early (before server authentication),
    # which would break connections.
    if world.started.wait(TCONDITION_TIMEOUT):
        for chanpair, entrydata in db.items():
            # Iterate over all the channels stored in our relay links DB.
            network, channel = chanpair

            # Initialize each relay channel on their home network, and on every linked one too.
            initialize_channel(irc, channel)
            for link in entrydata['links']:
                network, channel = link
                initialize_channel(irc, channel)

def main(irc=None):
    """Main function, called during plugin loading at start."""
    log.debug('relay.main: loading links database')
    datastore.load()

    permissions.addDefaultPermissions(default_permissions)

    if irc is not None:
        # irc is defined when the plugin is reloaded. Otherwise, it means that we've just started the
        # server. Iterate over all connected networks and initialize their relay users.
        for ircobj in world.networkobjects.values():
            if ircobj.connected.is_set():
                initialize_all(ircobj)

    log.debug('relay.main: finished initialization sequence')

def die(irc=None):
    """Deinitialize PyLink Relay by quitting all relay clients and saving the
    relay DB."""

    # For every connected network:
    for ircobj in world.networkobjects.values():
        # 1) SQUIT every relay subserver.
        for server, sobj in ircobj.servers.copy().items():
            if hasattr(sobj, 'remote'):
                ircobj.proto.squit(ircobj.sid, server, text="Relay plugin unloaded.")

    # 2) Clear our internal servers and users caches.
    relayservers.clear()
    relayusers.clear()

    # 3) Unload our permissions.
    permissions.removeDefaultPermissions(default_permissions)

    # 4) Save the database and quit.
    datastore.die()

allowed_chars = string.digits + string.ascii_letters + '/^|\\-_[]{}`'
fallback_separator = '|'
def normalize_nick(irc, netname, nick, times_tagged=0, uid=''):
    """
    Creates a normalized nickname for the given nick suitable for introduction to a remote network
    (as a relay client).

    UID is optional for checking regular nick changes, to make sure that the sender doesn't get
    marked as nick-colliding with itself.
    """

    # Get the nick/net separator
    separator = irc.serverdata.get('separator') or \
        conf.conf.get('relay', {}).get('separator') or "/"

    # Figure out whether we tag nicks or not.
    if times_tagged == 0:
        # Check the following options in order, before falling back to True:
        #  1) servers::<netname>::relay_tag_nicks
        #  2) relay::tag_nicks
        if irc.serverdata.get('relay_tag_nicks', conf.conf.get('relay', {}).get('tag_nicks', True)):
            times_tagged = 1
        else:
            forcetag_nicks = conf.conf.get('relay', {}).get('forcetag_nicks', [])
            log.debug('(%s) relay.normalize_nick: checking if globs %s match %s.', irc.name, forcetag_nicks, nick)
            for glob in forcetag_nicks:
                if irc.matchHost(glob, nick):
                    # User matched a nick to force tag nicks for. Tag them.
                    times_tagged = 1
                    break

    log.debug('(%s) relay.normalize_nick: using %r as separator.', irc.name, separator)
    orig_nick = nick
    maxnicklen = irc.maxnicklen

    # Charybdis, IRCu, etc. don't allow / in nicks, and will SQUIT with a protocol
    # violation if it sees one. Or it might just ignore the client introduction and
    # cause bad desyncs.
    protocol_allows_slashes = irc.proto.hasCap('slash-in-nicks') or \
        irc.serverdata.get('relay_force_slashes')

    if '/' not in separator or not protocol_allows_slashes:
        separator = separator.replace('/', fallback_separator)
        nick = nick.replace('/', fallback_separator)

    if nick.startswith(tuple(string.digits+'-')):
        # On TS6 IRCds, nicks that start with 0-9 are only allowed if
        # they match the UID of the originating server. Otherwise, you'll
        # get nasty protocol violation SQUITs!
        # Nicks starting with - are likewise not valid.
        nick = '_' + nick

    # Maximum allowed length that relay nicks may have, minus the /network tag if used.
    allowedlength = maxnicklen

    # Track how many times the given nick has been tagged. If this is 0, no tag is used.
    # If this is 1, a /network tag is added. Otherwise, keep adding one character to the
    # separator: GLolol -> GLolol/net1 -> GLolol//net1 -> ...
    if times_tagged >= 1:
        suffix = "%s%s%s" % (separator[0]*times_tagged, separator[1:], netname)
        allowedlength -= len(suffix)

    # If a nick is too long, the real nick portion will be cut off, but the
    # /network suffix MUST remain the same.
    nick = nick[:allowedlength]
    if times_tagged >= 1:
        nick += suffix

    # Loop over every character in the nick, making sure that it only contains valid
    # characters.
    for char in nick:
        if char not in allowed_chars:
            nick = nick.replace(char, fallback_separator)

    while irc.nickToUid(nick) and irc.nickToUid(nick) != uid:
        # The nick we want exists: Increase the separator length by 1 if the user was already
        # tagged, but couldn't be created due to a nick conflict. This can happen when someone
        # steals a relay user's nick.
        # However, if a user is changing from, say, a long, cut-off nick to another long, cut-off
        # nick, we would skip tagging the nick twice if they originate from the same UID.
        times_tagged += 1
        log.debug('(%s) relay.normalize_nick: nick %r is in use; incrementing times tagged to %s.',
                  irc.name, nick, times_tagged)
        nick = normalize_nick(irc, netname, orig_nick, times_tagged=times_tagged, uid=uid)

    finalLength = len(nick)
    assert finalLength <= maxnicklen, "Normalized nick %r went over max " \
        "nick length (got: %s, allowed: %s!)" % (nick, finalLength, maxnicklen)

    return nick

def normalize_host(irc, host):
    """Creates a normalized hostname for the given host suitable for
    introduction to a remote network (as a relay client)."""
    log.debug('(%s) relay.normalize_host: IRCd=%s, host=%s', irc.name, irc.protoname, host)

    allowed_chars = string.ascii_letters + string.digits + '-.:'
    if irc.proto.hasCap('slash-in-hosts'):
        # UnrealIRCd and IRCd-Hybrid don't allow slashes in hostnames
        allowed_chars += '/'

    if irc.proto.hasCap('underscore-in-hosts'):
        # Most IRCds allow _ in hostnames, but hybrid/charybdis/ratbox IRCds do not.
        allowed_chars += '_'

    for char in host:
        if char not in allowed_chars:
            host = host.replace(char, '-')

    return host[:63]  # Limit hosts to 63 chars for best compatibility

def get_prefix_modes(irc, remoteirc, channel, user, mlist=None):
    """
    Fetches all prefix modes for a user in a channel that are supported by the
    remote IRC network given.

    Optionally, an mlist argument can be given to look at an earlier state of
    the channel, e.g. for checking the op status of a mode setter before their
    modes are processed and added to the channel state.
    """
    modes = ''

    if user in irc.channels[channel].users:
        # Iterate over the the prefix modes for relay supported by the remote IRCd.
        # Note: reverse the order so prefix modes are bursted in their traditional order
        # (e.g. owner before op before halfop). TODO: SJOIN modes should probably be
        # consistently sorted IRCd-side.
        for pmode in reversed(irc.channels[channel].getPrefixModes(user, prefixmodes=mlist)):
            if pmode in remoteirc.cmodes:
                modes += remoteirc.cmodes[pmode]
    return modes

def spawn_relay_server(irc, remoteirc):
    if irc.connected.wait(TCONDITION_TIMEOUT):
        try:
            # ENDBURST is delayed by 3 secs on supported IRCds to prevent
            # triggering join-flood protection and the like.
            suffix = conf.conf.get('relay', {}).get('server_suffix', 'relay')
            # Strip any leading or trailing .'s
            suffix = suffix.strip('.')
            sid = irc.proto.spawnServer('%s.%s' % (remoteirc.name, suffix),
                                        desc="PyLink Relay network - %s" %
                                        (remoteirc.getFullNetworkName()), endburst_delay=3)
        except (RuntimeError, ValueError):  # Network not initialized yet, or a server name conflict.
            log.exception('(%s) Failed to spawn server for %r (possible jupe?):',
                          irc.name, remoteirc.name)
            # We will just bail here. Disconnect the bad network.
            irc.disconnect()
            return

        # Mark the server as a relay server
        irc.servers[sid].remote = remoteirc.name

        # Assign the newly spawned server as our relay server for the target net.
        relayservers[irc.name][remoteirc.name] = sid

        return sid
    else:
        log.debug('(%s) skipping spawn_relay_server(%s, %s); the remote is not ready yet',
                  irc.name, irc.name, remoteirc.name)

def get_remote_sid(irc, remoteirc, spawn_if_missing=True):
    """Gets the remote server SID representing remoteirc on irc, spawning
    it if it doesn't exist (and spawn_if_missing is enabled)."""

    log.debug('(%s) Grabbing spawnlocks_servers[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    if spawnlocks_servers[irc.name].acquire(timeout=TCONDITION_TIMEOUT):
        try:
            sid = relayservers[irc.name][remoteirc.name]
        except KeyError:
            if not spawn_if_missing:
                log.debug('(%s) get_remote_sid: %s.relay doesn\'t have a known SID, ignoring.', irc.name, remoteirc.name)
                spawnlocks_servers[irc.name].release()
                return

            log.debug('(%s) get_remote_sid: %s.relay doesn\'t have a known SID, spawning.', irc.name, remoteirc.name)
            sid = spawn_relay_server(irc, remoteirc)

        log.debug('(%s) get_remote_sid: got %s for %s.relay', irc.name, sid, remoteirc.name)
        if sid not in irc.servers:
            log.debug('(%s) get_remote_sid: SID %s for %s.relay doesn\'t exist, respawning', irc.name, sid, remoteirc.name)
            # Our stored server doesn't exist anymore. This state is probably a holdover from a netsplit,
            # so let's refresh it.
            sid = spawn_relay_server(irc, remoteirc)
        elif sid in irc.servers and irc.servers[sid].remote != remoteirc.name:
            log.debug('(%s) get_remote_sid: %s.relay != %s.relay, respawning', irc.name, irc.servers[sid].remote, remoteirc.name)
            sid = spawn_relay_server(irc, remoteirc)

        log.debug('(%s) get_remote_sid: got %s for %s.relay (round 2)', irc.name, sid, remoteirc.name)
        spawnlocks_servers[irc.name].release()
        return sid

def spawn_relay_user(irc, remoteirc, user, times_tagged=0):
    userobj = irc.users.get(user)
    if userobj is None:
        # The query wasn't actually a valid user, or the network hasn't
        # been connected yet... Oh well!
        return
    nick = normalize_nick(remoteirc, irc.name, userobj.nick, times_tagged=times_tagged)
    # Truncate idents at 10 characters, because TS6 won't like them otherwise!
    ident = userobj.ident[:10]
    # Normalize hostnames
    host = normalize_host(remoteirc, userobj.host)
    realname = userobj.realname
    modes = set(get_supported_umodes(irc, remoteirc, userobj.modes))
    opertype = ''
    if ('o', None) in userobj.modes:

        # Try to get the oper type, adding an "(on <networkname>)" suffix similar to what
        # Janus does.
        if hasattr(userobj, 'opertype'):
            log.debug('(%s) relay.get_remote_user: setting OPERTYPE of client for %r to %s',
                      irc.name, user, userobj.opertype)
            opertype = userobj.opertype
        else:
            opertype = 'IRC Operator'

        opertype += ' (on %s)' % irc.getFullNetworkName()

        # Set hideoper on remote opers, to prevent inflating
        # /lusers and various /stats
        hideoper_mode = remoteirc.umodes.get('hideoper')
        try:
            use_hideoper = conf.conf['relay']['hideoper']
        except KeyError:
            use_hideoper = True
        if hideoper_mode and use_hideoper:
            modes.add((hideoper_mode, None))

    rsid = get_remote_sid(remoteirc, irc)
    if not rsid:
        log.error('(%s) spawn_relay_user: aborting user spawn for %s/%s @ %s (failed to retrieve a '
                  'working SID).', irc.name, user, nick, remoteirc.name)
        return
    try:
        showRealIP = conf.conf['relay']['show_ips'] and not \
                     irc.serverdata.get('relay_no_ips') and not \
                     remoteirc.serverdata.get('relay_no_ips')
    except KeyError:
        showRealIP = False
    if showRealIP:
        ip = userobj.ip
        realhost = userobj.realhost
    else:
        realhost = None
        ip = '0.0.0.0'

    u = remoteirc.proto.spawnClient(nick, ident=ident, host=host, realname=realname, modes=modes,
                                    opertype=opertype, server=rsid, ip=ip, realhost=realhost).uid
    try:
        remoteirc.users[u].remote = (irc.name, user)
        remoteirc.users[u].opertype = opertype
        away = userobj.away
        if away:
            remoteirc.proto.away(u, away)
    except KeyError:
        # User got killed somehow while we were setting options on it.
        # This is probably being done by the uplink, due to something like an
        # invalid nick, etc.
        raise

    relayusers[(irc.name, user)][remoteirc.name] = u
    return u

def get_remote_user(irc, remoteirc, user, spawn_if_missing=True, times_tagged=0):
    """
    Gets the UID of the relay client requested on the target network (remoteirc),
    spawning one if it doesn't exist and spawn_if_missing is True."""

    # Wait until the network is working before trying to spawn anything.
    if irc.connected.wait(TCONDITION_TIMEOUT):
        # Don't spawn clones for registered service bots.
        sbot = irc.getServiceBot(user)
        if sbot:
            return sbot.uids.get(remoteirc.name)

        log.debug('(%s) Grabbing spawnlocks[%s] from thread %r in function %r', irc.name, irc.name,
                  threading.current_thread().name, inspect.currentframe().f_code.co_name)
        if spawnlocks[irc.name].acquire(timeout=TCONDITION_TIMEOUT):
            # Be sort-of thread safe: lock the user spawns for the current net first.
            u = None
            try:
                # Look up the existing user, stored here as dict entries in the format:
                # {('ournet', 'UID'): {'remotenet1': 'UID1', 'remotenet2': 'UID2'}}
                u = relayusers[(irc.name, user)][remoteirc.name]
            except KeyError:
                # User doesn't exist. Spawn a new one if requested.
                if spawn_if_missing:
                    u = spawn_relay_user(irc, remoteirc, user, times_tagged=times_tagged)

            # This is a sanity check to make sure netsplits and other state resets
            # don't break the relayer. If it turns out there was a client in our relayusers
            # cache for the requested UID, but it doesn't match the request,
            # assume it was a leftover from the last split and replace it with a new one.
            if u and ((u not in remoteirc.users) or remoteirc.users[u].remote != (irc.name, user)):
                u = spawn_relay_user(irc, remoteirc, user, times_tagged=times_tagged)

            spawnlocks[irc.name].release()

            return u
    else:
        log.debug('(%s) skipping spawn_relay_user(%s, %s, %s, ...); the remote is not ready yet',
                  irc.name, irc.name, remoteirc.name, user)

def get_orig_user(irc, user, targetirc=None):
    """
    Given the UID of a relay client, returns a tuple of the home network name
    and original UID of the user it was spawned for.

    If targetirc is given, get_remote_user() is called to get the relay client
    representing the original user on that target network."""

    try:
        remoteuser = irc.users[user].remote
    except (AttributeError, KeyError):
        remoteuser = None
    log.debug('(%s) relay.get_orig_user: remoteuser set to %r (looking up %s/%s).',
              irc.name, remoteuser, user, irc.name)
    if remoteuser:
        # If targetirc is given, we'll return simply the UID of the user on the
        # target network, if it exists. Otherwise, we'll return a tuple
        # with the home network name and the original user's UID.
        sourceobj = world.networkobjects.get(remoteuser[0])
        if targetirc and sourceobj:
            if remoteuser[0] == targetirc.name:
                # The user we found's home network happens to be the one being
                # requested; just return the UID then.
                return remoteuser[1]
            # Otherwise, use get_remote_user to find our UID.
            res = get_remote_user(sourceobj, targetirc, remoteuser[1],
                                spawn_if_missing=False)
            log.debug('(%s) relay.get_orig_user: targetirc found as %s, getting %r as '
                      'remoteuser for %r (looking up %s/%s).', irc.name, targetirc.name,
                      res, remoteuser[1], user, irc.name)
            return res
        else:
            return remoteuser

def get_relay(chanpair):
    """Finds the matching relay entry name for the given (network name, channel)
    pair, if one exists."""
    if chanpair in db:  # This chanpair is a shared channel; others link to it
        return chanpair
    # This chanpair is linked *to* a remote channel
    for name, dbentry in db.items():
        if chanpair in dbentry['links']:
            return name

def get_remote_channel(irc, remoteirc, channel):
    """Returns the linked channel name for the given channel on remoteirc,
    if one exists."""
    query = (irc.name, channel)
    remotenetname = remoteirc.name
    chanpair = get_relay(query)
    if chanpair is None:
        return
    if chanpair[0] == remotenetname:
        return chanpair[1]
    else:
        for link in db[chanpair]['links']:
            if link[0] == remotenetname:
                return link[1]

def initialize_channel(irc, channel):
    """Initializes a relay channel (merge local/remote users, set modes, etc.)."""
    # We're initializing a relay that already exists. This can be done at
    # ENDBURST, or on the LINK command.
    relay = get_relay((irc.name, channel))
    log.debug('(%s) relay.initialize_channel being called on %s', irc.name, channel)
    log.debug('(%s) relay.initialize_channel: relay pair found to be %s', irc.name, relay)
    queued_users = []
    if relay:
        all_links = db[relay]['links'].copy()
        all_links.update((relay,))
        log.debug('(%s) relay.initialize_channel: all_links: %s', irc.name, all_links)

        # Iterate over all the remote channels linked in this relay.
        for link in all_links:
            remotenet, remotechan = link
            if remotenet == irc.name:  # If the network is us, skip.
                continue
            remoteirc = world.networkobjects.get(remotenet)

            if remoteirc is None:
                # Remote network doesn't have an IRC object; e.g. it was removed
                # from the config. Skip this.
                continue
            rc = remoteirc.channels[remotechan]

            if not (remoteirc.connected.is_set() and get_remote_channel(remoteirc, irc, remotechan)):
                continue  # Remote network isn't connected.

            # Join their (remote) users and set their modes.
            relay_joins(remoteirc, remotechan, rc.users, rc.ts)
            topic = remoteirc.channels[remotechan].topic

            # Only update the topic if it's different from what we already have,
            # and topic bursting is complete.
            if remoteirc.channels[remotechan].topicset and topic != irc.channels[channel].topic:
                irc.proto.topicBurst(irc.sid, channel, topic)

        # Send our users and channel modes to the other nets
        log.debug('(%s) relay.initialize_channel: joining our (%s) users: %s', irc.name, remotenet, irc.channels[channel].users)
        relay_joins(irc, channel, irc.channels[channel].users, irc.channels[channel].ts)

        if 'pylink' in world.services:
            world.services['pylink'].join(irc, channel)

def remove_channel(irc, channel):
    """Destroys a relay channel by parting all of its users."""
    if irc is None:
        return

    if channel not in map(str.lower, irc.serverdata.get('channels', [])):
        world.services['pylink'].extra_channels[irc.name].discard(channel)
        if irc.pseudoclient:
            irc.proto.part(irc.pseudoclient.uid, channel, 'Channel delinked.')

    relay = get_relay((irc.name, channel))
    if relay:
        for user in irc.channels[channel].users.copy():
            if not isRelayClient(irc, user):
                relay_part(irc, channel, user)
            # Don't ever part the main client from any of its autojoin channels.
            else:
                if user == irc.pseudoclient.uid and channel in \
                        irc.serverdata.get('channels', []):
                    continue
                irc.proto.part(user, channel, 'Channel delinked.')
                # Don't ever quit it either...
                if user != irc.pseudoclient.uid and not irc.users[user].channels:
                    remoteuser = get_orig_user(irc, user)
                    del relayusers[remoteuser][irc.name]
                    irc.proto.quit(user, 'Left all shared channels.')

def check_claim(irc, channel, sender, chanobj=None):
    """
    Checks whether the sender of a kick/mode change passes CLAIM checks for
    a given channel. This returns True if any of the following criteria are met:

    1) No relay exists for the channel in question.
    2) The originating network is the one that created the relay.
    3) The CLAIM list for the relay in question is empty.
    4) The originating network is in the CLAIM list for the relay in question.
    5) The sender is halfop or above in the channel.
    6) The sender is a PyLink client/server (checks are suppressed in this case).
    """
    relay = get_relay((irc.name, channel))
    try:
        mlist = chanobj.prefixmodes
    except AttributeError:
        mlist = None

    sender_modes = get_prefix_modes(irc, irc, channel, sender, mlist=mlist)
    log.debug('(%s) relay.check_claim: sender modes (%s/%s) are %s (mlist=%s)', irc.name,
              sender, channel, sender_modes, mlist)
    # XXX: stop hardcoding modes to check for and support mlist in isHalfopPlus and friends
    return (not relay) or irc.name == relay[0] or not db[relay]['claim'] or \
        irc.name in db[relay]['claim'] or \
        any([mode in sender_modes for mode in ('y', 'q', 'a', 'o', 'h')]) \
        or irc.isInternalClient(sender) or \
        irc.isInternalServer(sender)

def get_supported_umodes(irc, remoteirc, modes):
    """Given a list of user modes, filters out all of those not supported by the
    remote network."""
    supported_modes = []

    # Iterate over all mode pairs.
    for modepair in modes:
        try:
            # Get the prefix and the actual mode character (the prefix being + or -, or
            # whether we're setting or unsetting a mode)
            prefix, modechar = modepair[0]
        except ValueError:
            # If the prefix is missing, assume we're adding a mode.
            modechar = modepair[0]
            prefix = '+'

        # Get the mode argument.
        arg = modepair[1]

        # Iterate over all supported user modes for the current network.
        for name, m in irc.umodes.items():
            if name.startswith('*'):
                # XXX: Okay, we need a better place to store modetypes.
                continue

            supported_char = None

            # Mode character matches one in our list, so set that named mode
            # as the one we're trying to set. Then, look up that named mode
            # in the supported modes list for the TARGET network, and set that
            # mode character as the one we're setting, if it exists.
            if modechar == m:
                if name not in whitelisted_umodes:
                    log.debug("(%s) relay.get_supported_umodes: skipping mode (%r, %r) because "
                              "it isn't a whitelisted (safe) mode for relay.",
                              irc.name, modechar, arg)
                    break
                supported_char = remoteirc.umodes.get(name)

            if supported_char:
                supported_modes.append((prefix+supported_char, arg))
                break
        else:
            log.debug("(%s) relay.get_supported_umodes: skipping mode (%r, %r) because "
                      "the remote network (%s)'s IRCd (%s) doesn't support it.",
                      irc.name, modechar, arg, remoteirc.name,
                      remoteirc.protoname)
    return supported_modes

def isRelayClient(irc, user):
    """Returns whether the given user is a relay client."""
    try:
        if irc.users[user].remote:
            # Is the .remote attribute set? If so, don't relay already
            # relayed clients; that'll trigger an endless loop!
            return True
    except AttributeError:  # Nope, it isn't.
        pass
    except KeyError:  # The user doesn't exist?!?
        return True
    return False
is_relay_client = isRelayClient

### EVENT HANDLER INTERNALS

def relay_joins(irc, channel, users, ts, burst=True):
    """
    Relays one or more users' joins from a channel to its relay links.
    """
    joined_nets = {}

    if ts < 750000:
        current_ts = int(time.time())
        log.debug('(%s) relay: resetting too low TS value of %s on %s to %s', irc.name, ts, users, current_ts)
        ts = current_ts

    for name, remoteirc in world.networkobjects.copy().items():
        queued_users = []
        if name == irc.name or not remoteirc.connected.is_set():
            # Don't relay things to their source network...
            continue

        remotechan = get_remote_channel(irc, remoteirc, channel)
        if remotechan is None:
            # If there is no link on the current network for the channel in question,
            # just skip it
            continue

        log.debug('(%s) relay.relay_joins: got %r for users', irc.name, users)

        for user in users.copy():
            if isRelayClient(irc, user):
                # Don't clone relay clients; that'll cause bad infinite loops.
                continue

            assert user in irc.users, "(%s) relay.relay_joins: How is this possible? %r isn't in our user database." % (irc.name, user)
            u = get_remote_user(irc, remoteirc, user)

            if not u:
                continue

            if u not in remoteirc.channels[remotechan].users:
                # Note: only join users if they aren't already joined. This prevents op floods
                # on charybdis from repeated SJOINs sent for one user.

                # Fetch the known channel TS and all the prefix modes for each user. This ensures
                # the different sides of the relay are merged properly.
                if not irc.proto.hasCap('has-ts'):
                    # Special hack for clientbot: just use the remote's modes so mode changes
                    # take precendence. (TS is always outside the clientbot's control)
                    ts = remoteirc.channels[remotechan].ts
                else:
                    ts = irc.channels[channel].ts
                prefixes = get_prefix_modes(irc, remoteirc, channel, user)

                # proto.sjoin() takes its users as a list of (prefix mode characters, UID) pairs.
                userpair = (prefixes, u)
                queued_users.append(userpair)

        if queued_users:
            # Look at whether we should relay this join as a regular JOIN, or a SJOIN.
            # SJOIN will be used if either the amount of users to join is > 1, or there are modes
            # to be set on the joining user.
            if burst or len(queued_users) > 1 or queued_users[0][0]:
                modes = get_supported_cmodes(irc, remoteirc, channel, irc.channels[channel].modes)
                rsid = get_remote_sid(remoteirc, irc)
                if rsid:
                    remoteirc.proto.sjoin(rsid, remotechan, queued_users, ts=ts, modes=modes)
            else:
                # A regular JOIN only needs the user and the channel. TS, source SID, etc., can all be omitted.
                remoteirc.proto.join(queued_users[0][1], remotechan)

            joined_nets[remoteirc] = {'channel': remotechan, 'users': [u[-1] for u in queued_users]}

    for remoteirc, hookdata in joined_nets.items():
        # HACK: Announce this JOIN as a special hook on each network, for plugins like Automode.
        remoteirc.callHooks([remoteirc.sid, 'PYLINK_RELAY_JOIN', hookdata])

def relay_part(irc, channel, user):
    """
    Relays a user part from a channel to its relay links, as part of a channel delink.
    """
    for name, remoteirc in world.networkobjects.copy().items():
        if name == irc.name or not remoteirc.connected.is_set():
            # Don't relay things to their source network...
            continue

        remotechan = get_remote_channel(irc, remoteirc, channel)
        log.debug('(%s) relay.relay_part: looking for %s/%s on %s', irc.name, user, irc.name, remoteirc.name)
        log.debug('(%s) relay.relay_part: remotechan found as %s', irc.name, remotechan)

        remoteuser = get_remote_user(irc, remoteirc, user, spawn_if_missing=False)
        log.debug('(%s) relay.relay_part: remoteuser for %s/%s found as %s', irc.name, user, irc.name, remoteuser)

        if remotechan is None or remoteuser is None:
            # If there is no relay channel on the target network, or the relay
            # user doesn't exist, just do nothing.
            continue

        # Part the relay client with the channel delinked message.
        remoteirc.proto.part(remoteuser, remotechan, 'Channel delinked.')

        # If the relay client no longer has any channels, quit them to prevent inflating /lusers.
        if isRelayClient(remoteirc, remoteuser) and not remoteirc.users[remoteuser].channels:
            remoteirc.proto.quit(remoteuser, 'Left all shared channels.')
            del relayusers[(irc.name, user)][remoteirc.name]


whitelisted_cmodes = {'admin', 'allowinvite', 'autoop', 'ban', 'banexception',
                      'blockcolor', 'halfop', 'invex', 'inviteonly', 'key',
                      'limit', 'moderated', 'noctcp', 'noextmsg', 'nokick',
                      'noknock', 'nonick', 'nonotice', 'op', 'operonly',
                      'opmoderated', 'owner', 'private', 'regonly',
                      'regmoderated', 'secret', 'sslonly', 'adminonly',
                      'stripcolor', 'topiclock', 'voice', 'flood',
                      'flood_unreal', 'joinflood', 'freetarget',
                      'noforwards', 'noinvite'}
whitelisted_umodes = {'bot', 'hidechans', 'hideoper', 'invisible', 'oper',
                      'regdeaf', 'stripcolor', 'noctcp', 'wallops',
                      'hideidle'}
clientbot_whitelisted_cmodes = {'admin', 'ban', 'banexception',
                                'halfop', 'invex', 'op', 'owner', 'voice'}
modesync_options = ('none', 'half', 'full')
def get_supported_cmodes(irc, remoteirc, channel, modes):
    """
    Filters a channel mode change to the modes supported by the target IRCd.
    """
    remotechan = get_remote_channel(irc, remoteirc, channel)
    if not remotechan:  # Not a relay channel
        return []

    # Handle Clientbot-specific mode whitelist settings
    whitelist = whitelisted_cmodes
    if remoteirc.protoname == 'clientbot' or irc.protoname == 'clientbot':
        modesync = conf.conf.get('relay', {}).get('clientbot_modesync', 'none').lower()
        if modesync not in modesync_options:
            modesync = 'none'
            log.warning('relay: Bad clientbot_modesync option %s: valid values are %s',
                        modesync, modesync_options)

        if modesync == 'none':
            return []  # Do nothing
        elif modesync == 'half':
            whitelist = clientbot_whitelisted_cmodes

    supported_modes = []
    for modepair in modes:
        try:
            prefix, modechar = modepair[0]
        except ValueError:
            modechar = modepair[0]
            prefix = '+'
        arg = modepair[1]

        # Iterate over every mode see whether the remote IRCd supports
        # this mode, and what its mode char for it is (if it is different).
        for name, m in irc.cmodes.items():
            supported_char = None
            if name.startswith('*'):
                # XXX: Okay, we need a better place to store modetypes.
                continue

            if modechar == m:

                supported_char = remoteirc.cmodes.get(name)

                if supported_char is None:
                    break

                if name not in whitelist:
                    log.debug("(%s) relay.get_supported_cmodes: skipping mode (%r, %r) because "
                              "it isn't a whitelisted (safe) mode for relay.",
                              irc.name, modechar, arg)
                    break

                if modechar in irc.prefixmodes:
                    # This is a prefix mode (e.g. +o). We must coerse the argument
                    # so that the target exists on the remote relay network.
                    log.debug("(%s) relay.get_supported_cmodes: coersing argument of (%r, %r) "
                              "for network %r.",
                              irc.name, modechar, arg, remoteirc.name)

                    if (not irc.proto.hasCap('can-spawn-clients')) and irc.pseudoclient and arg == irc.pseudoclient.uid:
                        # Skip modesync on the main PyLink client.
                        log.debug("(%s) relay.get_supported_cmodes: filtering prefix change (%r, %r) on Clientbot relayer",
                                  irc.name, name, arg)
                        break

                    # If the target is a remote user, get the real target
                    # (original user).
                    arg = get_orig_user(irc, arg, targetirc=remoteirc) or \
                        get_remote_user(irc, remoteirc, arg, spawn_if_missing=False)

                    if arg is None:
                        # Relay client for target user doesn't exist yet. Drop the mode.
                        break

                    log.debug("(%s) relay.get_supported_cmodes: argument found as (%r, %r) "
                              "for network %r.",
                              irc.name, modechar, arg, remoteirc.name)
                    oplist = remoteirc.channels[remotechan].prefixmodes[name]

                    log.debug("(%s) relay.get_supported_cmodes: list of %ss on %r is: %s",
                              irc.name, name, remotechan, oplist)

                    if prefix == '+' and arg in oplist:
                        # Don't set prefix modes that are already set.
                        log.debug("(%s) relay.get_supported_cmodes: skipping setting %s on %s/%s because it appears to be already set.",
                                  irc.name, name, arg, remoteirc.name)
                        break

                supported_char = remoteirc.cmodes.get(name)

            if supported_char:
                final_modepair = (prefix+supported_char, arg)
                if name in ('ban', 'banexception', 'invex') and not utils.isHostmask(arg):
                    # Don't add bans that don't match n!u@h syntax!
                    log.debug("(%s) relay.get_supported_cmodes: skipping mode (%r, %r) because it doesn't match nick!user@host syntax.",
                              irc.name, modechar, arg)
                    break

                # Don't set modes that are already set, to prevent floods on TS6
                # where the same mode can be set infinite times.
                if prefix == '+' and final_modepair in remoteirc.channels[remotechan].modes:
                    log.debug("(%s) relay.get_supported_cmodes: skipping setting mode (%r, %r) on %s%s because it appears to be already set.",
                              irc.name, supported_char, arg, remoteirc.name, remotechan)
                    break

                supported_modes.append(final_modepair)

    log.debug('(%s) relay.get_supported_cmodes: final modelist (sending to %s%s) is %s', irc.name, remoteirc.name, remotechan, supported_modes)
    return supported_modes

### EVENT HANDLERS

def handle_relay_whois(irc, source, command, args):
    """
    WHOIS handler for the relay plugin.
    """
    target = args['target']
    server = args['server']
    targetuser = irc.users[target]

    def wreply(num, text):
        """Convenience wrapper to return WHOIS replies."""
        # WHOIS replies are by convention prefixed with the target user's nick.
        text = '%s %s' % (targetuser.nick, text)
        irc.proto.numeric(server, num, source, text)

    def checkSendKey(infoline):
        """
        Returns whether we should send the given info line in WHOIS. This validates the
        corresponding configuration option for being either "all" or "opers"."""
        setting = conf.conf.get('relay', {}).get(infoline, '').lower()
        if setting == 'all':
            return True
        elif setting == 'opers' and irc.isOper(source, allowAuthed=False):
            return True
        return False

    # Get the real user for the WHOIS target.
    origuser = get_orig_user(irc, target)
    if origuser:
        homenet, uid = origuser
        realirc = world.networkobjects[homenet]
        realuser = realirc.users[uid]
        netname = realirc.getFullNetworkName()

        wreply(320, ":is a remote user connected via PyLink Relay. Home network: %s; "
                    "Home nick: %s" % (netname, realuser.nick))

        if checkSendKey('whois_show_accounts') and realuser.services_account:
            # Send account information if told to and the target is logged in.
            wreply(330, "%s :is logged in (on %s) as" % (realuser.services_account, netname))

        if checkSendKey('whois_show_server') and realirc.proto.hasCap('can-track-servers'):
            wreply(320, ":is actually connected via the following server:")
            realserver = realirc.getServer(uid)
            realserver = realirc.servers[realserver]
            wreply(312, "%s :%s" % (realserver.name, realserver.desc))

utils.add_hook(handle_relay_whois, 'PYLINK_CUSTOM_WHOIS')

def handle_operup(irc, numeric, command, args):
    """
    Handles setting oper types on relay clients during oper up.
    """
    newtype = '%s (on %s)' % (args['text'], irc.getFullNetworkName())
    for netname, user in relayusers[(irc.name, numeric)].items():
        log.debug('(%s) relay.handle_opertype: setting OPERTYPE of %s/%s to %s',
                  irc.name, user, netname, newtype)
        remoteirc = world.networkobjects[netname]
        remoteirc.users[user].opertype = newtype
utils.add_hook(handle_operup, 'CLIENT_OPERED')

def handle_join(irc, numeric, command, args):
    channel = args['channel']
    if not get_relay((irc.name, channel)):
        # No relay here, return.
        return
    ts = args['ts']
    users = set(args['users'])

    claim_passed = check_claim(irc, channel, numeric)
    current_chandata = irc.channels[channel]
    chandata = args.get('channeldata')
    log.debug('(%s) relay.handle_join: claim for %s on %s: %s', irc.name, numeric, channel, claim_passed)
    log.debug('(%s) relay.handle_join: old channel data %s', irc.name, chandata)
    log.debug('(%s) relay.handle_join: current channel data %s', irc.name, current_chandata)
    if chandata and not claim_passed:
        # If the server we're receiving an SJOIN from isn't in the claim list, undo ALL attempts
        # from it to burst modes.
        # This option can prevent things like /OJOIN abuse or split riding with oper override, but
        # has the side effect of causing all prefix modes on leaf links to be lost when networks
        # split and rejoin.
        modes = []
        for user in users:
            # XXX: Find the diff of the new and old mode lists of the channel. Not pretty, but I'd
            # rather not change the 'users' format of SJOIN just for this. -GL
            try:
                oldmodes = set(chandata.getPrefixModes(user))
            except KeyError:
                # User was never in channel. Treat their mode list as empty.
                oldmodes = set()
            newmodes = set(current_chandata.getPrefixModes(user))
            modediff = newmodes - oldmodes
            log.debug('(%s) relay.handle_join: mode diff for %s on %s: %s oldmodes=%s newmodes=%s',
                      irc.name, user, channel, modediff, oldmodes, newmodes)
            for modename in modediff:
                modechar = irc.cmodes.get(modename)
                if modechar:
                    modes.append(('-%s' % modechar, user))

        if modes:
            log.debug('(%s) relay.handle_join: reverting modes on BURST: %s', irc.name, irc.joinModes(modes))
            irc.proto.mode(irc.sid, channel, modes)

    relay_joins(irc, channel, users, ts, burst=False)
utils.add_hook(handle_join, 'JOIN')
utils.add_hook(handle_join, 'PYLINK_SERVICE_JOIN')

def handle_quit(irc, numeric, command, args):
    # Lock the user spawning mechanism before proceeding, since we're going to be
    # deleting client from the relayusers cache.
    log.debug('(%s) Grabbing spawnlocks[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    if spawnlocks[irc.name].acquire(timeout=TCONDITION_TIMEOUT):
        for netname, user in relayusers[(irc.name, numeric)].copy().items():
            remoteirc = world.networkobjects[netname]
            try:  # Try to quit the client. If this fails because they're missing, bail.
                remoteirc.proto.quit(user, args['text'])
            except LookupError:
                pass
        del relayusers[(irc.name, numeric)]
        spawnlocks[irc.name].release()

utils.add_hook(handle_quit, 'QUIT')

def handle_squit(irc, numeric, command, args):
    """
    Handles SQUITs over relay.
    """
    users = args['users']
    target = args['target']

    # Someone /SQUIT one of our relay subservers. Bad! Rejoin them!
    if target in relayservers[irc.name].values():
        sname = args['name']
        remotenet = sname.split('.', 1)[0]
        del relayservers[irc.name][remotenet]

        for userpair in relayusers:
            if userpair[0] == remotenet and irc.name in relayusers[userpair]:
                del relayusers[userpair][irc.name]

        remoteirc = world.networkobjects[remotenet]
        initialize_all(remoteirc)

    else:
        # Some other netsplit happened on the network, we'll have to fake
        # some *.net *.split quits for that.
        for user in users:
            log.debug('(%s) relay.handle_squit: sending handle_quit on %s', irc.name, user)

            try:  # Allow netsplit hiding to be toggled
                show_splits = conf.conf['relay']['show_netsplits']
            except KeyError:
                show_splits = False

            text = '*.net *.split'
            if show_splits:
                uplink = args['uplink']
                try:
                    text = '%s %s' % (irc.servers[uplink].name, args['name'])
                except (KeyError, AttributeError):
                    log.warning("(%s) relay.handle_squit: Failed to get server name for %s",
                                irc.name, uplink)

            handle_quit(irc, user, command, {'text': text})

utils.add_hook(handle_squit, 'SQUIT')

def handle_nick(irc, numeric, command, args):
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = world.networkobjects[netname]
        newnick = normalize_nick(remoteirc, irc.name, args['newnick'], uid=user)
        if remoteirc.users[user].nick != newnick:
            remoteirc.proto.nick(user, newnick)
utils.add_hook(handle_nick, 'NICK')

def handle_part(irc, numeric, command, args):
    channels = args['channels']
    text = args['text']
    # Don't allow the PyLink client PARTing to be relayed.
    if numeric == irc.pseudoclient.uid:
        # For clientbot: treat forced parts to the bot as clearchan, and attempt to rejoin only
        # if it affected a relay.
        if not irc.proto.hasCap('can-spawn-clients'):
            for channel in [c for c in channels if get_relay((irc.name, c))]:
                for user in irc.channels[channel].users:
                    if (not irc.isInternalClient(user)) and (not isRelayClient(irc, user)):
                        irc.callHooks([irc.sid, 'CLIENTBOT_SERVICE_KICKED', {'channel': channel, 'target': user,
                                       'text': 'Clientbot was force parted (Reason: %s)' % text or 'None',
                                       'parse_as': 'KICK'}])
                irc.proto.join(irc.pseudoclient.uid, channel)

            return
        return

    for channel in channels:
        for netname, user in relayusers[(irc.name, numeric)].copy().items():
            remoteirc = world.networkobjects[netname]
            remotechan = get_remote_channel(irc, remoteirc, channel)
            if remotechan is None:
                continue
            remoteirc.proto.part(user, remotechan, text)
            if not remoteirc.users[user].channels:
                remoteirc.proto.quit(user, 'Left all shared channels.')
                del relayusers[(irc.name, numeric)][remoteirc.name]
utils.add_hook(handle_part, 'PART')

def handle_messages(irc, numeric, command, args):
    notice = (command in ('NOTICE', 'PYLINK_SELF_NOTICE'))
    target = args['target']
    text = args['text']
    if irc.isInternalClient(numeric) and irc.isInternalClient(target):
        # Drop attempted PMs between internal clients (this shouldn't happen,
        # but whatever).
        return
    elif (numeric in irc.servers) and (not notice):
        log.debug('(%s) relay.handle_messages: dropping PM from server %s to %s',
                  irc.name, numeric, target)
        return

    relay = get_relay((irc.name, target))
    remoteusers = relayusers[(irc.name, numeric)]

    # HACK: Don't break on sending to @#channel or similar. TODO: This should really
    # be handled more neatly in core.
    try:
        prefix, target = target.split('#', 1)
    except ValueError:
        prefix = ''
    else:
        target = '#' + target

    if utils.isChannel(target):
        for name, remoteirc in world.networkobjects.copy().items():
            real_target = get_remote_channel(irc, remoteirc, target)

            # Don't relay anything back to the source net, or to disconnected networks
            # and networks without a relay for this channel.
            if irc.name == name or (not remoteirc.connected.is_set()) or (not real_target) \
                    or (not irc.connected.is_set()):
                continue

            user = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)

            if not user:
                if not (irc.serverdata.get('relay_weird_senders',
                        conf.conf.get('relay', {}).get('accept_weird_senders', True))):
                    log.debug("(%s) Dropping message for %s from user-less sender %s", irc.name,
                              real_target, numeric)
                    continue
                # No relay clone exists for the sender; route the message through our
                # main client (or SID for notices).

                # Skip "from:" formatting for servers; it's messy with longer hostnames.
                # Also skip this formatting for servicebot relaying.
                if numeric not in irc.servers and not irc.getServiceBot(numeric):
                    displayedname = irc.getFriendlyName(numeric)
                    real_text = '<%s/%s> %s' % (displayedname, irc.name, text)
                else:
                    real_text = text

                # XXX: perhaps consider routing messages from the server where
                # possible - most IRCds except TS6 (charybdis, ratbox, hybrid)
                # allow this.
                try:
                    user = get_remote_sid(remoteirc, irc, spawn_if_missing=False) \
                        if notice else remoteirc.pseudoclient.uid
                    if not user:
                        continue
                except AttributeError:
                    # Remote main client hasn't spawned yet. Drop the message.
                    continue
                else:
                    if remoteirc.pseudoclient.uid not in remoteirc.users:
                        # Remote UID is ghosted, drop message.
                        continue

            else:
                real_text = text

            real_target = prefix + real_target
            log.debug('(%s) relay.handle_messages: sending message to %s from %s on behalf of %s',
                      irc.name, real_target, user, numeric)

            try:
                if notice:
                    remoteirc.proto.notice(user, real_target, real_text)
                else:
                    remoteirc.proto.message(user, real_target, real_text)
            except LookupError:
                # Our relay clone disappeared while we were trying to send the message.
                # This is normally due to a nick conflict with the IRCd.
                log.warning("(%s) relay: Relay client %s on %s was killed while "
                            "trying to send a message through it!", irc.name,
                            remoteirc.name, user)
                continue

    else:
        # Get the real user that the PM was meant for
        origuser = get_orig_user(irc, target)
        if origuser is None:  # Not a relay client, return
            return
        homenet, real_target = origuser

        # For PMs, we must be on a common channel with the target.
        # Otherwise, the sender doesn't have a client representing them
        # on the remote network, and we won't have anything to send our
        # messages from.
        if homenet not in remoteusers.keys():
            irc.msg(numeric, 'You must be in a common channel '
                      'with %r in order to send messages.' % \
                      irc.users[target].nick, notice=True)
            return
        remoteirc = world.networkobjects[homenet]

        if (not remoteirc.proto.hasCap('can-spawn-clients')) and not conf.conf.get('relay', {}).get('allow_clientbot_pms'):
            irc.msg(numeric, 'Private messages to users connected via Clientbot have '
                    'been administratively disabled.', notice=True)
            return

        user = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)

        try:
            if notice:
                remoteirc.proto.notice(user, real_target, text)
            else:
                remoteirc.proto.message(user, real_target, text)
        except LookupError:
            # Our relay clone disappeared while we were trying to send the message.
            # This is normally due to a nick conflict with the IRCd.
            log.warning("(%s) relay: Relay client %s on %s was killed while "
                        "trying to send a message through it!", irc.name,
                        remoteirc.name, user)
            return

for cmd in ('PRIVMSG', 'NOTICE', 'PYLINK_SELF_NOTICE', 'PYLINK_SELF_PRIVMSG'):
    utils.add_hook(handle_messages, cmd)

def handle_kick(irc, source, command, args):
    channel = args['channel']
    target = args['target']
    text = args['text']
    kicker = source
    relay = get_relay((irc.name, channel))

    # Special case for clientbot: treat kicks to the PyLink service bot as channel clear.
    if (not irc.proto.hasCap('can-spawn-clients')) and irc.pseudoclient and target == irc.pseudoclient.uid:
        for user in irc.channels[channel].users:
            if (not irc.isInternalClient(user)) and (not isRelayClient(irc, user)):
                reason = "Clientbot kicked by %s (Reason: %s)" % (irc.getFriendlyName(source), text)
                irc.callHooks([irc.sid, 'CLIENTBOT_SERVICE_KICKED', {'channel': channel, 'target': user,
                               'text': reason, 'parse_as': 'KICK'}])

        return

    # Don't relay kicks to protected service bots.
    if relay is None or irc.getServiceBot(target):
        return

    origuser = get_orig_user(irc, target)
    for name, remoteirc in world.networkobjects.copy().items():
        if irc.name == name or not remoteirc.connected.is_set():
            continue
        remotechan = get_remote_channel(irc, remoteirc, channel)
        log.debug('(%s) relay.handle_kick: remotechan for %s on %s is %s', irc.name, channel, name, remotechan)
        if remotechan is None:
            continue
        real_kicker = get_remote_user(irc, remoteirc, kicker, spawn_if_missing=False)
        log.debug('(%s) relay.handle_kick: real kicker for %s on %s is %s', irc.name, kicker, name, real_kicker)
        if not isRelayClient(irc, target):
            log.debug('(%s) relay.handle_kick: target %s is NOT an internal client', irc.name, target)
            # Both the target and kicker are external clients; i.e.
            # they originate from the same network. We won't have
            # to filter this; the uplink IRCd will handle it appropriately,
            # and we'll just follow.
            real_target = get_remote_user(irc, remoteirc, target, spawn_if_missing=False)
            log.debug('(%s) relay.handle_kick: real target for %s is %s', irc.name, target, real_target)
        else:
            log.debug('(%s) relay.handle_kick: target %s is an internal client, going to look up the real user', irc.name, target)
            real_target = get_orig_user(irc, target, targetirc=remoteirc)
            if not check_claim(irc, channel, kicker):
                log.debug('(%s) relay.handle_kick: kicker %s is not opped... We should rejoin the target user %s', irc.name, kicker, real_target)
                # Home network is not in the channel's claim AND the kicker is not
                # opped. We won't propograte the kick then.
                # TODO: make the check slightly more advanced: i.e. halfops can't
                # kick ops, admins can't kick owners, etc.
                modes = get_prefix_modes(remoteirc, irc, remotechan, real_target)
                # Join the kicked client back with its respective modes.
                irc.proto.sjoin(irc.sid, channel, [(modes, target)])
                if kicker in irc.users:
                    log.info('(%s) relay: Blocked KICK (reason %r) from %s/%s to relay client %s on %s.',
                             irc.name, args['text'], irc.users[source].nick, irc.name,
                             remoteirc.users[real_target].nick, channel)
                    irc.msg(kicker, "This channel is claimed; your kick to "
                                    "%s has been blocked because you are not "
                                    "(half)opped." % channel, notice=True)
                else:
                    log.info('(%s) relay: Blocked KICK (reason %r) from server %s to relay client %s/%s on %s.',
                             irc.name, args['text'], irc.servers[source].name,
                             remoteirc.users[real_target].nick, remoteirc.name, channel)
                return

        if not real_target:
            continue
        # Propogate the kick!
        if real_kicker:
            log.debug('(%s) relay.handle_kick: Kicking %s from channel %s via %s on behalf of %s/%s', irc.name, real_target, remotechan,real_kicker, kicker, irc.name)
            remoteirc.proto.kick(real_kicker, remotechan, real_target, args['text'])
        else:
            # Kick originated from a server, or the kicker isn't in any
            # common channels with the target relay network.
            rsid = get_remote_sid(remoteirc, irc)
            log.debug('(%s) relay.handle_kick: Kicking %s from channel %s via %s on behalf of %s/%s', irc.name, real_target, remotechan, rsid, kicker, irc.name)
            if not irc.proto.hasCap('can-spawn-clients'):
                # Special case for clientbot: no kick prefixes are needed.
                text = args['text']
            else:
                try:
                    if kicker in irc.servers:
                        kname = irc.servers[kicker].name
                    else:
                        kname = irc.users.get(kicker).nick
                    text = "(%s/%s) %s" % (kname, irc.name, args['text'])
                except AttributeError:
                    text = "(<unknown kicker>@%s) %s" % (irc.name, args['text'])
            rsid = rsid or remoteirc.sid  # Fall back to the main PyLink SID if get_remote_sid() fails
            remoteirc.proto.kick(rsid, remotechan, real_target, text)

        # If the target isn't on any channels, quit them.
        if remoteirc != irc and (not remoteirc.users[real_target].channels) and not origuser:
            del relayusers[(irc.name, target)][remoteirc.name]
            remoteirc.proto.quit(real_target, 'Left all shared channels.')

    if origuser and not irc.users[target].channels:
        del relayusers[origuser][irc.name]
        irc.proto.quit(target, 'Left all shared channels.')

utils.add_hook(handle_kick, 'KICK')

def handle_chgclient(irc, source, command, args):
    target = args['target']
    if args.get('newhost'):
        field = 'HOST'
        text = args['newhost']
    elif args.get('newident'):
        field = 'IDENT'
        text = args['newident']
    elif args.get('newgecos'):
        field = 'GECOS'
        text = args['newgecos']
    if field:
        for netname, user in relayusers[(irc.name, target)].items():
            remoteirc = world.networkobjects[netname]
            try:
                if field == 'HOST':
                    newtext = normalize_host(remoteirc, text)
                else:  # Don't overwrite the original text variable on every iteration.
                    newtext = text
                remoteirc.proto.updateClient(user, field, newtext)
            except NotImplementedError:  # IRCd doesn't support changing the field we want
                log.debug('(%s) relay.handle_chgclient: Ignoring changing field %r of %s on %s (for %s/%s);'
                          ' remote IRCd doesn\'t support it', irc.name, field,
                          user, netname, target, irc.name)
                continue

for c in ('CHGHOST', 'CHGNAME', 'CHGIDENT'):
    utils.add_hook(handle_chgclient, c)

def handle_mode(irc, numeric, command, args):
    target = args['target']
    modes = args['modes']

    for name, remoteirc in world.networkobjects.copy().items():
        if irc.name == name or not remoteirc.connected.is_set():
            continue

        if utils.isChannel(target):
            # Use the old state of the channel to check for CLAIM access.
            oldchan = args.get('channeldata')

            if check_claim(irc, target, numeric, chanobj=oldchan):
                remotechan = get_remote_channel(irc, remoteirc, target)
                supported_modes = get_supported_cmodes(irc, remoteirc, target, modes)
                if supported_modes:
                    # Check if the sender is a user with a relay client; otherwise relay the mode
                    # from the corresponding server.
                    u = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)
                    if u:
                        remoteirc.proto.mode(u, remotechan, supported_modes)
                    else:
                        rsid = get_remote_sid(remoteirc, irc)
                        rsid = rsid or remoteirc.sid
                        remoteirc.proto.mode(rsid, remotechan, supported_modes)
            else:  # Mode change blocked by CLAIM.
                reversed_modes = irc.reverseModes(target, modes, oldobj=oldchan)
                log.debug('(%s) relay.handle_mode: Reversing mode changes of %r with %r (CLAIM).',
                          irc.name, modes, reversed_modes)
                if reversed_modes:
                    irc.proto.mode(irc.sid, target, reversed_modes)
                break

        else:
            # Set hideoper on remote opers, to prevent inflating
            # /lusers and various /stats
            hideoper_mode = remoteirc.umodes.get('hideoper')
            modes = get_supported_umodes(irc, remoteirc, modes)

            if hideoper_mode:
                if ('+o', None) in modes:
                    modes.append(('+%s' % hideoper_mode, None))
                elif ('-o', None) in modes:
                    modes.append(('-%s' % hideoper_mode, None))

            remoteuser = get_remote_user(irc, remoteirc, target, spawn_if_missing=False)

            if remoteuser and modes:
                remoteirc.proto.mode(remoteuser, remoteuser, modes)

utils.add_hook(handle_mode, 'MODE')

def handle_topic(irc, numeric, command, args):
    channel = args['channel']
    oldtopic = args.get('oldtopic')
    topic = args['text']
    if check_claim(irc, channel, numeric):
        for name, remoteirc in world.networkobjects.copy().items():
            if irc.name == name or not remoteirc.connected.is_set():
                continue

            remotechan = get_remote_channel(irc, remoteirc, channel)
            # Don't send if the remote topic is the same as ours.
            if remotechan is None or topic == remoteirc.channels[remotechan].topic:
                continue
            # This might originate from a server too.
            remoteuser = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)
            if remoteuser:
                remoteirc.proto.topic(remoteuser, remotechan, topic)
            else:
                rsid = get_remote_sid(remoteirc, irc)
                remoteirc.proto.topicBurst(rsid, remotechan, topic)
    elif oldtopic:  # Topic change blocked by claim.
        irc.proto.topicBurst(irc.sid, channel, oldtopic)

utils.add_hook(handle_topic, 'TOPIC')

def handle_kill(irc, numeric, command, args):
    target = args['target']
    userdata = args['userdata']

    # Try to find the original client of the target being killed
    if userdata and hasattr(userdata, 'remote'):
        realuser = userdata.remote
    else:
        realuser = get_orig_user(irc, target)

    log.debug('(%s) relay.handle_kill: realuser is %r', irc.name, realuser)

    # Target user was remote:
    if realuser and realuser[0] != irc.name:
        # We don't allow killing over the relay, so we must respawn the affected
        # client and rejoin it to its channels.
        del relayusers[realuser][irc.name]
        remoteirc = world.networkobjects[realuser[0]]
        for remotechan in remoteirc.users[realuser[1]].channels:
            localchan = get_remote_channel(remoteirc, irc, remotechan)
            if localchan:
                modes = get_prefix_modes(remoteirc, irc, remotechan, realuser[1])
                log.debug('(%s) relay.handle_kill: userpair: %s, %s', irc.name, modes, realuser)
                client = get_remote_user(remoteirc, irc, realuser[1], times_tagged=1)
                irc.proto.sjoin(get_remote_sid(irc, remoteirc), localchan, [(modes, client)])

        if userdata and numeric in irc.users:
            log.info('(%s) relay.handle_kill: Blocked KILL (reason %r) from %s to relay client %s/%s.',
                     irc.name, args['text'], irc.users[numeric].nick,
                     remoteirc.users[realuser[1]].nick, realuser[0])
            irc.msg(numeric, "Your kill to %s has been blocked "
                             "because PyLink does not allow killing"
                             " users over the relay at this time." % \
                             userdata.nick, notice=True)
        else:
            log.info('(%s) relay.handle_kill: Blocked KILL (reason %r) from server %s to relay client %s/%s.',
                     irc.name, args['text'], irc.servers[numeric].name,
                     remoteirc.users[realuser[1]].nick, realuser[0])

    # Target user was local.
    else:
        # IMPORTANT: some IRCds (charybdis) don't send explicit QUIT messages
        # for locally killed clients, while others (inspircd) do!
        # If we receive a user object in 'userdata' instead of None, it means
        # that the KILL hasn't been handled by a preceding QUIT message.
        if userdata:
            handle_quit(irc, target, 'KILL', {'text': args['text']})

utils.add_hook(handle_kill, 'KILL')

def handle_away(irc, numeric, command, args):
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = world.networkobjects[netname]
        remoteirc.proto.away(user, args['text'])
utils.add_hook(handle_away, 'AWAY')

def handle_invite(irc, source, command, args):
    target = args['target']
    channel = args['channel']
    if isRelayClient(irc, target):
        remotenet, remoteuser = get_orig_user(irc, target)
        remoteirc = world.networkobjects[remotenet]
        remotechan = get_remote_channel(irc, remoteirc, channel)
        remotesource = get_remote_user(irc, remoteirc, source, spawn_if_missing=False)
        if remotesource is None:
            irc.msg(source, 'You must be in a common channel '
                                   'with %s to invite them to channels.' % \
                                   irc.users[target].nick,
                                   notice=True)
        elif remotechan is None:
            irc.msg(source, 'You cannot invite someone to a '
                                   'channel not on their network!',
                                   notice=True)
        else:
            remoteirc.proto.invite(remotesource, remoteuser,
                                         remotechan)
utils.add_hook(handle_invite, 'INVITE')

def handle_endburst(irc, numeric, command, args):
    if numeric == irc.uplink:
        initialize_all(irc)
utils.add_hook(handle_endburst, "ENDBURST")

def handle_services_login(irc, numeric, command, args):
    """
    Relays services account changes as a hook, for integration with plugins like Automode.
    """
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = world.networkobjects[netname]
        remoteirc.callHooks([user, 'PYLINK_RELAY_SERVICES_LOGIN', args])
utils.add_hook(handle_services_login, 'CLIENT_SERVICES_LOGIN')

def handle_disconnect(irc, numeric, command, args):
    """Handles IRC network disconnections (internal hook)."""

    # Quit all of our users' representations on other nets, and remove
    # them from our relay clients index.
    log.debug('(%s) Grabbing spawnlocks[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    if spawnlocks[irc.name].acquire(timeout=TCONDITION_TIMEOUT):
        for k, v in relayusers.copy().items():
            if irc.name in v:
                del relayusers[k][irc.name]
            if k[0] == irc.name:
                del relayusers[k]
        spawnlocks[irc.name].release()

    # SQUIT all relay pseudoservers spawned for us, and remove them
    # from our relay subservers index.
    log.debug('(%s) Grabbing spawnlocks_servers[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    if spawnlocks_servers[irc.name].acquire(timeout=TCONDITION_TIMEOUT):
        for name, ircobj in world.networkobjects.copy().items():
            if name != irc.name:
                try:
                    rsid = relayservers[name][irc.name]
                except KeyError:
                    continue
                else:
                    ircobj.proto.squit(ircobj.sid, rsid, text='Relay network lost connection.')

            if irc.name in relayservers[name]:
                del relayservers[name][irc.name]

        try:
            del relayservers[irc.name]
        except KeyError:  # Already removed; ignore.
            pass

        spawnlocks_servers[irc.name].release()

    # Announce the disconnects to every leaf channel where the disconnected network is the owner
    announcement = conf.conf.get('relay', {}).get('disconnect_announcement')
    log.debug('(%s) relay: last connection successful: %s', irc.name, args.get('was_successful'))
    if announcement and args.get('was_successful'):
        for chanpair, entrydata in db.items():
            log.debug('(%s) relay: Looking up %s', irc.name, chanpair)
            if chanpair[0] == irc.name:
                for leaf in entrydata['links']:
                    log.debug('(%s) relay: Announcing disconnect to %s%s', irc.name,
                              leaf[0], leaf[1])
                    remoteirc = world.networkobjects.get(leaf[0])
                    if remoteirc and remoteirc.connected.is_set():
                        text = string.Template(announcement).safe_substitute(
                            {'homenetwork': irc.name, 'homechannel': chanpair[1],
                             'network': remoteirc.name, 'channel': leaf[1]})
                        remoteirc.msg(leaf[1], text, loopback=False)

utils.add_hook(handle_disconnect, "PYLINK_DISCONNECT")

def nick_collide(irc, target):
    """
    Handles nick collisions on relay clients and attempts to fix nicks.
    """
    remotenet, remoteuser = get_orig_user(irc, target)
    remoteirc = world.networkobjects[remotenet]

    nick = remoteirc.users[remoteuser].nick

    # Force a tagged nick by setting times_tagged to 1.
    newnick = normalize_nick(irc, remotenet, nick, times_tagged=1)
    log.debug('(%s) relay.nick_collide: Fixing nick of relay client %r (%s) to %s',
              irc.name, target, nick, newnick)
    irc.proto.nick(target, newnick)

def handle_save(irc, numeric, command, args):
    target = args['target']

    if isRelayClient(irc, target):
        # Nick collision!
        # It's one of our relay clients; try to fix our nick to the next
        # available normalized nick.
        nick_collide(irc, target)
    else:
        # Somebody else on the network (not a PyLink client) had a nick collision;
        # relay this as a nick change appropriately.
        handle_nick(irc, target, 'SAVE', {'oldnick': None, 'newnick': target})

utils.add_hook(handle_save, "SAVE")

def handle_svsnick(irc, numeric, command, args):
    """
    Handles forced nick change attempts to relay clients, tagging their nick.
    """
    target = args['target']

    if isRelayClient(irc, target):
        nick_collide(irc, target)

utils.add_hook(handle_svsnick, "SVSNICK")

### PUBLIC COMMANDS

def create(irc, source, args):
    """<channel>

    Opens up the given channel over PyLink Relay."""
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1: channel.")
        return
    if not utils.isChannel(channel):
        irc.error('Invalid channel %r.' % channel)
        return
    if not irc.proto.hasCap('can-host-relay'):
        irc.error('Clientbot networks cannot be used to host a relay.')
        return
    if source not in irc.channels[channel].users:
        irc.error('You must be in %r to complete this operation.' % channel)
        return

    permissions.checkPermissions(irc, source, ['relay.create'])

    # Check to see whether the channel requested is already part of a different
    # relay.
    localentry = get_relay((irc.name, channel))
    if localentry:
        irc.error('Channel %r is already part of a relay.' % channel)
        return

    creator = irc.getHostmask(source)
    # Create the relay database entry with the (network name, channel name)
    # pair - this is just a dict with various keys.
    db[(irc.name, channel)] = {'claim': [irc.name], 'links': set(),
                               'blocked_nets': set(), 'creator': creator,
                               'ts': time.time()}
    log.info('(%s) relay: Channel %s created by %s.', irc.name, channel, creator)
    initialize_channel(irc, channel)
    irc.reply('Done.')
create = utils.add_cmd(create, featured=True)

def stop_relay(entry):
    """Internal function to deinitialize a relay link and its leaves."""
    network, channel = entry
    # Iterate over all the channel links and deinitialize them.
    for link in db[entry]['links']:
        remove_channel(world.networkobjects.get(link[0]), link[1])
    remove_channel(world.networkobjects.get(network), channel)

def destroy(irc, source, args):
    """[<home network>] <channel>

    Removes the given channel from the PyLink Relay, delinking all networks linked to it. If the home network is given and you are logged in as admin, this can also remove relay channels from other networks."""
    try:  # Two args were given: first one is network name, second is channel.
        channel = irc.toLower(args[1])
        network = args[0]
    except IndexError:
        try:  # One argument was given; assume it's just the channel.
            channel = irc.toLower(args[0])
            network = irc.name
        except IndexError:
            irc.error("Not enough arguments. Needs 1-2: channel, network (optional).")
            return

    if not utils.isChannel(channel):
        irc.error('Invalid channel %r.' % channel)
        return

    # Check for different permissions based on whether we're destroying a local channel or
    # a remote one.
    if network == irc.name:
        permissions.checkPermissions(irc, source, ['relay.destroy'])
    else:
        permissions.checkPermissions(irc, source, ['relay.destroy.remote'])

    entry = (network, channel)
    if entry in db:
        stop_relay(entry)
        del db[entry]

        log.info('(%s) relay: Channel %s destroyed by %s.', irc.name,
                 channel, irc.getHostmask(source))
        irc.reply('Done.')
    else:
        irc.error("No such channel %r exists. If you're trying to delink a channel from "
                  "another network, use the DESTROY command." % channel)
        return
destroy = utils.add_cmd(destroy, featured=True)

@utils.add_cmd
def purge(irc, source, args):
    """<network>

    Destroys all links relating to the target network."""
    permissions.checkPermissions(irc, source, ['relay.purge'])
    try:
        network = args[0]
    except IndexError:
        irc.error("Not enough arguments. Needs 1: network.")
        return

    count = 0

    for entry in db.copy():
        # Entry was owned by the target network; remove it
        if entry[0] == network:
            count += 1
            stop_relay(entry)
            del db[entry]
        else:
            # Drop leaf channels involving the target network
            for link in db[entry]['links'].copy():
                if link[0] == network:
                    count += 1
                    remove_channel(world.networkobjects.get(network), link[1])
                    db[entry]['links'].remove(link)

    irc.reply("Done. Purged %s entries involving the network %s." % (count, network))

link_parser = utils.IRCParser()
link_parser.add_argument('remotenet')
link_parser.add_argument('channel')
link_parser.add_argument('localchannel', nargs='?')
link_parser.add_argument("-f", "--force", action='store_true')
def link(irc, source, args):
    """<remotenet> <channel> [<local channel>] [-f/--force]

    Links the specified channel on \x02remotenet\x02 over PyLink Relay as \x02local channel\x02.
    If \x02local channel\x02 is not specified, it defaults to the same name as \x02channel\x02.

    If the --force option is given, this command will bypass checks for TS and whether the target
    network is alive, and link the channel anyways."""
    args = link_parser.parse_args(args)

    # Normalize channel case
    channel = irc.toLower(args.channel)
    localchan = irc.toLower(args.localchannel or args.channel)
    remotenet = args.remotenet

    for c in (channel, localchan):
        if not utils.isChannel(c):
            irc.error('Invalid channel %r.' % c)
            return

    if remotenet == irc.name:
        irc.error('Cannot link two channels on the same network.')
        return

    if source not in irc.channels[localchan].users:
        # Caller is not in the requested channel.
        log.debug('(%s) Source not in channel %s; protoname=%s', irc.name, localchan, irc.protoname)
        if irc.protoname == 'clientbot':
            # Special case for Clientbot: join the requested channel first, then
            # require that the caller be opped.
            if localchan not in irc.pseudoclient.channels:
                irc.proto.join(irc.pseudoclient.uid, localchan)
                irc.reply('Joining %r now to check for op status; please run this command again after I join.' % localchan)
                return
            elif not irc.channels[localchan].isOpPlus(source):
                irc.error('You must be opped in %r to complete this operation.' % localchan)
                return

        else:
            irc.error('You must be in %r to complete this operation.' % localchan)
            return

    permissions.checkPermissions(irc, source, ['relay.link'])

    if remotenet not in world.networkobjects:
        irc.error('No network named %r exists.' % remotenet)
        return
    localentry = get_relay((irc.name, localchan))

    if localentry:
        irc.error('Channel %r is already part of a relay.' % localchan)
        return

    try:
        entry = db[(remotenet, channel)]
    except KeyError:
        irc.error('No such relay %r exists.' % args.channel)
        return
    else:
        if irc.name in entry['blocked_nets']:
            irc.error('Access denied (target channel is not open to links).')
            return
        for link in entry['links']:
            if link[0] == irc.name:
                irc.error("Remote channel '%s%s' is already linked here "
                          "as %r." % (remotenet, args.channel, link[1]))
                return

        if args.force:
            permissions.checkPermissions(irc, source, ['relay.link.force'])
            log.info("(%s) relay: Forcing link %s%s -> %s%s", irc.name, irc.name, localchan, remotenet,
                     args.channel)
        else:
            if not world.networkobjects[remotenet].connected.is_set():
                log.debug('(%s) relay: Blocking link request %s%s -> %s%s because the target '
                          'network is down', irc.name, irc.name, localchan, remotenet, args.channel)
                irc.error("The target network %s is not connected; refusing to link (you may be "
                          "able to override this with the --force option)." % remotenet)
                return

            our_ts = irc.channels[localchan].ts
            their_ts = world.networkobjects[remotenet].channels[channel].ts
            if (our_ts < their_ts) and irc.proto.hasCap('has-ts'):
                log.debug('(%s) relay: Blocking link request %s%s -> %s%s due to bad TS (%s < %s)', irc.name,
                          irc.name, localchan, remotenet, args.channel, our_ts, their_ts)
                irc.error("The channel creation date (TS) on %s (%s) is lower than the target "
                          "channel's (%s); refusing to link. You should clear the local channel %s first "
                          "before linking, or use a different local channel (you may be able to "
                          "override this with the --force option)." % (localchan, our_ts, their_ts, localchan))
                return

        entry['links'].add((irc.name, localchan))
        log.info('(%s) relay: Channel %s linked to %s%s by %s.', irc.name,
                 localchan, remotenet, args.channel, irc.getHostmask(source))
        initialize_channel(irc, localchan)
        irc.reply('Done.')
link = utils.add_cmd(link, featured=True)

def delink(irc, source, args):
    """<local channel> [<network>]

    Delinks the given channel from PyLink Relay. \x02network\x02 must and can only be specified if you are on the host network for the channel given, and allows you to pick which network to delink.
    To remove a relay channel entirely, use the 'destroy' command instead."""
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: channel, remote netname (optional).")
        return
    try:
        remotenet = args[1]
    except IndexError:
        remotenet = None

    permissions.checkPermissions(irc, source, ['relay.delink'])

    if not utils.isChannel(channel):
        irc.error('Invalid channel %r.' % channel)
        return
    entry = get_relay((irc.name, channel))
    if entry:
        if entry[0] == irc.name:  # We own this channel.
            if not remotenet:
                irc.error("You must select a network to "
                          "delink, or use the 'destroy' command to remove "
                          "this relay entirely (it was created on the current "
                          "network).")
                return
            else:
                for link in db[entry]['links'].copy():
                    if link[0] == remotenet:
                        remove_channel(world.networkobjects.get(remotenet), link[1])
                        db[entry]['links'].remove(link)
        else:
            remove_channel(irc, channel)
            db[entry]['links'].remove((irc.name, channel))
        irc.reply('Done.')
        log.info('(%s) relay: Channel %s delinked from %s%s by %s.', irc.name,
                 channel, entry[0], entry[1], irc.getHostmask(source))
    else:
        irc.error('No such relay %r.' % channel)
delink = utils.add_cmd(delink, featured=True)

def linked(irc, source, args):
    """[<network>]

    Returns a list of channels shared across PyLink Relay. If \x02network\x02 is given, filters output to channels linked to the given network."""

    permissions.checkPermissions(irc, source, ['relay.linked'])

    # Only show remote networks that are marked as connected.
    remote_networks = [netname for netname, ircobj in world.networkobjects.copy().items()
                       if ircobj.connected.is_set()]

    # But remove the current network from the list, so that it isn't shown twice.
    remote_networks.remove(irc.name)

    remote_networks.sort()

    s = 'Connected networks: \x02%s\x02 %s' % (irc.name, ' '.join(remote_networks))
    # Always reply in private to prevent floods.
    irc.reply(s, private=True)

    net = ''
    try:
        net = args[0]
    except:
        pass
    else:
        irc.reply("Showing channels linked to %s:" % net, private=True)

    # Sort the list of shared channels when displaying
    for k, v in sorted(db.items()):
        # Skip if we're filtering by network and the network given isn't relayed
        # to the channel.
        if net and not (net == k[0] or net in [link[0] for link in v['links']]):
            continue

        # Bold each network/channel name pair
        s = '\x02%s%s\x02 ' % k
        remoteirc = world.networkobjects.get(k[0])
        channel = k[1]  # Get the channel name from the network/channel pair

        if remoteirc and channel in remoteirc.channels:
            c = remoteirc.channels[channel]
            if ('s', None) in c.modes or ('p', None) in c.modes:
                # Only show secret channels to opers or those in the channel, and tag them as
                # [secret].
                localchan = get_remote_channel(remoteirc, irc, channel)
                if irc.isOper(source) or (localchan and source in irc.channels[localchan].users):
                    s += '\x02[secret]\x02 '
                else:
                    continue

        if v['links']:
            # Sort, join up and output all the linked channel names. Silently drop
            # entries for disconnected networks.
            s += ' '.join([''.join(link) for link in sorted(v['links']) if link[0] in world.networkobjects
                           and world.networkobjects[link[0]].connected.is_set()])

        else:  # Unless it's empty; then, well... just say no relays yet.
            s += '(no relays yet)'

        irc.reply(s, private=True)

        if irc.isOper(source):
            s = ''

            # If the caller is an oper, we can show the hostmasks of people
            # that created all the available channels (Janus does this too!!)
            creator = v.get('creator')
            if creator:
                # But only if the value actually exists (old DBs will have it
                # missing).
                s += ' by \x02%s\x02' % creator

            # Ditto for creation date
            ts = v.get('ts')
            if ts:
                s += ' on %s' % time.ctime(ts)

            if s:  # Indent to make the list look nicer
                irc.reply('    Channel created%s.' % s, private=True)
linked = utils.add_cmd(linked, featured=True)

@utils.add_cmd
def linkacl(irc, source, args):
    """ALLOW|DENY|LIST <channel> <remotenet>

    Allows blocking / unblocking certain networks from linking to a relayed channel, based on a blacklist.

    LINKACL LIST returns a list of blocked networks for a channel, while the ALLOW and DENY subcommands allow manipulating this blacklist."""
    missingargs = "Not enough arguments. Needs 2-3: subcommand (ALLOW/DENY/LIST), channel, remote network (for ALLOW/DENY)."

    try:
        cmd = args[0].lower()
        channel = irc.toLower(args[1])
    except IndexError:
        irc.error(missingargs)
        return
    if not utils.isChannel(channel):
        irc.error('Invalid channel %r.' % channel)
        return
    relay = get_relay((irc.name, channel))
    if not relay:
        irc.error('No such relay %r exists.' % channel)
        return
    if cmd == 'list':
        permissions.checkPermissions(irc, source, ['relay.linkacl.view'])
        s = 'Blocked networks for \x02%s\x02: \x02%s\x02' % (channel, ', '.join(db[relay]['blocked_nets']) or '(empty)')
        irc.reply(s)
        return

    permissions.checkPermissions(irc, source, ['relay.linkacl'])
    try:
        remotenet = args[2]
    except IndexError:
        irc.error(missingargs)
        return
    if cmd == 'deny':
        db[relay]['blocked_nets'].add(remotenet)
        irc.reply('Done.')
    elif cmd == 'allow':
        try:
            db[relay]['blocked_nets'].remove(remotenet)
        except KeyError:
            irc.error('Network %r is not on the blacklist for %r.' % (remotenet, channel))
        else:
            irc.reply('Done.')
    else:
        irc.error('Unknown subcommand %r: valid ones are ALLOW, DENY, and LIST.' % cmd)

@utils.add_cmd
def showuser(irc, source, args):
    """<user>

    Shows relay data about the given user. This supplements the 'showuser' command in the 'commands' plugin, which provides more general information."""
    try:
        target = args[0]
    except IndexError:
        # No errors here; showuser from the commands plugin already does this
        # for us.
        return
    u = irc.nickToUid(target)
    if u:
        irc.reply("Showing relay information on user \x02%s\x02:" % irc.users[u].nick, private=True)
        try:
            userpair = get_orig_user(irc, u) or (irc.name, u)
            remoteusers = relayusers[userpair].items()
        except KeyError:
            pass
        else:
            nicks = []
            if remoteusers:
                nicks.append('%s:\x02%s\x02' % (userpair[0],
                             world.networkobjects[userpair[0]].users[userpair[1]].nick))
                for r in remoteusers:
                    remotenet, remoteuser = r
                    remoteirc = world.networkobjects[remotenet]
                    nicks.append('%s:\x02%s\x02' % (remotenet, remoteirc.users[remoteuser].nick))
                irc.reply("\x02Relay nicks\x02: %s" % ', '.join(nicks), private=True)
        relaychannels = []
        for ch in irc.users[u].channels:
            relay = get_relay((irc.name, ch))
            if relay:
                relaychannels.append(''.join(relay))
        if relaychannels and (irc.isOper(source) or u == source):
            irc.reply("\x02Relay channels\x02: %s" % ' '.join(relaychannels), private=True)

@utils.add_cmd
def showchan(irc, source, args):
    """<user>

    Shows relay data about the given channel. This supplements the 'showchan' command in the 'commands' plugin, which provides more general information."""
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        return
    if channel not in irc.channels:
        return

    f = lambda s: irc.reply(s, private=True)

    c = irc.channels[channel]

    # Only show verbose info if caller is oper or is in the target channel.
    verbose = source in c.users or irc.isOper(source)
    secret = ('s', None) in c.modes
    if secret and not verbose:
        # Hide secret channels from normal users.
        return

    else:
        relayentry = get_relay((irc.name, channel))
        if relayentry:
            relays = ['\x02%s\x02' % ''.join(relayentry)]
            relays += [''.join(link) for link in db[relayentry]['links']]
            f('\x02Relayed channels:\x02 %s' % (' '.join(relays)))

@utils.add_cmd
def save(irc, source, args):
    """takes no arguments.

    Saves the relay database to disk."""
    permissions.checkPermissions(irc, source, ['relay.savedb'])
    datastore.save()
    irc.reply('Done.')

@utils.add_cmd
def claim(irc, source, args):
    """<channel> [<comma separated list of networks>]

    Sets the CLAIM for a channel to a case-sensitive list of networks. If no list of networks is
    given, this shows which networks have a claim over the channel. A single hyphen (-) can also be
    given as a list of networks to disable CLAIM from the channel entirely.

    CLAIM is a way of enforcing network ownership for channels, similar to Janus. Unless a
    channel's CLAIM list is empty, only networks on its CLAIM list (plus the creating network) are
    allowed to override kicks, mode changes, and topic changes - attempts from other networks are
    either blocked or reverted. "override" in this case refers to any KICK, MODE, or TOPIC change
    from a sender that is not halfop or above in the channel (this affects servers and services
    as well).
    """
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: channel, list of networks (optional).")
        return

    permissions.checkPermissions(irc, source, ['relay.claim'])

    # We override get_relay() here to limit the search to the current network.
    relay = (irc.name, channel)
    if relay not in db:
        irc.error('No relay %r exists on this network (this command must be run on the '
                  'network this channel was created on).' % channel)
        return
    claimed = db[relay]["claim"]
    try:
        nets = args[1].strip()
    except IndexError:  # No networks given.
        irc.reply('Channel \x02%s\x02 is claimed by: %s' %
                (channel, ', '.join(claimed) or '\x1D(none)\x1D'))
    else:
        if nets == '-' or not nets:
            claimed = set()
        else:
            claimed = set(nets.split(','))
    db[relay]["claim"] = claimed
    irc.reply('CLAIM for channel \x02%s\x02 set to: %s' %
            (channel, ', '.join(claimed) or '\x1D(none)\x1D'))
