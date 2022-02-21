# relay.py: PyLink Relay plugin
import base64
import inspect
import string
import threading
import time
from collections import defaultdict

from pylinkirc import conf, structures, utils, world
from pylinkirc.coremods import permissions
from pylinkirc.log import log

CHANNEL_DELINKED_MSG = "Channel delinked."
RELAY_UNLOADED_MSG = "Relay plugin unloaded."

try:
    import cachetools
except ImportError as e:
    raise ImportError("PyLink Relay requires cachetools as of PyLink 3.0: https://pypi.org/project/cachetools/") from e

try:
    import unidecode
except ImportError:
    log.info('relay: unidecode not found; disabling unicode nicks support')
    USE_UNIDECODE = False
else:
    USE_UNIDECODE = conf.conf.get('relay', {}).get('use_unidecode', True)

### GLOBAL (statekeeping) VARIABLES
relayusers = defaultdict(dict)
relayservers = defaultdict(dict)
spawnlocks = defaultdict(threading.Lock)
spawnlocks_servers = defaultdict(threading.Lock)

# Claim bounce cache to prevent kick/mode/topic loops
__claim_bounce_timeout = conf.conf.get('relay', {}).get('claim_bounce_timeout', 5)
claim_bounce_cache = cachetools.TTLCache(float('inf'), __claim_bounce_timeout)
claim_bounce_cache_lock = threading.Lock()

dbname = conf.get_database_name('pylinkrelay')
datastore = structures.PickleDataStore('pylinkrelay', dbname)
db = datastore.store

default_permissions = {"*!*@*": ['relay.linked'],
                       "$ircop": ['relay.linkacl*']}
default_oper_permissions = {"$ircop": ['relay.create', 'relay.destroy', 'relay.link',
                                       'relay.delink', 'relay.claim', 'relay.chandesc*']}

### INTERNAL FUNCTIONS

def initialize_all(irc):
    """Initializes all relay channels for the given IRC object."""

    def _initialize_all():
        for chanpair, entrydata in db.items():
            network, channel = chanpair

            # Initialize all channels that are relevant to the called network (i.e. channels either hosted there or a relay leaf channels)
            if network == irc.name:
                initialize_channel(irc, channel)
            for link in entrydata['links']:
                network, channel = link
                if network == irc.name:
                    initialize_channel(irc, channel)

    t = threading.Thread(target=_initialize_all, daemon=True,
                         name='relay initialize_all thread from network %r' % irc.name)
    t.start()

def main(irc=None):
    """Main function, called during plugin loading at start."""
    log.debug('relay.main: loading links database')
    datastore.load()

    permissions.add_default_permissions(default_permissions)

    if 'relay' in conf.conf and conf.conf['relay'].get('allow_free_oper_links', True):
        permissions.add_default_permissions(default_oper_permissions)

    if irc is not None:
        # irc is defined when the plugin is reloaded. Otherwise, it means that we've just started the
        # server. Iterate over all connected networks and initialize their relay users.
        for netname, ircobj in world.networkobjects.items():
            if ircobj.connected.is_set():
                initialize_all(ircobj)

            if 'relay_no_ips' in ircobj.serverdata:
                log.warning('(%s) The "relay_no_ips" option is deprecated as of 2.0-beta1. Consider migrating '
                            'to "ip_share_pools", which provides more fine-grained control over which networks '
                            'see which networks\' IPs.', netname)

    if 'relay' in conf.conf and 'show_ips' in conf.conf['relay']:
        log.warning('The "relay::show_ips" option is deprecated as of 2.0-beta1. Consider migrating '
                    'to "ip_share_pools", which provides more fine-grained control over which networks '
                    'see which networks\' IPs.')

    log.debug('relay.main: finished initialization sequence')

def die(irc=None):
    """Deinitialize PyLink Relay by quitting all relay clients and saving the
    relay DB."""

    if not world.shutting_down.is_set():
        # Speed up shutdowns significantly by not manually splitting off every relay server -
        # the connection will soon be gone anyways.

        # For every connected network:
        for ircobj in world.networkobjects.values():
            # 1) SQUIT every relay subserver.
            for server, sobj in ircobj.servers.copy().items():
                if hasattr(sobj, 'remote'):
                    ircobj.squit(ircobj.sid, server, text=RELAY_UNLOADED_MSG)

    # 2) Clear our internal servers and users caches.
    relayservers.clear()
    relayusers.clear()

    # 3) Unload our permissions.
    permissions.remove_default_permissions(default_permissions)
    permissions.remove_default_permissions(default_oper_permissions)

    # 4) Save the database.
    datastore.die()

    # 5) Clear all persistent channels set up by relay.
    try:
        world.services['pylink'].clear_persistent_channels(None, 'relay',
                                                           part_reason=RELAY_UNLOADED_MSG)
    except KeyError:
        log.debug('relay.die: failed to clear persistent channels:', exc_info=True)

IRC_ASCII_ALLOWED_CHARS = string.digits + string.ascii_letters + '^|\\-_[]{}`'
FALLBACK_SEPARATOR = '|'
FALLBACK_CHARACTER = '-'

def _replace_special(text):
    """
    Replaces brackets and spaces by similar IRC-representable characters.
    """
    for pair in {('(', '['), (')', ']'), (' ', FALLBACK_CHARACTER), ('<', '['), ('>', ']')}:
        text = text.replace(pair[0], pair[1])
    return text

def _sanitize(text, extrachars=''):
    """Replaces characters not in IRC_ASCII_ALLOWED_CHARS with FALLBACK_CHARACTER."""
    whitelist = IRC_ASCII_ALLOWED_CHARS + extrachars
    for char in text:
        if char not in whitelist:
            text = text.replace(char, FALLBACK_CHARACTER)
    return text

def normalize_nick(irc, netname, nick, times_tagged=0, uid=''):
    """
    Creates a normalized nickname for the given nick suitable for introduction to a remote network
    (as a relay client).

    UID is optional for checking regular nick changes, to make sure that the sender doesn't get
    marked as nick-colliding with itself.
    """
    if irc.has_cap('freeform-nicks'):  # ☺
        return nick

    is_unicode_capable = irc.casemapping in ('utf8', 'utf-8', 'rfc7700')
    if USE_UNIDECODE and not is_unicode_capable:
        decoded_nick = unidecode.unidecode(nick).strip()
        netname = unidecode.unidecode(netname).strip()
        if decoded_nick:
            nick = decoded_nick
        else:
            # XXX: The decoded version of the nick is empty, YUCK!
            # Base64 the nick for now, since (interestingly) we don't enforce UIDs to always be
            # ASCII strings.
            nick = base64.b64encode(nick.encode(irc.encoding, 'replace'), altchars=b'[]')
            nick = nick.decode()

    # Normalize spaces to hyphens, () => []
    nick = _replace_special(nick)
    netname = _replace_special(netname)

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
            forcetag_nicks = set(conf.conf.get('relay', {}).get('forcetag_nicks', []))
            forcetag_nicks |= set(irc.serverdata.get('relay_forcetag_nicks', []))
            log.debug('(%s) relay.normalize_nick: checking if globs %s match %s.', irc.name, forcetag_nicks, nick)
            for glob in forcetag_nicks:
                if irc.match_text(glob, nick):
                    # User matched a nick to force tag nicks for. Tag them.
                    times_tagged = 1
                    break

    log.debug('(%s) relay.normalize_nick: using %r as separator.', irc.name, separator)
    orig_nick = nick
    maxnicklen = irc.maxnicklen

    # Charybdis, IRCu, etc. don't allow / in nicks, and will SQUIT with a protocol
    # violation if it sees one. Or it might just ignore the client introduction and
    # cause bad desyncs.
    protocol_allows_slashes = irc.has_cap('slash-in-nicks') or \
        irc.serverdata.get('relay_force_slashes')

    if '/' not in separator or not protocol_allows_slashes:
        separator = separator.replace('/', FALLBACK_SEPARATOR)
        nick = nick.replace('/', FALLBACK_SEPARATOR)

    # Loop over every character in the nick, making sure that it only contains valid
    # characters.
    if not is_unicode_capable:
        nick = _sanitize(nick, extrachars='/')
    else:
        # UnrealIRCd 4's forbidden nick chars, from
        # https://github.com/unrealircd/unrealircd/blob/02d69e7d8/src/modules/charsys.c#L152-L163
        for char in """!+%@&~#$:'\"?*,.""":
            nick = nick.replace(char, FALLBACK_CHARACTER)

    if nick.startswith(tuple(string.digits)):
        # On TS6 IRCds, nicks that start with 0-9 are only allowed if
        # they match the UID of the originating server. Otherwise, you'll
        # get nasty protocol violation SQUITs!
        nick = '_' + nick
    elif nick.startswith('-'):
        # Nicks starting with - are likewise not valid.
        nick = '_' + nick[1:]

    # Maximum allowed length that relay nicks may have, minus the /network tag if used.
    allowedlength = maxnicklen

    # Track how many times the given nick has been tagged. If this is 0, no tag is used.
    # If this is 1, a /network tag is added. Otherwise, keep adding one character to the
    # separator: jlu5 -> jlu5/net1 -> jlu5//net1 -> ...
    if times_tagged >= 1:
        suffix = "%s%s%s" % (separator[0]*times_tagged, separator[1:], netname)
        allowedlength -= len(suffix)

    # If a nick is too long, the real nick portion will be cut off, but the
    # /network suffix MUST remain the same.
    nick = nick[:allowedlength]
    if times_tagged >= 1:
        nick += suffix

    while irc.nick_to_uid(nick) not in (None, uid):
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
    if irc.has_cap('slash-in-hosts'):
        # UnrealIRCd and IRCd-Hybrid don't allow slashes in hostnames
        allowed_chars += '/'

    if irc.has_cap('underscore-in-hosts'):
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

    if channel in irc.channels and user in irc.channels[channel].users:
        # Iterate over the the prefix modes for relay supported by the remote IRCd.
        for pmode in irc.channels[channel].get_prefix_modes(user, prefixmodes=mlist):
            if pmode in remoteirc.cmodes:
                modes += remoteirc.cmodes[pmode]
    return modes

def spawn_relay_server(irc, remoteirc):
    """
    Spawns a relay server representing "remoteirc" on "irc".
    """
    if irc.connected.is_set():
        try:
            suffix = irc.serverdata.get('relay_server_suffix', conf.conf.get('relay', {}).get('server_suffix', 'relay'))
            # Strip any leading .'s
            suffix = suffix.lstrip('.')

            # On some IRCds (e.g. InspIRCd), we have to delay endburst to prevent triggering
            # join flood protections that are counted locally.
            needs_delayed_eob = hasattr(irc, '_endburst_delay')
            if needs_delayed_eob:
                old_eob_delay = irc._endburst_delay
                irc._endburst_delay = irc.serverdata.get('relay_endburst_delay', 10)

            sid = irc.spawn_server('%s.%s' % (remoteirc.name, suffix),
                                              desc="PyLink Relay network - %s" %
                                              (remoteirc.get_full_network_name()))

            # Set _endburst_delay back to its last value.
            if needs_delayed_eob:
                irc._endburst_delay = old_eob_delay

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
        log.debug('(%s) skipping spawn_relay_server(%s, %s); the local server (%s) is not ready yet',
                  irc.name, irc.name, remoteirc.name, irc.name)
        log.debug('(%s) spawn_relay_server: current thread is %s',
                  irc.name, threading.current_thread().name)

def get_relay_server_sid(irc, remoteirc, spawn_if_missing=True):
    """
    Fetches the relay server SID representing remoteirc on irc, spawning
    a new server if it doesn't exist and spawn_if_missing is enabled.
    """

    log.debug('(%s) Grabbing spawnlocks_servers[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    with spawnlocks_servers[irc.name]:
        try:
            sid = relayservers[irc.name][remoteirc.name]
        except KeyError:
            if not spawn_if_missing:
                log.debug('(%s) get_relay_server_sid: %s.relay doesn\'t have a known SID, ignoring.', irc.name, remoteirc.name)
                return

            log.debug('(%s) get_relay_server_sid: %s.relay doesn\'t have a known SID, spawning.', irc.name, remoteirc.name)
            sid = spawn_relay_server(irc, remoteirc)

        log.debug('(%s) get_relay_server_sid: got %s for %s.relay', irc.name, sid, remoteirc.name)
        if (sid not in irc.servers) or (sid in irc.servers and irc.servers[sid].remote != remoteirc.name):
            # SID changed in the meantime; abort.
            return

        log.debug('(%s) get_relay_server_sid: got %s for %s.relay (round 2)', irc.name, sid, remoteirc.name)
        return sid

def _has_common_pool(sourcenet, targetnet, namespace):
    """
    Returns the source network and target networks are in a pool under the given namespace
    (e.g. "ip_share_pools").
    """
    if 'relay' not in conf.conf:
        return False

    for pool in (conf.conf['relay'].get(namespace) or []):
        if sourcenet in pool and targetnet in pool:
            log.debug('relay._has_common_pool: found networks %r and %r in %s pool %r', sourcenet, targetnet,
                      namespace, pool)
            return True
    return False

def spawn_relay_user(irc, remoteirc, user, times_tagged=0, reuse_sid=None):
    """
    Spawns a relay user representing "user" from "irc" (the local network) on remoteirc (the target network).
    """
    userobj = irc.users.get(user)
    if userobj is None:
        # The query wasn't actually a valid user, or the network hasn't
        # been connected yet... Oh well!
        return

    nick = normalize_nick(remoteirc, irc.name, userobj.nick, times_tagged=times_tagged)

    # Sanitize UTF8 for networks that don't support it
    ident = _sanitize(userobj.ident, extrachars='~')

    # Truncate idents at 10 characters, because TS6 won't like them otherwise!
    ident = ident[:10]

    # HACK: hybrid will reject idents that start with a symbol
    if remoteirc.protoname == 'hybrid':
        goodchars = tuple(string.ascii_letters + string.digits + '~')
        if not ident.startswith(goodchars):
            ident = 'r' + ident

    # Normalize hostnames
    host = normalize_host(remoteirc, userobj.host)
    realname = userobj.realname
    modes = set(get_supported_umodes(irc, remoteirc, userobj.modes))
    opertype = ''

    if ('o', None) in userobj.modes:
        # Try to get the oper type, adding an "(on <networkname>)" suffix similar to what
        # Janus does.
        if hasattr(userobj, 'opertype'):
            log.debug('(%s) spawn_relay_user: setting OPERTYPE of client for %r to %s',
                      irc.name, user, userobj.opertype)
            opertype = userobj.opertype
        else:
            opertype = 'IRC Operator'

        opertype += ' (on %s)' % irc.get_full_network_name()

        # Set hideoper on remote opers, to prevent inflating
        # /lusers and various /stats
        hideoper_mode = remoteirc.umodes.get('hideoper')
        try:
            use_hideoper = conf.conf['relay']['hideoper']
        except KeyError:
            use_hideoper = True
        if hideoper_mode and use_hideoper:
            modes.add((hideoper_mode, None))

    if reuse_sid:
        rsid = reuse_sid
    else:
        rsid = get_relay_server_sid(remoteirc, irc)
        if not rsid:
            log.debug('(%s) spawn_relay_user: aborting user spawn for %s/%s @ %s (failed to retrieve a '
                      'working SID).', irc.name, user, nick, remoteirc.name)
            return

    # This is the legacy (< 2.0-beta1) control for relay IP sharing
    try:
        showRealIP = conf.conf['relay']['show_ips'] and not \
                     irc.serverdata.get('relay_no_ips') and not \
                     remoteirc.serverdata.get('relay_no_ips')

    except KeyError:
        showRealIP = False

    # New (>= 2.0-beta1) IP sharing is configured via pools of networks
    showRealIP = showRealIP or _has_common_pool(irc.name, remoteirc.name, "ip_share_pools")
    if showRealIP:
        ip = userobj.ip
        realhost = userobj.realhost
    else:
        realhost = None
        ip = '0.0.0.0'

    u = remoteirc.spawn_client(nick, ident=ident, host=host, realname=realname, modes=modes,
                               opertype=opertype, server=rsid, ip=ip, realhost=realhost).uid
    try:
        remoteirc.users[u].remote = (irc.name, user)
        remoteirc.users[u].opertype = opertype
        away = userobj.away
        if away:
            remoteirc.away(u, away)
    except KeyError:
        # User got killed somehow while we were setting options on it.
        # This is probably being done by the uplink, due to something like an
        # invalid nick, etc.
        raise

    relayusers[(irc.name, user)][remoteirc.name] = u
    return u

def get_remote_user(irc, remoteirc, user, spawn_if_missing=True, times_tagged=0, reuse_sid=None):
    """
    Fetches and returns the relay client UID representing "user" on the remote network "remoteirc",
    spawning a new user if one doesn't exist and spawn_if_missing is True.
    """

    # Wait until the network is working before trying to spawn anything.
    if irc.connected.is_set():
        # Don't spawn clones for registered service bots.
        sbot = irc.get_service_bot(user)
        if sbot:
            return sbot.uids.get(remoteirc.name)

        # Ignore invisible users - used to skip joining users who are offline or invisible on
        # external transports
        if user in irc.users:
            hide = getattr(irc.users[user], '_invisible', False)
            if hide:
                log.debug('(%s) get_remote_user: ignoring user %s since they are marked invisible', irc.name,
                          user)
                return

        log.debug('(%s) Grabbing spawnlocks[%s] from thread %r in function %r', irc.name, irc.name,
                  threading.current_thread().name, inspect.currentframe().f_code.co_name)
        with spawnlocks[irc.name]:
            # Be sort-of thread safe: lock the user spawns for the current net first.
            u = None
            try:
                # Look up the existing user, stored here as dict entries in the format:
                # {('ournet', 'UID'): {'remotenet1': 'UID1', 'remotenet2': 'UID2'}}
                u = relayusers[(irc.name, user)][remoteirc.name]
            except KeyError:
                # User doesn't exist. Spawn a new one if requested.
                if spawn_if_missing:
                    u = spawn_relay_user(irc, remoteirc, user, times_tagged=times_tagged, reuse_sid=reuse_sid)

            return u
    else:
        log.debug('(%s) skipping spawn_relay_user(%s, %s, %s, ...); the local server (%s) is not ready yet',
                  irc.name, irc.name, remoteirc.name, user, irc.name)
        log.debug('(%s) get_remote_user: current thread is %s',
                  irc.name, threading.current_thread().name)

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

def get_relay(irc, channel):
    """Finds the matching relay entry name for the given network, channel
    pair, if one exists."""

    chanpair = (irc.name, irc.to_lower(str(channel)))

    if chanpair in db:  # This chanpair is a shared channel; others link to it
        return chanpair
    # This chanpair is linked *to* a remote channel
    for name, dbentry in db.items():
        if chanpair in dbentry['links']:
            return name

def get_remote_channel(irc, remoteirc, channel):
    """Returns the linked channel name for the given channel on remoteirc,
    if one exists."""
    remotenetname = remoteirc.name
    chanpair = get_relay(irc, channel)
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
    relay = get_relay(irc, channel)

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

            # Remote net isn't ready yet, try again later.
            if not remoteirc.connected.is_set():
                continue

            # Join their (remote) users and set their modes, if applicable.
            if remotechan in remoteirc.channels:
                rc = remoteirc.channels[remotechan]
                relay_joins(remoteirc, remotechan, rc.users, rc.ts, targetirc=irc)

                # Only update the topic if it's different from what we already have,
                # and topic bursting is complete.
                if rc.topicset and rc.topic != irc.channels[channel].topic:
                    irc.topic_burst(irc.sid, channel, rc.topic)

        # Send our users and channel modes to the other nets
        if channel in irc.channels:
            c = irc._channels[channel]
            relay_joins(irc, channel, c.users, c.ts)

        if 'pylink' in world.services:
            world.services['pylink'].add_persistent_channel(irc, 'relay', channel)

def remove_channel(irc, channel):
    """Destroys a relay channel by parting all of its users."""
    if irc is None:
        return

    try:
        world.services['pylink'].remove_persistent_channel(irc, 'relay', channel, part_reason=CHANNEL_DELINKED_MSG)
    except KeyError:
        log.warning('(%s) relay: failed to remove persistent channel %r on delink', irc.name, channel, exc_info=True)

    relay = get_relay(irc, channel)
    if relay and channel in irc.channels:
        for user in irc.channels[channel].users.copy():
            # Relay a /part of all local users.
            if not irc.is_internal_client(user):
                relay_part(irc, channel, user)
            else:
                # Part and quit all relay clients.
                # Service bots are treated differently: they have plugin-defined persistent
                # channels, so we can request a part and it will apply if no other plugins
                # have the channel registered.
                sbot = irc.get_service_bot(user)
                if sbot:
                    try:
                        sbot.remove_persistent_channel(irc, 'relay', channel, part_reason=CHANNEL_DELINKED_MSG)
                    except KeyError:
                        pass
                else:
                    irc.part(user, channel, CHANNEL_DELINKED_MSG)
                    if user != irc.pseudoclient.uid and not irc.users[user].channels:
                        remoteuser = get_orig_user(irc, user)
                        del relayusers[remoteuser][irc.name]
                        irc.quit(user, 'Left all shared channels.')

def _claim_should_bounce(irc, channel):
    """
    Returns whether we should bounce the next action that fails CLAIM.
    This is used to prevent kick/mode/topic wars with services.
    """
    with claim_bounce_cache_lock:
        if irc.name not in claim_bounce_cache:  # Nothing in the cache to worry about
            return True

        limit = irc.get_service_option('relay', 'claim_bounce_limit', default=15)
        if limit < 0:  # Disabled
            return True
        elif limit < 5:  # Anything below this is just asking for desyncs...
            log.warning('(%s) relay: the minimum supported value for relay::claim_bounce_limit is 5.', irc.name)
            limit = 5

        success = claim_bounce_cache[irc.name] <= limit
        ttl = claim_bounce_cache.ttl
        if not success:
            log.warning("(%s) relay: %s received more than %s claim bounces in %s seconds - your channel may be desynced!",
                        irc.name, channel, limit, ttl)
        return success

def check_claim(irc, channel, sender, chanobj=None):
    """
    Checks whether the sender of a kick/mode/topic change passes CLAIM checks for
    a given channel. This returns True if any of the following criteria are met:

    1) No relay exists for the channel in question.
    2) The originating network is the one that created the relay.
    3) The CLAIM list for the relay in question is empty.
    4) The originating network is in the CLAIM list for the relay in question.
    5) The sender is halfop or above in the channel but NOT a U-line
       (this is because we allow u-lines to override with ops to prevent mode floods).
    6) The sender is a PyLink client/server (checks are suppressed in this case).
    """
    relay = get_relay(irc, channel)
    try:
        mlist = chanobj.prefixmodes
    except AttributeError:
        mlist = None

    sender_modes = get_prefix_modes(irc, irc, channel, sender, mlist=mlist)
    log.debug('(%s) relay.check_claim: sender modes (%s/%s) are %s (mlist=%s)', irc.name,
              sender, channel, sender_modes, mlist)
    # XXX: stop hardcoding modes to check for and support mlist in isHalfopPlus and friends
    success = (not relay) or irc.name == relay[0] or not db[relay]['claim'] or \
        irc.name in db[relay]['claim'] or \
        (any([mode in sender_modes for mode in {'y', 'q', 'a', 'o', 'h'}])
         and not irc.is_privileged_service(sender)) \
        or irc.is_internal_client(sender) or \
        irc.is_internal_server(sender)

    # Increment claim_bounce_cache, checked in _claim_should_bounce()
    if not success:
        with claim_bounce_cache_lock:
            if irc.name not in claim_bounce_cache:
                claim_bounce_cache[irc.name] = 1
            else:
                claim_bounce_cache[irc.name] += 1

    return success

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
                if name not in WHITELISTED_UMODES:
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

def is_relay_client(irc, user):
    """Returns whether the given user is a relay client."""
    return user in irc.users and hasattr(irc.users[user], 'remote')
isRelayClient = is_relay_client

def iterate_all(origirc, func, extra_args=(), kwargs=None):
    """
    Runs the given function 'func' on all connected networks. 'func' must take at least two arguments: the original network object and the remote network object.
    """
    if kwargs is None:
        kwargs = {}

    for name, remoteirc in world.networkobjects.copy().items():
        if name == origirc.name or not remoteirc.connected.is_set():
            # Don't relay things to their source network...
            continue

        func(origirc, remoteirc, *extra_args, **kwargs)

def iterate_all_present(origirc, origuser, func, extra_args=(), kwargs=None):
    """
    Runs the given function 'func' on all networks where the UID 'origuser'
    from 'origirc' has a relay client.

    'func' must take at least three arguments: the original network object,
    the remote network object, and the UID on the remote network to work on.
    """
    if kwargs is None:
        kwargs = {}

    for netname, user in relayusers[(origirc.name, origuser)].copy().items():
        remoteirc = world.networkobjects[netname]
        func(origirc, remoteirc, user, *extra_args, **kwargs)

### EVENT HANDLER INTERNALS

def relay_joins(irc, channel, users, ts, targetirc=None, **kwargs):
    """
    Relays one or more users' joins from a channel to its relay links. If targetirc is given, only burst
    to that specific network.
    """

    log.debug('(%s) relay.relay_joins: called on %r with users %r, targetirc=%s', irc.name, channel,
              users, targetirc)

    if ts < 750000:
        current_ts = int(time.time())
        log.debug('(%s) relay: resetting too low TS value of %s on %s to %s', irc.name, ts, users, current_ts)
        ts = current_ts

    claim_passed = check_claim(irc, channel, irc.uplink)

    def _relay_joins_loop(irc, remoteirc, channel, users, ts, burst=True):
        queued_users = []

        if not remoteirc.connected.is_set():
            return  # Remote network is not ready yet.

        remotechan = get_remote_channel(irc, remoteirc, channel)
        if remotechan is None:
            # If there is no link on the current network for the channel in question,
            # just skip it.
            return

        # This is a batch-like event, so try to reuse a relay server SID as much as possible.
        rsid = get_relay_server_sid(remoteirc, irc)

        for user in users.copy():
            if is_relay_client(irc, user):
                # Don't clone relay clients; that'll cause bad infinite loops.
                continue

            assert user in irc.users, "(%s) relay.relay_joins: How is this possible? %r isn't in our user database." % (irc.name, user)

            # Special case for service bots: mark the channel is persistent so that it is joined
            # when the service bot is next ready. This can be done regardless of whether the remote
            # client exists at this stage.
            sbot = irc.get_service_bot(user)
            if sbot:
                sbot.add_persistent_channel(remoteirc, 'relay', remotechan, try_join=False)

            u = get_remote_user(irc, remoteirc, user, reuse_sid=rsid)

            if not u:
                continue

            if (remotechan not in remoteirc.channels) or u not in remoteirc.channels[remotechan].users:
                # Note: only join users if they aren't already joined. This prevents op floods
                # on charybdis from repeated SJOINs sent for one user.

                # Fetch the known channel TS and all the prefix modes for each user. This ensures
                # the different sides of the relay are merged properly.
                if not irc.has_cap('has-ts'):
                    # Special hack for clientbot: just use the remote's modes so mode changes
                    # take precendence. (TS is always outside the clientbot's control)
                    if remotechan in remoteirc.channels:
                        ts = remoteirc.channels[remotechan].ts
                    else:
                        ts = int(time.time())
                else:
                    ts = irc.channels[channel].ts
                prefixes = get_prefix_modes(irc, remoteirc, channel, user)

                # sjoin() takes its users as a list of (prefix mode characters, UID) pairs.
                userpair = (prefixes, u)

                queued_users.append(userpair)

        if queued_users:
            # Look at whether we should relay this join as a regular JOIN, or a SJOIN.
            # SJOIN will be used if either the amount of users to join is > 1, or there are modes
            # to be set on the joining user.
            if burst or len(queued_users) > 1 or queued_users[0][0]:
                # Check CLAIM on the bursting network to see if they should be allowed to burst
                # modes towards other links.
                if claim_passed:
                    modes = get_supported_cmodes(irc, remoteirc, channel, irc.channels[channel].modes)

                    # Subtract any mode delta modes from this burst
                    relay = db[get_relay(irc, channel)]
                    modedelta_modes = relay.get('modedelta')
                    if modedelta_modes:
                        # Check if the target is a leaf channel: if so, add the mode delta modes to the target channel.
                        # Otherwise, subtract this set of modes, as we don't want these modes from leaves to be sent back
                        # to the original channel.
                        adding = (remoteirc.name, remotechan) in relay['links']

                        # Add this to the SJOIN mode list.
                        for mode in modedelta_modes:
                            modechar = remoteirc.cmodes.get(mode[0])

                            if modechar:
                                if modechar in remoteirc.cmodes['*A'] or modechar in remoteirc.prefixmodes:
                                    log.warning('(%s) Refusing to set modedelta mode %r on %s because it is a list or prefix mode',
                                                irc.name, modechar, channel)
                                    continue
                                elif not remoteirc.has_cap('can-spawn-clients'):
                                    log.debug('(%s) relay.handle_mode: Not enforcing modedelta modes on bot-only network %s',
                                              irc.name, remoteirc.name)
                                    continue

                                modedelta_mode = ('+%s' % modechar, mode[1])
                                if adding:
                                    log.debug('(%s) relay.relay_joins: adding %r on %s/%s (modedelta)', irc.name,
                                              str(modedelta_mode), remoteirc.name, remotechan)
                                    modes.append(modedelta_mode)
                                elif modedelta_mode in modes:
                                    log.debug('(%s) relay.relay_joins: removing %r on %s/%s (modedelta)', irc.name,
                                              str(modedelta_mode), remoteirc.name, remotechan)
                                    modes.remove(modedelta_mode)
                else:
                    modes = set()

                if rsid:
                    remoteirc.sjoin(rsid, remotechan, queued_users, ts=ts, modes=modes)
            else:
                # A regular JOIN only needs the user and the channel. TS, source SID, etc., can all be omitted.
                remoteirc.join(queued_users[0][1], remotechan)

            remoteirc.call_hooks([rsid, 'PYLINK_RELAY_JOIN', {'channel': remotechan, 'users': [u[-1] for u in queued_users]}])

    if targetirc:
        _relay_joins_loop(irc, targetirc, channel, users, ts, **kwargs)
    else:
        iterate_all(irc, _relay_joins_loop, extra_args=(channel, users, ts), kwargs=kwargs)

def relay_part(irc, *args, **kwargs):
    """
    Relays a user part from a channel to its relay links, as part of a channel delink.
    """
    def _relay_part_loop(irc, remoteirc, channel, user):
        remotechan = get_remote_channel(irc, remoteirc, channel)
        log.debug('(%s) relay.relay_part: looking for %s/%s on %s', irc.name, user, irc.name, remoteirc.name)
        log.debug('(%s) relay.relay_part: remotechan found as %s', irc.name, remotechan)

        remoteuser = get_remote_user(irc, remoteirc, user, spawn_if_missing=False)
        log.debug('(%s) relay.relay_part: remoteuser for %s/%s found as %s', irc.name, user, irc.name, remoteuser)

        if remotechan is None or remoteuser is None:
            # If there is no relay channel on the target network, or the relay
            # user doesn't exist, just do nothing.
            return

        # Remove any persistent channel entries from the remote end.
        sbot = irc.get_service_bot(user)
        if sbot:
            try:
                sbot.remove_persistent_channel(remoteirc, 'relay', remotechan, try_part=False)
            except KeyError:
                pass

        # Part the relay client with the channel delinked message.
        remoteirc.part(remoteuser, remotechan, CHANNEL_DELINKED_MSG)

        # If the relay client no longer has any channels, quit them to prevent inflating /lusers.
        if is_relay_client(remoteirc, remoteuser) and not remoteirc.users[remoteuser].channels:
            remoteirc.quit(remoteuser, 'Left all shared channels.')
            del relayusers[(irc.name, user)][remoteirc.name]

    iterate_all(irc, _relay_part_loop, extra_args=args, kwargs=kwargs)

WHITELISTED_CMODES = {
     'admin',
     'adminonly',
     'allowinvite',
     'autoop',
     'ban',
     'banexception',
     'blockcolor',
     'blockcaps',
     'blockhighlight',
     'exemptchanops',
     'filter',
     'flood',
     'flood_unreal',
     'freetarget',
     'halfop',
     'hidequits',
     'history',
     'invex',
     'inviteonly',
     'joinflood',
     'key',
     'kicknorejoin',
     'kicknorejoin_insp',
     'largebanlist',
     'limit',
     'moderated',
     'nickflood',
     'noamsg',
     'noctcp',
     'noextmsg',
     'noforwards',
     'noinvite',
     'nokick',
     'noknock',
     'nonick',
     'nonotice',
     'op',
     'operonly',
     'opmoderated',
     'owner',
     'private',
     'quiet',
     'regmoderated',
     'regonly',
     'repeat',
     'repeat_insp',
     'secret',
     'sslonly',
     'stripcolor',
     'topiclock',
     'voice'
}
WHITELISTED_UMODES = {
     'bot',
     'hidechans',
     'hideidle',
     'hideoper',
     'invisible',
     # XXX: filter-type umodes don't work consistently across IRCds
     #'noctcp',
     'oper',
     #'regdeaf',
     #'stripcolor',
     'wallops'
}
CLIENTBOT_WHITELISTED_CMODES = {'admin', 'ban', 'banexception', 'halfop', 'invex', 'op', 'owner', 'voice'}
CLIENTBOT_MODESYNC_OPTIONS = ('none', 'half', 'full')
def get_supported_cmodes(irc, remoteirc, channel, modes):
    """
    Filters a channel mode change to the modes supported by the target IRCd.
    """
    remotechan = get_remote_channel(irc, remoteirc, channel)
    if not remotechan:  # Not a relay channel
        return []

    # Handle Clientbot-specific mode whitelist settings
    whitelist = WHITELISTED_CMODES
    if remoteirc.protoname == 'clientbot' or irc.protoname == 'clientbot':
        modesync = conf.conf.get('relay', {}).get('clientbot_modesync', 'none').lower()
        if modesync not in CLIENTBOT_MODESYNC_OPTIONS:
            modesync = 'none'
            log.warning('relay: Bad clientbot_modesync option %s: valid values are %s',
                        modesync, CLIENTBOT_MODESYNC_OPTIONS)

        if modesync == 'none':
            return []  # Do nothing
        elif modesync == 'half':
            whitelist = CLIENTBOT_WHITELISTED_CMODES

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
            mode_parse_aborted = False
            if name.startswith('*'):
                # XXX: Okay, we need a better place to store modetypes.
                continue

            if modechar == m:
                if name not in whitelist:
                    log.debug("(%s) relay.get_supported_cmodes: skipping mode (%r, %r) because "
                              "it isn't a whitelisted (safe) mode for relay.",
                              irc.name, modechar, arg)
                    break

                supported_char = remoteirc.cmodes.get(name)

                # The mode we requested is an acting extban on the target network.
                # Basically there are 3 possibilities when handling these extban-like modes:
                # 1) Both target & source both use a chmode (e.g. ts6 +q). In these cases, the mode is just forwarded as-is.
                # 2) Forwarding from chmode to extban - this is the case being handled here.
                # 3) Forwarding from extban to extban (see below)
                pending_extban_prefixes = []
                if name in remoteirc.extbans_acting:
                    # We make the assumption that acting extbans can only be used with +b...
                    old_arg = arg
                    supported_char = remoteirc.cmodes['ban']
                    pending_extban_prefixes.append(name)  # Save the extban prefix for joining later
                    log.debug('(%s) relay.get_supported_cmodes: folding mode %s%s %s to %s%s %s%s for %s',
                              irc.name, prefix, modechar, old_arg, prefix, supported_char,
                              remoteirc.extbans_acting[name], arg, remoteirc.name)
                elif supported_char is None:
                    continue

                if modechar in irc.prefixmodes:
                    # This is a prefix mode (e.g. +o). We must coerse the argument
                    # so that the target exists on the remote relay network.
                    log.debug("(%s) relay.get_supported_cmodes: coersing argument of (%r, %r) "
                              "for network %r.",
                              irc.name, modechar, arg, remoteirc.name)

                    if (not irc.has_cap('can-spawn-clients')) and irc.pseudoclient and arg == irc.pseudoclient.uid:
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

                    oplist = []
                    if remotechan in remoteirc.channels:
                        oplist = remoteirc.channels[remotechan].prefixmodes[name]

                    log.debug("(%s) relay.get_supported_cmodes: list of %ss on %r is: %s",
                              irc.name, name, remotechan, oplist)

                    if prefix == '+' and arg in oplist:
                        # Don't set prefix modes that are already set.
                        log.debug("(%s) relay.get_supported_cmodes: skipping setting %s on %s/%s because it appears to be already set.",
                                  irc.name, name, arg, remoteirc.name)
                        break
                elif arg:
                    # Acting extban case 3: forwarding extban -> extban or mode
                    # First, we expand extbans from the local IRCd into a named mode and argument pair. Then, we
                    # can figure out how to relay it.
                    for extban_name, extban_prefix in irc.extbans_acting.items():
                        # Acting extbans are generally only supported with +b and +e
                        if name in {'ban', 'banexception'} and arg.startswith(extban_prefix):
                            orig_supported_char, old_arg = supported_char, arg

                            if extban_name in remoteirc.cmodes:
                                # This extban is a mode on the target network. Chop off the extban prefix and set
                                # the mode character to the target's mode for it.
                                supported_char = remoteirc.cmodes[extban_name]
                                arg = arg[len(extban_prefix):]
                                log.debug('(%s) relay.get_supported_cmodes: expanding acting extban %s%s %s to %s%s %s for %s',
                                          irc.name, prefix, orig_supported_char, old_arg, prefix,
                                          supported_char, arg, remoteirc.name)
                                # Override the mode name so that we're not overly strict about nick!user@host
                                # conformance. Note: the reverse (cmode->extban) is not done because that would
                                # also trigger the nick!user@host filter for +b.
                                name = extban_name
                            elif extban_name in remoteirc.extbans_acting:
                                # This is also an extban on the target network.
                                # Just chop off the local prefix now; we rewrite it later after processing
                                # any matching extbans.
                                pending_extban_prefixes.append(extban_name)
                                arg = arg[len(extban_prefix):]
                                log.debug('(%s) relay.get_supported_cmodes: expanding acting extban %s%s %s to %s%s %s%s for %s',
                                          irc.name, prefix, orig_supported_char, old_arg, prefix,
                                          supported_char, remoteirc.extbans_acting[extban_name], arg,
                                          remoteirc.name)
                            else:
                                # This mode/extban isn't supported, so ignore it.
                                log.debug('(%s) relay.get_supported_cmodes: blocking acting extban '
                                          '%s%s %s as target %s doesn\'t support it',
                                          irc.name, prefix, supported_char, arg, remoteirc.name)
                                mode_parse_aborted = True  # XXX: nested loops are ugly...
                            break  # Only one extban per mode pair, so break.

                    # Handle matching extbans such as Charybdis $a, UnrealIRCd ~a, InspIRCd R:, etc.
                    for extban_name, extban_prefix in irc.extbans_matching.items():
                        # For matching extbans, we check for the following:
                        # 1) arg == extban, for extbans like Charybdis $o and $a that are valid without an argument.
                        # 2) arg starting with extban, the most general case.
                        # Extbans with and without args have different mode names to prevent ambiguity and
                        # allow proper forwarding.
                        old_arg = arg
                        if arg == extban_prefix:
                            # This is a matching extban with no arg (case 1).
                            if extban_name in remoteirc.extbans_matching:
                                # Replace the ban with the remote's version entirely.
                                arg = remoteirc.extbans_matching[extban_name]
                                log.debug('(%s) relay.get_supported_cmodes: mangling static matching extban %s => %s for %s',
                                          irc.name, old_arg, arg, remoteirc.name)
                                break
                            else:
                                # Unsupported, don't forward it.
                                log.debug("(%s) relay.get_supported_cmodes: setting mode_parse_aborted as (%r, %r) "
                                          "(name=%r; extban_name=%r) doesn't match any (static) extban on %s",
                                          irc.name, supported_char, arg, name, extban_name, remoteirc.name)
                                mode_parse_aborted = True
                        elif extban_prefix.endswith(':') and arg.startswith(extban_prefix):
                            # This is a full extban with a prefix and some data. The assumption: all extbans with data
                            # have a prefix ending with : (as a delimiter)
                            if extban_name in remoteirc.extbans_matching:
                                # Chop off our prefix and apply the remote's.
                                arg = arg[len(extban_prefix):]
                                arg = remoteirc.extbans_matching[extban_name] + arg
                                log.debug('(%s) relay.get_supported_cmodes: mangling matching extban arg %s => %s for %s',
                                          irc.name, old_arg, arg, remoteirc.name)
                                break
                            else:
                                log.debug("(%s) relay.get_supported_cmodes: setting mode_parse_aborted as (%r, %r) "
                                          "(name=%r; extban_name=%r) doesn't match any (dynamic) extban on %s",
                                          irc.name, supported_char, arg, name, extban_name, remoteirc.name)
                                mode_parse_aborted = True
                    else:
                        if name in ('ban', 'banexception', 'invex', 'quiet') and not remoteirc.is_hostmask(arg):
                            # Don't add unsupported bans that don't match n!u@h syntax.
                            log.debug("(%s) relay.get_supported_cmodes: skipping unsupported extban/mode (%r, %r) "
                                      "because it doesn't match nick!user@host. (name=%r)",
                                      irc.name, supported_char, arg, name)
                            break

                    # We broke up an acting extban earlier. Now, rewrite it into a new mode by joining the prefix and data together.
                    while pending_extban_prefixes:
                        next_prefix = pending_extban_prefixes.pop()
                        log.debug("(%s) relay.get_supported_cmodes: readding extban prefix %r (%r) to (%r, %r) for %s",
                                  irc.name, next_prefix, remoteirc.extbans_acting[next_prefix],
                                  supported_char, arg, remoteirc.name)
                        arg = remoteirc.extbans_acting[next_prefix] + arg

                if mode_parse_aborted:
                    log.debug("(%s) relay.get_supported_cmodes: blocking unsupported extban/mode (%r, %r) for %s (mode_parse_aborted)",
                              irc.name, supported_char, arg, remoteirc.name)
                    break
                final_modepair = (prefix+supported_char, arg)

                # Don't set modes that are already set, to prevent floods on TS6
                # where the same mode can be set infinite times.
                if prefix == '+' and (remotechan not in remoteirc.channels or final_modepair in remoteirc.channels[remotechan].modes):
                    log.debug("(%s) relay.get_supported_cmodes: skipping setting mode (%r, %r) on %s%s because it appears to be already set.",
                              irc.name, supported_char, arg, remoteirc.name, remotechan)
                    break

                supported_modes.append(final_modepair)
                log.debug("(%s) relay.get_supported_cmodes: added modepair (%r, %r) for %s%s",
                          irc.name, supported_char, arg, remoteirc.name, remotechan)
                break

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
        irc.numeric(server, num, source, text)

    def _check_send_key(infoline):
        """
        Returns whether we should send the given info line in WHOIS. This validates the
        corresponding configuration option for being either "all" or "opers"."""
        setting = conf.conf.get('relay', {}).get(infoline, '').lower()
        if setting == 'all':
            return True
        elif setting == 'opers' and irc.is_oper(source):
            return True
        return False

    # Get the real user for the WHOIS target.
    origuser = get_orig_user(irc, target)
    if origuser:
        homenet, uid = origuser
        realirc = world.networkobjects[homenet]
        realuser = realirc.users[uid]
        netname = realirc.get_full_network_name()

        wreply(320, ":is a remote user connected via PyLink Relay. Home network: %s; "
                    "Home nick: %s" % (netname, realuser.nick))

        if _check_send_key('whois_show_accounts') and realuser.services_account:
            # Send account information if told to and the target is logged in.
            wreply(330, "%s :is logged in (on %s) as" % (realuser.services_account, netname))

        if _check_send_key('whois_show_server') and realirc.has_cap('can-track-servers'):
            wreply(320, ":is actually connected via the following server:")
            realserver = realirc.get_server(uid)
            realserver = realirc.servers[realserver]
            wreply(312, "%s :%s" % (realserver.name, realserver.desc))

utils.add_hook(handle_relay_whois, 'PYLINK_CUSTOM_WHOIS')

def handle_operup(irc, numeric, command, args):
    """
    Handles setting oper types on relay clients during oper up.
    """
    newtype = '%s (on %s)' % (args['text'], irc.get_full_network_name())

    def _handle_operup_func(irc, remoteirc, user):
        log.debug('(%s) relay.handle_opertype: setting OPERTYPE of %s/%s to %s',
                  irc.name, user, remoteirc.name, newtype)
        remoteirc.users[user].opertype = newtype

    iterate_all_present(irc, numeric, _handle_operup_func)
utils.add_hook(handle_operup, 'CLIENT_OPERED')

def handle_join(irc, numeric, command, args):
    channel = args['channel']
    if not get_relay(irc, channel):
        # No relay here, return.
        return
    ts = args['ts']
    users = set(args['users'])

    claim_passed = check_claim(irc, channel, numeric)
    current_chandata = irc.channels.get(channel)
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
            # rather not change the 'users' format of SJOIN just for this. -jlu5
            try:
                oldmodes = set(chandata.get_prefix_modes(user))
            except KeyError:
                # User was never in channel. Treat their mode list as empty.
                oldmodes = set()

            newmodes = set()
            if current_chandata is not None:
                newmodes = set(current_chandata.get_prefix_modes(user))

            modediff = newmodes - oldmodes
            log.debug('(%s) relay.handle_join: mode diff for %s on %s: %s oldmodes=%s newmodes=%s',
                      irc.name, user, channel, modediff, oldmodes, newmodes)
            for modename in modediff:
                modechar = irc.cmodes.get(modename)
                # Special case for U-lined servers: allow them to join with ops, but don't forward this mode change on.
                if modechar and not irc.is_privileged_service(numeric):
                    modes.append(('-%s' % modechar, user))

        if modes:
            if _claim_should_bounce(irc, channel):
                log.debug('(%s) relay.handle_join: reverting modes on BURST: %s', irc.name, irc.join_modes(modes))
                irc.mode(irc.sid, channel, modes)
            else:
                # HACK: pretend we managed to deop the caller, so that they can't bypass claim entirely
                log.debug('(%s) relay.handle_join: fake reverting modes on BURST: %s', irc.name, irc.join_modes(modes))
                irc.apply_modes(channel, modes)

    relay_joins(irc, channel, users, ts, burst=False)
utils.add_hook(handle_join, 'JOIN')
utils.add_hook(handle_join, 'PYLINK_SERVICE_JOIN')

def handle_quit(irc, numeric, command, args):
    # Lock the user spawning mechanism before proceeding, since we're going to be
    # deleting client from the relayusers cache.
    log.debug('(%s) Grabbing spawnlocks[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)

    with spawnlocks[irc.name]:

        def _handle_quit_func(irc, remoteirc, user):
            try:  # Try to quit the client. If this fails because they're missing, bail.
                remoteirc.quit(user, args['text'])
            except LookupError:
                pass

        iterate_all_present(irc, numeric, _handle_quit_func)
        del relayusers[(irc.name, numeric)]

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
    newnick = args['newnick']
    def _handle_nick_func(irc, remoteirc, user):
        remote_newnick = normalize_nick(remoteirc, irc.name, newnick, uid=user)
        if remoteirc.users[user].nick != remote_newnick:
            remoteirc.nick(user, remote_newnick)

    iterate_all_present(irc, numeric, _handle_nick_func)

utils.add_hook(handle_nick, 'NICK')

def handle_part(irc, numeric, command, args):
    channels = args['channels']
    text = args['text']
    # Don't allow the PyLink client PARTing to be relayed.
    if numeric == irc.pseudoclient.uid:
        # For clientbot: treat forced parts to the bot as clearchan, and attempt to rejoin only
        # if it affected a relay.
        if not irc.has_cap('can-spawn-clients'):
            for channel in [c for c in channels if get_relay(irc, c)]:
                for user in irc.channels[channel].users.copy():
                    if (not irc.is_internal_client(user)) and (not is_relay_client(irc, user)):
                        irc.call_hooks([irc.sid, 'CLIENTBOT_SERVICE_KICKED', {'channel': channel, 'target': user,
                                       'text': 'Clientbot was force parted (%s)' % text or 'None',
                                       'parse_as': 'KICK'}])
                irc.join(irc.pseudoclient.uid, channel)

            return
        return

    for channel in channels:
        def _handle_part_loop(irc, remoteirc, user):
            remotechan = get_remote_channel(irc, remoteirc, channel)
            if remotechan is None:
                return
            remoteirc.part(user, remotechan, text)

            if not remoteirc.users[user].channels:
                remoteirc.quit(user, 'Left all shared channels.')
                del relayusers[(irc.name, numeric)][remoteirc.name]
        iterate_all_present(irc, numeric, _handle_part_loop)

utils.add_hook(handle_part, 'PART')

def _get_lowest_prefix(prefixes):
    if not prefixes:
        return ''
    for prefix in 'vhoayq':
        if prefix in prefixes:
            return prefix
    else:
        log.warning('relay._get_lowest_prefix: unknown prefixes string %r', prefixes)
        return ''

def handle_messages(irc, numeric, command, args):
    command = command.upper()
    notice = 'NOTICE' in command or command.startswith('WALL')

    target = args['target']
    text = args['text']
    if irc.is_internal_client(numeric) and irc.is_internal_client(target):
        # Drop attempted PMs between internal clients (this shouldn't happen,
        # but whatever).
        return
    elif (numeric in irc.servers) and (not notice):
        log.debug('(%s) relay.handle_messages: dropping PM from server %s to %s',
                  irc.name, numeric, target)
        return
    elif not irc.has_cap('can-spawn-clients') and not world.plugins.get('relay_clientbot'):
        # For consistency, only read messages from clientbot networks if relay_clientbot is loaded
        return

    relay = get_relay(irc, target)
    remoteusers = relayusers[(irc.name, numeric)]

    avail_prefixes = {v: k for k, v in irc.prefixmodes.items()}
    prefixes = []
    # Split up @#channel prefixes and the like into their prefixes and target components
    if isinstance(target, str):
        while target and target[0] in avail_prefixes:
            prefixes.append(avail_prefixes[target[0]])
            target = target[1:]

    log.debug('(%s) relay.handle_messages: splitting target %r into prefixes=%r, target=%r',
              irc.name, args['target'], prefixes, target)

    if irc.is_channel(target):
        def _handle_messages_loop(irc, remoteirc, numeric, command, args, notice,
                                  target, text, msgprefixes):
            real_target = get_remote_channel(irc, remoteirc, target)

            # Don't relay anything back to the source net, or to disconnected networks
            # and networks without a relay for this channel.
            if (not real_target) or (not irc.connected.is_set()):
                return

            orig_msgprefixes = msgprefixes
            # Filter @#channel prefixes by what's available on the target network
            msgprefixes = list(filter(lambda p: p in remoteirc.prefixmodes, msgprefixes))
            log.debug("(%s) relay: filtering message prefixes for %s%s from %s to %s",
                      irc.name, remoteirc.name, real_target, orig_msgprefixes,
                      msgprefixes)

            # If we originally had message prefixes but ended with none,
            # assume that we don't have a place to forward the message and drop it.
            # One exception though is that %#channel implies @#channel.
            if orig_msgprefixes and not msgprefixes:
                if 'h' in orig_msgprefixes:
                    msgprefixes.append('o')
                else:
                    log.debug("(%s) relay: dropping message for %s%s, orig_prefixes=%r since "
                              "prefixes were empty after filtering.", irc.name,
                              remoteirc.name, real_target, orig_msgprefixes)
                    return

            # This bit of filtering exists because some IRCds let you do /msg ~@#channel
            # and such, despite its redundancy. (This is equivalent to @#channel AFAIK)
            lowest_msgprefix = _get_lowest_prefix(msgprefixes)
            lowest_msgprefix = remoteirc.prefixmodes.get(lowest_msgprefix, '')
            real_target = lowest_msgprefix + real_target

            user = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)

            if not user:
                if not (irc.serverdata.get('relay_weird_senders',
                        conf.conf.get('relay', {}).get('accept_weird_senders', True))):
                    log.debug("(%s) Dropping message for %s from user-less sender %s", irc.name,
                              real_target, numeric)
                    return
                # No relay clone exists for the sender; route the message through our
                # main client (or SID for notices).

                # Skip "from:" formatting for servers; it's messy with longer hostnames.
                # Also skip this formatting for servicebot relaying.
                if numeric not in irc.servers and not irc.get_service_bot(numeric):
                    displayedname = irc.get_friendly_name(numeric)
                    real_text = '<%s/%s> %s' % (displayedname, irc.name, text)
                else:
                    real_text = text

                # XXX: perhaps consider routing messages from the server where
                # possible - most IRCds except TS6 (charybdis, ratbox, hybrid)
                # allow this.
                try:
                    user = get_relay_server_sid(remoteirc, irc, spawn_if_missing=False) \
                        if notice else remoteirc.pseudoclient.uid
                    if not user:
                        return
                except AttributeError:
                    # Remote main client hasn't spawned yet. Drop the message.
                    return
                else:
                    if remoteirc.pseudoclient.uid not in remoteirc.users:
                        # Remote UID is ghosted, drop message.
                        return

            else:
                real_text = text

            log.debug('(%s) relay.handle_messages: sending message to %s from %s on behalf of %s',
                      irc.name, real_target, user, numeric)

            if real_target.startswith(tuple(irc.prefixmodes.values())) and not \
                    remoteirc.has_cap('has-statusmsg'):
                log.debug("(%s) Not sending message destined to %s/%s because "
                          "the remote does not support STATUSMSG.", irc.name,
                          remoteirc.name, real_target)
                return
            try:
                if notice:
                    remoteirc.notice(user, real_target, real_text)
                else:
                    remoteirc.message(user, real_target, real_text)
            except LookupError:
                # Our relay clone disappeared while we were trying to send the message.
                # This is normally due to a nick conflict with the IRCd.
                log.warning("(%s) relay: Relay client %s on %s was killed while "
                            "trying to send a message through it!", irc.name,
                            remoteirc.name, user)
                return
        iterate_all(irc, _handle_messages_loop,
                    extra_args=(numeric, command, args, notice, target, text, prefixes))

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
        # Note: don't spam ulined senders (e.g. services announcers) with
        # these notices.
        if homenet not in remoteusers.keys():
            if not irc.is_privileged_service(numeric):
                irc.msg(numeric, 'You must be in a common channel '
                        'with %r in order to send messages.' % \
                        irc.users[target].nick, notice=True)
            return
        remoteirc = world.networkobjects[homenet]

        if (not remoteirc.has_cap('can-spawn-clients')) and not conf.conf.get('relay', {}).get('allow_clientbot_pms'):
            if not irc.is_privileged_service(numeric):
                irc.msg(numeric, 'Private messages to users connected via Clientbot have '
                        'been administratively disabled.', notice=True)
            return

        user = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)

        try:
            if notice:
                remoteirc.notice(user, real_target, text)
            else:
                remoteirc.message(user, real_target, text)
        except LookupError:
            # Our relay clone disappeared while we were trying to send the message.
            # This is normally due to a nick conflict with the IRCd.
            log.warning("(%s) relay: Relay client %s on %s was killed while "
                        "trying to send a message through it!", irc.name,
                        remoteirc.name, user)
            return

for cmd in ('PRIVMSG', 'NOTICE', 'PYLINK_SELF_NOTICE', 'PYLINK_SELF_PRIVMSG'):
    utils.add_hook(handle_messages, cmd, priority=500)

def handle_kick(irc, source, command, args):
    channel = args['channel']
    target = args['target']
    text = args['text']
    kicker = source
    relay = get_relay(irc, channel)

    # Special case for clientbot: treat kicks to the PyLink service bot as channel clear.
    if (not irc.has_cap('can-spawn-clients')) and irc.pseudoclient and target == irc.pseudoclient.uid:
        for user in irc.channels[channel].users:
            if (not irc.is_internal_client(user)) and (not is_relay_client(irc, user)):
                reason = "Clientbot kicked by %s (%s)" % (irc.get_friendly_name(source), text)
                irc.call_hooks([irc.sid, 'CLIENTBOT_SERVICE_KICKED', {'channel': channel, 'target': user,
                               'text': reason, 'parse_as': 'KICK'}])

        return

    # Don't relay kicks to protected service bots.
    if relay is None or irc.get_service_bot(target):
        return

    origuser = get_orig_user(irc, target)

    def _handle_kick_loop(irc, remoteirc, source, command, args):
        remotechan = get_remote_channel(irc, remoteirc, channel)
        name = remoteirc.name
        log.debug('(%s) relay.handle_kick: remotechan for %s on %s is %s', irc.name, channel, name, remotechan)

        if remotechan is None:
            return

        real_kicker = get_remote_user(irc, remoteirc, kicker, spawn_if_missing=False)
        log.debug('(%s) relay.handle_kick: real kicker for %s on %s is %s', irc.name, kicker, name, real_kicker)

        if not is_relay_client(irc, target):
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

        if not real_target:
            return

        # Propogate the kick!
        if real_kicker:
            log.debug('(%s) relay.handle_kick: Kicking %s from channel %s via %s on behalf of %s/%s', irc.name, real_target, remotechan,real_kicker, kicker, irc.name)
            remoteirc.kick(real_kicker, remotechan, real_target, args['text'])
        else:
            # Kick originated from a server, or the kicker isn't in any
            # common channels with the target relay network.
            rsid = get_relay_server_sid(remoteirc, irc)
            log.debug('(%s) relay.handle_kick: Kicking %s from channel %s via %s on behalf of %s/%s', irc.name, real_target, remotechan, rsid, kicker, irc.name)

            if not irc.has_cap('can-spawn-clients'):
                # Special case for clientbot: no kick prefixes are needed.
                text = args['text']
            else:
                try:
                    if kicker in irc.servers:
                        kname = irc.servers[kicker].name
                    else:
                        kname = irc.users.get(kicker).nick
                    text = "(%s) %s" % (kname, args['text'])
                except AttributeError:
                    text = "(<unknown kicker>) %s" % args['text']

            rsid = rsid or remoteirc.sid  # Fall back to the main PyLink SID if get_relay_server_sid() fails
            remoteirc.kick(rsid, remotechan, real_target, text)

        # If the target isn't on any channels, quit them.
        if remoteirc != irc and (not remoteirc.users[real_target].channels) and not origuser:
            del relayusers[(irc.name, target)][remoteirc.name]
            remoteirc.quit(real_target, 'Left all shared channels.')

    # Kick was a relay client but sender does not pass CLAIM restrictions. Bounce a rejoin unless we've reached our limit.
    if is_relay_client(irc, target) and not check_claim(irc, channel, kicker):
        if _claim_should_bounce(irc, channel):
            homenet, real_target = get_orig_user(irc, target)
            homeirc = world.networkobjects.get(homenet)
            homenick = homeirc.users[real_target].nick if homeirc else '<ghost user>'
            homechan = get_remote_channel(irc, homeirc, channel)

            log.debug('(%s) relay.handle_kick: kicker %s is not opped... We should rejoin the target user %s', irc.name, kicker, real_target)
            # FIXME: make the check slightly more advanced: i.e. halfops can't kick ops, admins can't kick owners, etc.
            modes = get_prefix_modes(homeirc, irc, homechan, real_target)

            # Join the kicked client back with its respective modes.
            irc.sjoin(irc.sid, channel, [(modes, target)])
            if kicker in irc.users:
                log.info('(%s) relay: Blocked KICK (reason %r) from %s/%s to %s/%s on %s.',
                         irc.name, args['text'], irc.users[source].nick, irc.name,
                         homenick, homenet, channel)
                irc.msg(kicker, "This channel is claimed; your kick to "
                                "%s has been blocked because you are not "
                                "(half)opped." % channel, notice=True)
            else:
                log.info('(%s) relay: Blocked KICK (reason %r) from server %s to %s/%s on %s.',
                         irc.name, args['text'], irc.servers[source].name ,
                         homenick, homenet, channel)
        return

    iterate_all(irc, _handle_kick_loop, extra_args=(source, command, args))

    if origuser and not irc.users[target].channels:
        del relayusers[origuser][irc.name]
        irc.quit(target, 'Left all shared channels.')

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
        def _handle_chgclient_loop(irc, remoteirc, user):
            try:
                if field == 'HOST':
                    newtext = normalize_host(remoteirc, text)
                else:  # Don't overwrite the original text variable on every iteration.
                    newtext = text
                remoteirc.update_client(user, field, newtext)
            except NotImplementedError:  # IRCd doesn't support changing the field we want
                log.debug('(%s) relay.handle_chgclient: Ignoring changing field %r of %s on %s (for %s/%s);'
                          ' remote IRCd doesn\'t support it', irc.name, field,
                          user, remoteirc.name, target, irc.name)
                return
        iterate_all_present(irc, target, _handle_chgclient_loop)

for c in ('CHGHOST', 'CHGNAME', 'CHGIDENT'):
    utils.add_hook(handle_chgclient, c)

def handle_mode(irc, numeric, command, args):
    target = args['target']
    modes = args['modes']

    def _handle_mode_loop(irc, remoteirc, numeric, command, target, modes):
        if irc.is_channel(target):
            remotechan = get_remote_channel(irc, remoteirc, target)
            if not remotechan:
                return
            supported_modes = get_supported_cmodes(irc, remoteirc, target, modes)

            # Check if the sender is a user with a relay client; otherwise relay the mode
            # from the corresponding server.
            remotesender = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False) or \
                get_relay_server_sid(remoteirc, irc) or remoteirc.sid

            if not remoteirc.has_cap('can-spawn-clients'):
                if numeric in irc.servers and not irc.servers[numeric].has_eob:
                    log.debug('(%s) Not relaying modes from server %s/%s to %s as it has not finished bursting',
                              irc.name, numeric, irc.get_friendly_name(numeric), remoteirc.name)
                else:
                    friendly_modes = []
                    for modepair in modes:
                        modechar = modepair[0][-1]
                        if modechar in irc.prefixmodes:
                            orig_user = get_orig_user(irc, modepair[1])
                            if orig_user and orig_user[0] == remoteirc.name:
                                # Don't display prefix mode changes for someone on the target clientbot
                                # link; this will either be relayed via modesync or ignored.
                                continue

                            # Convert UIDs to nicks when relaying this to clientbot.
                            modepair = (modepair[0], irc.get_friendly_name(modepair[1]))
                        elif modechar in irc.cmodes['*A'] and irc.is_hostmask(modepair[1]) and \
                                conf.conf.get('relay', {}).get('clientbot_modesync', 'none').lower() != 'none':
                            # Don't show bans if the ban is a simple n!u@h and modesync is enabled
                            continue
                        friendly_modes.append(modepair)

                    if friendly_modes:
                        # Call hooks, this is used for clientbot relay.
                        remoteirc.call_hooks([remotesender, 'RELAY_RAW_MODE', {'channel': remotechan, 'modes': friendly_modes}])

            if supported_modes:
                remoteirc.mode(remotesender, remotechan, supported_modes)

        else:
            # Set hideoper on remote opers, to prevent inflating
            # /lusers and various /stats
            hideoper_mode = remoteirc.umodes.get('hideoper')
            try:
                use_hideoper = conf.conf['relay']['hideoper']
            except KeyError:
                use_hideoper = True

            # If Relay oper hiding is enabled, don't allow unsetting +H
            if use_hideoper and ('-%s' % hideoper_mode, None) in modes:
                modes.remove(('-%s' % hideoper_mode, None))

            modes = get_supported_umodes(irc, remoteirc, modes)

            if hideoper_mode:
                if ('+o', None) in modes and use_hideoper:
                    modes.append(('+%s' % hideoper_mode, None))
                elif ('-o', None) in modes:
                    modes.append(('-%s' % hideoper_mode, None))

            remoteuser = get_remote_user(irc, remoteirc, target, spawn_if_missing=False)

            if remoteuser and modes:
                remoteirc.mode(remoteuser, remoteuser, modes)

    reversed_modes = []
    if irc.is_channel(target):
        # Use the old state of the channel to check for CLAIM access.
        oldchan = args.get('channeldata')

        # Block modedelta modes from being unset by leaf networks
        relay_entry = get_relay(irc, target)
        if not relay_entry:
            modedelta_modes = []
        else:
            modedelta_modes = db[relay_entry].get('modedelta', [])
            modedelta_modes = list(filter(None, [irc.cmodes.get(named_modepair[0])
                                                 for named_modepair in modedelta_modes]))

        if not check_claim(irc, target, numeric, chanobj=oldchan):
            # Mode change blocked by CLAIM.
            reversed_modes = irc.reverse_modes(target, modes, oldobj=oldchan)

            if irc.is_privileged_service(numeric):
                # Special hack for "U-lined" servers - ignore changes to SIMPLE modes and
                # attempts to op its own clients (trying to change status for others
                # SHOULD be reverted).
                # This is for compatibility with Anope's DEFCON for the most part, as well as
                # silly people who try to register a channel multiple times via relay.
                reversed_modes = [modepair for modepair in reversed_modes if
                                  # Include prefix modes if target isn't also U-lined
                                  ((modepair[0][-1] in irc.prefixmodes and not
                                    irc.is_privileged_service(modepair[1]))
                                  # Include all list modes (bans, etc.)
                                   or modepair[0][-1] in irc.cmodes['*A'])
                                 ]
            modes.clear()  # Clear the mode list so nothing is relayed below

        for modepair in modes.copy():
            log.debug('(%s) relay.handle_mode: checking if modepair %s is in %s',
                      irc.name, str(modepair), str(modedelta_modes))
            modechar = modepair[0][-1]
            if modechar in modedelta_modes:
                if modechar in irc.cmodes['*A'] or modechar in irc.prefixmodes:
                    # Don't enforce invalid modes.
                    log.debug('(%s) relay.handle_mode: Not enforcing invalid modedelta mode %s on %s (list or prefix mode)',
                              irc.name, str(modepair), target)
                    continue
                elif not irc.has_cap('can-spawn-clients'):
                    log.debug('(%s) relay.handle_mode: Not enforcing modedelta modes on bot-only network',
                              irc.name)
                    continue

                modes.remove(modepair)

                if relay_entry[0] != irc.name:
                    # On leaf nets, enforce the modedelta.
                    reversed_modes += irc.reverse_modes(target, [modepair], oldobj=oldchan)
                    log.debug('(%s) relay.handle_mode: Reverting change of modedelta mode %s on %s',
                              irc.name, str(modepair), target)
                else:
                    # On the home net, just don't propagate the mode change.
                    log.debug('(%s) relay.handle_mode: Not propagating change of modedelta mode %s on %s',
                              irc.name, str(modepair), target)

    if reversed_modes:
        if _claim_should_bounce(irc, target):
            log.debug('(%s) relay.handle_mode: Reversing mode changes %r on %s with %r.',
                      irc.name, args['modes'], target, reversed_modes)
            irc.mode(irc.sid, target, reversed_modes)
        else:
            log.debug('(%s) relay.handle_mode: Fake reversing mode changes %r on %s with %r.',
                      irc.name, args['modes'], target, reversed_modes)
            irc.apply_modes(target, reversed_modes)

    if modes:
        iterate_all(irc, _handle_mode_loop, extra_args=(numeric, command, target, modes))

utils.add_hook(handle_mode, 'MODE')

def handle_topic(irc, numeric, command, args):
    channel = args['channel']
    oldtopic = args.get('oldtopic')
    topic = args['text']

    if check_claim(irc, channel, numeric):
        def _handle_topic_loop(irc, remoteirc, numeric, command, args):
            channel = args['channel']
            oldtopic = args.get('oldtopic')
            topic = args['text']

            remotechan = get_remote_channel(irc, remoteirc, channel)

            # Don't send if the remote topic is the same as ours.
            if remotechan is None or remotechan not in remoteirc.channels or \
                    topic == remoteirc.channels[remotechan].topic:
                return

            # This might originate from a server too.
            remoteuser = get_remote_user(irc, remoteirc, numeric, spawn_if_missing=False)
            if remoteuser:
                remoteirc.topic(remoteuser, remotechan, topic)
            else:
                rsid = get_relay_server_sid(remoteirc, irc)
                remoteirc.topic_burst(rsid, remotechan, topic)
        iterate_all(irc, _handle_topic_loop, extra_args=(numeric, command, args))

    elif oldtopic and _claim_should_bounce(irc, channel):  # Topic change blocked by claim.
        irc.topic_burst(irc.sid, channel, oldtopic)

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
        del relayusers[realuser][irc.name]
        fwd_reason = 'KILL FWD from %s/%s: %s' % (irc.get_friendly_name(numeric), irc.name, args['text'])

        origirc = world.networkobjects[realuser[0]]

        # If we're allowed to forward kills, then do so.
        if _has_common_pool(irc.name, realuser[0], 'kill_share_pools') and numeric in irc.users:
            def _relay_kill_loop(irc, remoteirc):
                if remoteirc == origirc:
                    # Don't bother with get_orig_user when we relay onto the target's home net
                    rtarget = realuser[1]
                else:
                    rtarget = get_remote_user(origirc, remoteirc, realuser[1])

                if rtarget:
                    # Forward the kill from the relay server when available
                    rsender = get_relay_server_sid(remoteirc, irc, spawn_if_missing=False) or \
                              remoteirc.sid
                    remoteirc.kill(rsender, rtarget, fwd_reason)

            iterate_all(irc, _relay_kill_loop)

            del relayusers[realuser]
        else:
            # Otherwise, forward kills as kicks where applicable.
            for homechan in origirc.users[realuser[1]].channels.copy():
                localchan = get_remote_channel(origirc, irc, homechan)

                if localchan:
                    # Forward kills as kicks in all channels that the sender has CLAIM access to.
                    if check_claim(irc, localchan, numeric) and numeric in irc.users:
                        target_nick = origirc.get_friendly_name(realuser[1])

                        def _relay_kill_to_kick(origirc, remoteirc, rtarget):
                            # Forward as a kick to each present relay client
                            remotechan = get_remote_channel(origirc, remoteirc, homechan)
                            if not remotechan:
                                return
                            rsender = get_relay_server_sid(remoteirc, irc, spawn_if_missing=False) or \
                                      remoteirc.sid
                            log.debug('(%s) relay.handle_kill: forwarding kill to %s/%s@%s as '
                                      'kick to %s/%s@%s on %s', irc.name, realuser[1],
                                      target_nick, realuser[0],
                                      rtarget, remoteirc.get_friendly_name(rtarget), remoteirc.name,
                                      remotechan)
                            remoteirc.kick(rsender, remotechan, rtarget, fwd_reason)

                        iterate_all_present(origirc, realuser[1], _relay_kill_to_kick)

                        # Then, forward to the home network.
                        hsender = get_relay_server_sid(origirc, irc, spawn_if_missing=False) or \
                                  origirc.sid
                        log.debug('(%s) relay.handle_kill: forwarding kill to %s/%s@%s as '
                                  'kick on %s', irc.name, realuser[1], target_nick,
                                  realuser[0], homechan)
                        origirc.kick(hsender, homechan, realuser[1], fwd_reason)

                    # If we have no access in a channel, rejoin the target.
                    else:
                        modes = get_prefix_modes(origirc, irc, homechan, realuser[1])
                        log.debug('(%s) relay.handle_kill: rejoining target userpair: (%r, %r)', irc.name, modes, realuser)
                        # Set times_tagged=1 to forcetag the target when they return.
                        client = get_remote_user(origirc, irc, realuser[1], times_tagged=1)
                        irc.sjoin(irc.sid, localchan, [(modes, client)])

    # Target user was local.
    elif userdata:
        reason = 'Killed (%s (%s))' % (irc.get_friendly_name(numeric), args['text'])
        handle_quit(irc, target, 'KILL', {'text': reason})

utils.add_hook(handle_kill, 'KILL')

def handle_away(irc, numeric, command, args):
    iterate_all_present(irc, numeric,
                        lambda irc, remoteirc, user:
                        remoteirc.away(user, args['text']))

    # Check invisible flag, used by external transports to hide offline users
    if not irc.is_internal_client(numeric):
        invisible = args.get('now_invisible')
        log.debug('(%s) relay.handle_away: invisible flag: %s', irc.name, invisible)
        if invisible:
            # User is now invisible - quit them
            log.debug('(%s) relay.handle_away: quitting user %s due to invisible flag', irc.name, numeric)
            handle_quit(irc, numeric, 'AWAY_NOW_INVISIBLE', {'text': "User has gone offline"})
        elif invisible is False:
            # User is no longer invisible - join them to all channels
            log.debug('(%s) relay.handle_away: rejoining user %s due to invisible flag', irc.name, numeric)
            for channel in irc.users[numeric].channels:
                c = irc.channels[channel]
                relay_joins(irc, channel, [numeric], c.ts, burst=True)

utils.add_hook(handle_away, 'AWAY')

def handle_invite(irc, source, command, args):
    target = args['target']
    channel = args['channel']
    if is_relay_client(irc, target):
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
            remoteirc.invite(remotesource, remoteuser,
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
    iterate_all_present(irc, numeric,
                        lambda irc, remoteirc, user:
                            remoteirc.call_hooks([user, 'PYLINK_RELAY_SERVICES_LOGIN', args]))

utils.add_hook(handle_services_login, 'CLIENT_SERVICES_LOGIN')

def handle_disconnect(irc, numeric, command, args):
    """Handles IRC network disconnections (internal hook)."""

    # Quit all of our users' representations on other nets, and remove
    # them from our relay clients index.
    log.debug('(%s) Grabbing spawnlocks[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    with spawnlocks[irc.name]:
        for k, v in relayusers.copy().items():
            if irc.name in v:
                del relayusers[k][irc.name]
            if k[0] == irc.name:
                del relayusers[k]
    # SQUIT all relay pseudoservers spawned for us, and remove them
    # from our relay subservers index.
    log.debug('(%s) Grabbing spawnlocks_servers[%s] from thread %r in function %r', irc.name, irc.name,
              threading.current_thread().name, inspect.currentframe().f_code.co_name)
    with spawnlocks_servers[irc.name]:

        def _handle_disconnect_loop(irc, remoteirc):
            name = remoteirc.name
            if name != irc.name:
                try:
                    rsid = relayservers[name][irc.name]
                except KeyError:
                    return
                else:
                    remoteirc.squit(remoteirc.sid, rsid, text='Relay network lost connection.')

            if irc.name in relayservers[name]:
                del relayservers[name][irc.name]

        iterate_all(irc, _handle_disconnect_loop)

        try:
            del relayservers[irc.name]
        except KeyError:  # Already removed; ignore.
            pass

    # Announce the disconnects to every leaf channel where the disconnected network is the owner
    announcement = conf.conf.get('relay', {}).get('disconnect_announcement')
    log.debug('(%s) relay: last connection successful: %s', irc.name, args.get('was_successful'))
    if args.get('was_successful'):
        for chanpair, entrydata in db.items():
            if chanpair[0] == irc.name:
                for leaf in entrydata['links']:
                    remoteirc = world.networkobjects.get(leaf[0])
                    if remoteirc and remoteirc.connected.is_set():
                        if announcement:
                            log.debug('(%s) relay: Announcing disconnect to %s%s', irc.name,
                                      leaf[0], leaf[1])
                            text = string.Template(announcement).safe_substitute({
                                   'homenetwork': irc.name, 'homechannel': chanpair[1],
                                   'network': remoteirc.name, 'channel': leaf[1]})
                            remoteirc.msg(leaf[1], text, loopback=False)

                        # Also remove any services bots that joined because of relay.
                        for sname, sbot in world.services.items():
                            if sname == 'pylink':
                                # We always keep the relay service on the channel
                                # for consistency.
                                continue
                            try:
                                sbot.remove_persistent_channel(remoteirc, 'relay', leaf[1],
                                                               part_reason=CHANNEL_DELINKED_MSG)
                            except KeyError:
                                continue
                            else:
                                log.debug('(%s) Removed service %r from %s%s as the home network disconnected',
                                          irc.name, sname, leaf[0], leaf[1])

utils.add_hook(handle_disconnect, "PYLINK_DISCONNECT")

def forcetag_nick(irc, target):
    """
    Force tags the target UID's nick, if it is a relay client.

    This method is used to handle nick collisions between relay clients and outside ones.

    Returns the new nick if the operation succeeded; otherwise returns False.
    """
    remote = get_orig_user(irc, target)
    if remote is None:
        return False

    remotenet, remoteuser = remote
    try:
        remoteirc = world.networkobjects[remotenet]
        nick = remoteirc.users[remoteuser].nick
    except KeyError:
        return False

    # Force a tagged nick by setting times_tagged to 1.
    newnick = normalize_nick(irc, remotenet, nick, times_tagged=1)
    log.debug('(%s) relay.forcetag_nick: Fixing nick of relay client %r (%s) to %s',
              irc.name, target, nick, newnick)

    if nick == newnick:
        log.debug('(%s) relay.forcetag_nick: New nick %s for %r matches old nick %s',
                  irc.name, newnick, target, nick)
        return False

    irc.nick(target, newnick)
    return newnick

def handle_save(irc, numeric, command, args):
    target = args['target']

    if is_relay_client(irc, target):
        # Nick collision!
        # It's one of our relay clients; try to fix our nick to the next
        # available normalized nick.
        forcetag_nick(irc, target)
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

    if is_relay_client(irc, target):
        forcetag_nick(irc, target)

utils.add_hook(handle_svsnick, "SVSNICK")

def handle_knock(irc, source, command, args):
    def _handle_knock_loop(irc, remoteirc, source, command, args):
        channel = args['channel']
        remotechan = get_remote_channel(irc, remoteirc, channel)
        # TS6 does not use reasons with knock, so this is not always available.
        text = args['text'] or 'No reason available'

        if remotechan is None or remotechan not in remoteirc.channels:
            return

        remoteuser = get_remote_user(irc, remoteirc, source, spawn_if_missing=False)
        use_fallback = False
        if remoteuser:
            try:
                remoteirc.knock(remoteuser, remotechan, text)
            except NotImplementedError:
                use_fallback = True
        else:
            use_fallback = True

        # Fallback to a simple notice directed to ops
        if use_fallback:
            nick = irc.get_friendly_name(source)
            log.debug('(%s) relay: using fallback KNOCK routine for %s on %s/%s',
                      irc.name, nick, remoteirc.name, remotechan)
            prefix = '%' if 'h' in remoteirc.prefixmodes else '@'
            remoteirc.notice(remoteirc.pseudoclient.uid, prefix + remotechan,
                             "Knock from %s@%s (*not* invitable from this network): %s" %
                             (nick, irc.name, text))

    iterate_all(irc, _handle_knock_loop, extra_args=(source, command, args))

utils.add_hook(handle_knock, 'KNOCK')

### PUBLIC COMMANDS

def create(irc, source, args):
    """<channel>

    Opens up the given channel over PyLink Relay."""
    try:
        channel = irc.to_lower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1: channel.")
        return
    if not irc.is_channel(channel):
        irc.error('Invalid channel %r.' % channel)
        return
    if not irc.has_cap('can-host-relay'):
        irc.error('Clientbot networks cannot be used to host a relay.')
        return
    if channel not in irc.channels or source not in irc.channels[channel].users:
        irc.error('You must be in %r to complete this operation.' % channel)
        return

    permissions.check_permissions(irc, source, ['relay.create'])

    # Check to see whether the channel requested is already part of a different
    # relay.
    localentry = get_relay(irc, channel)
    if localentry:
        irc.error('Channel %r is already part of a relay.' % channel)
        return

    creator = irc.get_hostmask(source)
    # Create the relay database entry with the (network name, channel name)
    # pair - this is just a dict with various keys.
    db[(irc.name, str(channel))] = {'links': set(),
                                    'blocked_nets': set(),
                                    'creator': creator,
                                    'ts': time.time(),
                                    'use_whitelist': irc.get_service_option('relay', 'linkacl_use_whitelist', False),
                                    'allowed_nets': set(),
                                    'claim': [irc.name] if irc.get_service_option('relay', 'enable_default_claim', True)
                                             else []}
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
        channel = args[1]
        network = args[0]
    except IndexError:
        try:  # One argument was given; assume it's just the channel.
            channel = args[0]
            network = irc.name
        except IndexError:
            irc.error("Not enough arguments. Needs 1-2: channel, network (optional).")
            return

    if not irc.is_channel(channel):
        irc.error('Invalid channel %r.' % channel)
        return

    # Check for different permissions based on whether we're destroying a local channel or
    # a remote one.
    if network == irc.name:
        permissions.check_permissions(irc, source, ['relay.destroy'])
    else:
        permissions.check_permissions(irc, source, ['relay.destroy.remote'])

    # Allow deleting old channels if the local network's casemapping ever changes
    if (network, channel) in db:
        entry = (network, channel)
    else:
        entry = (network, irc.to_lower(channel))
    if entry in db:
        stop_relay(entry)
        del db[entry]

        log.info('(%s) relay: Channel %s destroyed by %s.', irc.name,
                 channel, irc.get_hostmask(source))
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
    permissions.check_permissions(irc, source, ['relay.purge'])
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
link_parser.add_argument("-f", "--force-ts", action='store_true')
def link(irc, source, args):
    """<remotenet> <channel> [<local channel>] [-f/--force-ts]

    Links the specified channel on \x02remotenet\x02 over PyLink Relay as \x02local channel\x02.
    If \x02local channel\x02 is not specified, it defaults to the same name as \x02channel\x02.

    If the --force-ts option is given, this command will bypass checks for TS and whether the target
    network is alive, and link the channel anyways. It will not bypass other link restrictions like
    those imposed by LINKACL."""

    args = link_parser.parse_args(args)

    # Normalize channel case. For the target channel it's possible for the local and remote casemappings
    # to differ - if we find the unnormalized channel name in the list, we should just use that.
    # This mainly affects channels with e.g. | in them.
    channel_orig = str(args.channel)
    channel_norm = irc.to_lower(channel_orig)

    localchan = irc.to_lower(str(args.localchannel or args.channel))
    remotenet = args.remotenet

    if not irc.is_channel(localchan):
        irc.error('Invalid channel %r.' % localchan)
        return

    if remotenet == irc.name:
        irc.error('Cannot link two channels on the same network.')
        return

    permissions.check_permissions(irc, source, ['relay.link'])

    if localchan not in irc.channels or source not in irc.channels[localchan].users:
        # Caller is not in the requested channel.
        log.debug('(%s) Source not in channel %s; protoname=%s', irc.name, localchan, irc.protoname)
        if irc.protoname == 'clientbot':
            # Special case for Clientbot: join the requested channel first, then
            # require that the caller be opped.
            if localchan not in irc.pseudoclient.channels:
                irc.join(irc.pseudoclient.uid, localchan)
                irc.reply('Joining %r now to check for op status; please run this command again after I join.' % localchan)
                return
        else:
            irc.error('You must be in %r to complete this operation.' % localchan)
            return

    elif irc.protoname == 'clientbot' and not irc.channels[localchan].is_op_plus(source):
        if irc.pseudoclient and source == irc.pseudoclient.uid:
            irc.error('Please op the bot in %r to complete this operation.' % localchan)
        else:
            irc.error('You must be opped in %r to complete this operation.' % localchan)
        return

    if remotenet not in world.networkobjects:
        irc.error('No network named %r exists.' % remotenet)
        return
    localentry = get_relay(irc, localchan)

    if localentry:
        irc.error('Channel %r is already part of a relay.' % localchan)
        return

    if (remotenet, channel_orig) in db:
        channel = channel_orig
    elif (remotenet, channel_norm) in db:
        channel = channel_norm
    else:
        irc.error('No such relay %r exists.' % args.channel)
        return
    entry = db[(remotenet, channel)]

    whitelist_mode = entry.get('use_whitelist', False)
    if ((not whitelist_mode) and irc.name in entry['blocked_nets']) or \
            (whitelist_mode and irc.name not in entry.get('allowed_nets', set())):
        irc.error('Access denied (target channel is not open to links).')
        log.warning('(%s) relay: Blocking link request %s%s -> %s%s from %s due to LINKACL (whitelist_mode=%s)',
                    irc.name, irc.name, localchan, remotenet, channel,
                    irc.get_hostmask(source), whitelist_mode)
        return
    for link in entry['links']:
        if link[0] == irc.name:
            irc.error("Remote channel '%s%s' is already linked here "
                      "as %r." % (remotenet, args.channel, link[1]))
            return

    if args.force_ts:
        permissions.check_permissions(irc, source, ['relay.link.force_ts', 'relay.link.force'])
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
        if channel not in world.networkobjects[remotenet].channels:
            irc.error("Unknown target channel %r." % channel)
            return

        their_ts = world.networkobjects[remotenet].channels[channel].ts
        if (our_ts < their_ts) and irc.has_cap('has-ts'):
            log.debug('(%s) relay: Blocking link request %s%s -> %s%s due to bad TS (%s < %s)', irc.name,
                      irc.name, localchan, remotenet, channel, our_ts, their_ts)
            irc.error("The channel creation date (TS) on %s (%s) is lower than the target "
                      "channel's (%s); refusing to link. You should clear the local channel %s first "
                      "before linking, or use a different local channel (you may be able to "
                      "override this with the --force option)." % (localchan, our_ts, their_ts, localchan))
            return

    entry['links'].add((irc.name, localchan))
    log.info('(%s) relay: Channel %s linked to %s%s by %s.', irc.name,
             localchan, remotenet, args.channel, irc.get_hostmask(source))
    initialize_channel(irc, localchan)
    irc.reply('Done.')
link = utils.add_cmd(link, featured=True)

def delink(irc, source, args):
    """<local channel> [<network>]

    Delinks the given channel from PyLink Relay. \x02network\x02 must and can only be specified if you are on the host network for the channel given, and allows you to pick which network to delink.
    To remove a relay channel entirely, use the 'destroy' command instead."""
    try:
        channel = irc.to_lower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: channel, remote netname (optional).")
        return
    try:
        remotenet = args[1]
    except IndexError:
        remotenet = None

    permissions.check_permissions(irc, source, ['relay.delink'])

    if not irc.is_channel(channel):
        irc.error('Invalid channel %r.' % channel)
        return
    entry = get_relay(irc, channel)
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
        elif remotenet:
            irc.error('You can only use this delink syntax from the network that owns this channel.')
            return
        else:
            remove_channel(irc, channel)
            db[entry]['links'].remove((irc.name, channel))
        irc.reply('Done.')
        log.info('(%s) relay: Channel %s delinked from %s%s by %s.', irc.name,
                 channel, entry[0], entry[1], irc.get_hostmask(source))
    else:
        irc.error('No such relay %r.' % channel)
delink = utils.add_cmd(delink, featured=True)

def linked(irc, source, args):
    """[<network>]

    Returns a list of channels shared across PyLink Relay. If \x02network\x02 is given, filters output to channels linked to the given network."""

    permissions.check_permissions(irc, source, ['relay.linked'])

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
                if irc.is_oper(source) or (localchan and source in irc.channels[localchan].users):
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

        desc = v.get('description')
        if desc:  # Show channel description, if there is one.
            irc.reply('    \x02Description:\x02 %s' % desc, private=True)

        if irc.is_oper(source):
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
    """ALLOW|DENY <channel> <remotenet> [OR] LIST <channel> [OR] WHITELIST <channel> [true/false]

    Allows managing link access control lists.

    LINKACL LIST returns a list of whitelisted / blacklisted networks for a channel.

    LINKACL ALLOW and DENY allow manipulating the blacklist or whitelist for a channel.

    LINKACL WHITELIST allows showing and setting whether the channel uses a blacklist or a whitelist for ACL management."""
    missingargs = "Not enough arguments. Needs 2-3: subcommand (ALLOW/DENY/LIST/WHITELIST), channel, remote network (for ALLOW/DENY)."

    try:
        cmd = args[0].lower()
        channel = irc.to_lower(args[1])
    except IndexError:
        irc.error(missingargs)
        return

    if not irc.is_channel(channel):
        irc.error('Invalid channel %r.' % channel)
        return

    relay = get_relay(irc, channel)
    if not relay:
        irc.error('No such relay %r exists.' % channel)
        return

    entry = db[relay]
    whitelist = entry.get('use_whitelist', False)

    if cmd == 'list':
        permissions.check_permissions(irc, source, ['relay.linkacl.view'])
        if whitelist:
            s = 'Whitelisted networks for \x02%s\x02: \x02%s\x02' % (channel, ', '.join(entry['allowed_nets']) or '(empty)')
        else:
            s = 'Blocked networks for \x02%s\x02: \x02%s\x02' % (channel, ', '.join(entry.get('blocked_nets', set())) or '(empty)')
        irc.reply(s)
        return
    elif cmd == 'whitelist':
        s = 'Whitelist mode is currently \x02%s\x02 on \x02%s\x02.' % ('enabled' if whitelist else 'disabled', channel)
        if len(args) >= 3:
            setting = args[2].lower()
            if setting in ('y', 'yes', 'true', '1', 'on'):
                entry['use_whitelist'] = True
                irc.reply('Done. Whitelist mode \x02enabled\x02 on \x02%s\x02.' % channel)
                return
            elif setting in ('n', 'np', 'false', '0', 'off'):
                entry['use_whitelist'] = False
                irc.reply('Done. Whitelist mode \x02disabled\x02 on \x02%s\x02.' % channel)
                return
            else:
                irc.reply('Unknown option %r. %s' % (setting, s))
                return
        irc.reply(s)
        return

    permissions.check_permissions(irc, source, ['relay.linkacl'])
    try:
        remotenet = args[2]
    except IndexError:
        irc.error(missingargs)
        return

    if cmd == 'deny':
        if whitelist:
            # In whitelist mode, DENY *removes* from the whitelist
            try:
                db[relay]['allowed_nets'].remove(remotenet)
            except KeyError:
                irc.error('Network \x02%s\x02 is not on the whitelist for \x02%s\x02.' % (remotenet, channel))
                return
        else:
            # In blacklist mode, DENY *adds* to the blacklist
            db[relay]['blocked_nets'].add(remotenet)
        irc.reply('Done.')

    elif cmd == 'allow':
        if whitelist:
            # In whitelist mode, ALLOW *adds* to the whitelist
            if 'allowed_nets' not in entry:  # Upgrading from < 2.0-beta1
                entry['allowed_nets'] = set()
            db[relay]['allowed_nets'].add(remotenet)
        else:
            # In blacklist mode, ALLOW *removes* from the blacklist
            try:
                db[relay]['blocked_nets'].remove(remotenet)
            except KeyError:
                irc.error('Network \x02%s\x02 is not on the blacklist for \x02%s\x02.' % (remotenet, channel))
                return
        irc.reply('Done.')
    else:
        irc.error('Unknown subcommand %r: valid ones are ALLOW, DENY, and LIST.' % cmd)

@utils.add_cmd
def save(irc, source, args):
    """takes no arguments.

    Saves the relay database to disk."""
    permissions.check_permissions(irc, source, ['relay.savedb'])
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
        channel = irc.to_lower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: channel, list of networks (optional).")
        return

    permissions.check_permissions(irc, source, ['relay.claim'])

    # We override get_relay() here to limit the search to the current network.
    relay = (irc.name, channel)
    if relay not in db:
        irc.error('No relay %r exists on this network (this command must be run on the '
                  'network the channel was created on).' % channel)
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

@utils.add_cmd
def modedelta(irc, source, args):
    """<channel> [<named modes>]

    Sets the relay mode delta for the given channel: a list of named mode pairs to apply on leaf
    channels, but not the host network.

    This may be helpful in fighting spam if leaf networks
    don't police it as well as your own (e.g. you can set +R with this).

    Mode names are defined using PyLink named modes, and not IRC mode characters: you can find a
    list of channel named modes and the characters they map to on different IRCds at:

    https://raw.githack.com/jlu5/PyLink/devel/docs/modelists/channel-modes.html

    Examples of setting modes:

        modedelta #channel regonly

        modedelta #channel regonly inviteonly

        modedelta #channel key,supersecret sslonly

        modedelta #channel -

    If no modes are given, this shows the mode delta for the channel.

    A single hyphen (-) can also be given as a list of modes to disable the mode delta
    and remove any mode deltas from relay leaves.

    Note: only simple and single-arg modes (e.g. +f, +l) are supported; list modes and
    prefix modes such as bans and op are NOT.
    """
    try:
        channel = irc.to_lower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: channel, list of modes (optional).")
        return

    permissions.check_permissions(irc, source, ['relay.modedelta'])

    # We override get_relay() here to limit the search to the current network.
    relay = (irc.name, channel)
    if relay not in db:
        irc.error('No relay %r exists on this network (this command must be run on the '
                  'network the channel was created on).' % channel)
        return

    target_modes = []
    old_modes = []
    if '-' in args[1:]:  # - given to clear the list
        try:
            # Keep track of the old modedelta modes, and unset them when applying the new ones
            old_modes = db[relay]['modedelta']
            del db[relay]['modedelta']
        except KeyError:
            irc.error('No mode delta exists for %r.' % channel)
            return
        else:
            irc.reply('Cleared the mode delta for %r.' % channel)
    else:
        modes = []
        for modepair in args[1:]:
            # Construct mode pairs given the initial query.
            m = modepair.split(',', 1)
            if len(m) == 1:
                m.append(None)

            # Sanity check: you shouldn't be allowed to lock things like op or redirects
            # because one misconfiguration can cause serious desyncs.
            if m[0] not in WHITELISTED_CMODES:
                irc.error('Setting mode %r is not supported for modedelta (case sensitive).' % m[0])
                return

            modes.append(m)

        if modes:
            old_modes = db[relay].get('modedelta', [])
            db[relay]['modedelta'] = modes
            target_modes = modes.copy()
            log.debug('channel: %s', str(channel))
            irc.reply('Set the mode delta for \x02%s\x02 to: %s' % (channel, modes))
        else: # No modes given, so show the list.
            irc.reply('Mode delta for channel \x02%s\x02 is set to: %s' %
                      (channel, db[relay].get('modedelta') or '\x1D(none)\x1D'))

    # Add to target_modes all former modedelta modes that don't have a positive equivalent
    # Note: We only check for (modechar, modedata) and not for (+modechar, modedata) here
    # internally, but the actual filtering below checks for both?
    modedelta_diff = [('-%s' % modepair[0], modepair[1]) for modepair in old_modes if
                      modepair not in target_modes]
    target_modes += modedelta_diff
    for chanpair in db[relay]['links']:
        remotenet, remotechan = chanpair
        remoteirc = world.networkobjects.get(remotenet)
        if not remoteirc:
            continue

        remote_modes = []
        # For each leaf channel, unset the old mode delta and set the new one if applicable.
        log.debug('(%s) modedelta target modes for %s/%s: %s', irc.name, remotenet, remotechan, target_modes)
        for modepair in target_modes:
            modeprefix = modepair[0][0]
            if modeprefix not in '+-':  # Assume + if no prefix was given.
                modeprefix = '+'
            modename = modepair[0].lstrip('+-')

            mchar = remoteirc.cmodes.get(modename)
            if mchar:
                if mchar in remoteirc.cmodes['*A'] or mchar in remoteirc.prefixmodes:
                    log.warning('(%s) Refusing to set modedelta mode %r on %s because it is a list or prefix mode',
                                irc.name, mchar, remotechan)
                    continue
                elif not remoteirc.has_cap('can-spawn-clients'):
                    log.debug('(%s) relay.handle_mode: Not enforcing modedelta modes on bot-only network %s',
                              irc.name, remoteirc.name)
                    continue
                remote_modes.append(('%s%s' % (modeprefix, mchar), modepair[1]))
        if remote_modes:
            log.debug('(%s) Sending modedelta modes %s to %s/%s', irc.name, remote_modes, remotenet, remotechan)
            remoteirc.mode(remoteirc.pseudoclient.uid, remotechan, remote_modes)

@utils.add_cmd
def chandesc(irc, source, args):
    """<channel> [<text> or "-"]

    Sets a description for the given relay channel, which will be shown in the LINKED command.
    If no description is given, this shows the channel's current description.

    A single hyphen (-) can also be given as the description text to clear a channel's description.
    """
    try:
        channel = irc.to_lower(args[0])
    except IndexError:
        irc.error("Not enough arguments. Needs 1-2: channel, text (optional).")
        return

    # We override get_relay() here to limit the search to the current network.
    relay = (irc.name, channel)
    if relay not in db:
        irc.error('No relay %r exists on this network (this command must be run on the '
                  'network the channel was created on).' % channel)
        return

    if len(args) >= 2:
        if args[1].strip() == '-':
            permissions.check_permissions(irc, source, ['relay.chandesc.remove'])

            db[relay]['description'] = ''
            log.info('(%s) %s cleared the description for %s', irc.name, irc.get_hostmask(source), channel)
            irc.reply('Done. Cleared the description for \x02%s\x02.' % channel)
        else:
            permissions.check_permissions(irc, source, ['relay.chandesc.set'])

            db[relay]['description'] = newdesc = ' '.join(args[1:])
            log.info('(%s) %s set the description for %s to: %s', irc.name, irc.get_hostmask(source),
                     channel, newdesc)
            irc.reply('Done. Updated the description for \x02%s\x02.' % channel)
    else:
        irc.reply('Description for \x02%s\x02: %s' % (channel, db[relay].get('description') or  '\x1D(none)\x1D'))

@utils.add_cmd
def forcetag(irc, source, args):
    """<nick>

    Attempts to forcetag the given nick, if it is a relay client.
    """
    try:
        nick = args[0]
    except IndexError:
        irc.error("Not enough arguments. Needs 1: target nick.")
        return

    permissions.check_permissions(irc, source, ['relay.forcetag'])

    uid = irc.nick_to_uid(nick) or nick
    result = forcetag_nick(irc, uid)
    if result:
        irc.reply('Done. Forcetagged %s to %s' % (nick, result))
    else:
        irc.error('User %s is already tagged or not a relay client.' % nick)
