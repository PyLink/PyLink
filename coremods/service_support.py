"""
service_support.py - Implements handlers for the PyLink ServiceBot API.
"""

from pylinkirc import utils, world, conf
from pylinkirc.log import log

def spawn_service(irc, source, command, args):
    """Handles new service bot introductions."""

    if not irc.connected.is_set():
        return

    # Service name
    name = args['name']

    if name != 'pylink' and not irc.proto.hasCap('can-spawn-clients'):
        log.debug("(%s) Not spawning service %s because the server doesn't support spawning clients",
                  irc.name, name)
        return

    # Get the ServiceBot object.
    sbot = world.services[name]

    # Look up the nick or ident in the following order:
    # 1) Network specific nick/ident settings for this service (servers::irc.name::servicename_nick)
    # 2) Global settings for this service (servicename::nick)
    # 3) The preferred nick/ident combination defined by the plugin (sbot.nick / sbot.ident)
    # 4) The literal service name.
    # settings, and then falling back to the literal service name.
    nick = irc.serverdata.get("%s_nick" % name) or conf.conf.get(name, {}).get('nick') or sbot.nick or name
    ident = irc.serverdata.get("%s_ident" % name) or conf.conf.get(name, {}).get('ident') or sbot.ident or name

    # TODO: make this configurable?
    host = irc.hostname()

    # Spawning service clients with these umodes where supported. servprotect usage is a
    # configuration option.
    preferred_modes = ['oper', 'hideoper', 'hidechans', 'invisible', 'bot']
    modes = []

    if conf.conf['bot'].get('protect_services'):
        preferred_modes.append('servprotect')

    for mode in preferred_modes:
        mode = irc.umodes.get(mode)
        if mode:
            modes.append((mode, None))

    # Track the service's UIDs on each network.
    log.debug('(%s) spawn_service: Using nick %s for service %s', irc.name, nick, name)
    u = irc.nickToUid(nick)
    if u and irc.isInternalClient(u):  # If an internal client exists, reuse it.
        log.debug('(%s) spawn_service: Using existing client %s/%s', irc.name, u, nick)
        userobj = irc.users[u]
    else:
        log.debug('(%s) spawn_service: Spawning new client %s', irc.name, nick)
        userobj = irc.proto.spawnClient(nick, ident, host, modes=modes, opertype="PyLink Service",
                                        manipulatable=sbot.manipulatable)

    # Store the service name in the IrcUser object for easier access.
    userobj.service = name

    sbot.uids[irc.name] = u = userobj.uid

    # Special case: if this is the main PyLink client being spawned,
    # assign this as irc.pseudoclient.
    if name == 'pylink':
        log.debug('(%s) spawn_service: irc.pseudoclient set to UID %s', irc.name, u)
        irc.pseudoclient = userobj

    channels = set(irc.serverdata.get(name+'_channels', [])) | set(irc.serverdata.get('channels', [])) | \
               sbot.extra_channels.get(irc.name, set())
    sbot.join(irc, channels)

utils.add_hook(spawn_service, 'PYLINK_NEW_SERVICE')

def handle_disconnect(irc, source, command, args):
    """Handles network disconnections."""
    for name, sbot in world.services.items():
        try:
            del sbot.uids[irc.name]
            log.debug("coremods.service_support: removing uids[%s] from service bot %s", irc.name, sbot.name)
        except KeyError:
            continue

utils.add_hook(handle_disconnect, 'PYLINK_DISCONNECT')

def handle_endburst(irc, source, command, args):
    """Handles network bursts."""
    if source == irc.uplink:
        log.debug('(%s): spawning service bots now.', irc.name)

        # We just connected. Burst all our registered services.
        for name, sbot in world.services.items():
            spawn_service(irc, source, command, {'name': name})

utils.add_hook(handle_endburst, 'ENDBURST')

def handle_kill(irc, source, command, args):
    """Handle KILLs to PyLink service bots, respawning them as needed."""
    target = args['target']
    userdata = args.get('userdata')
    sbot = irc.getServiceBot(target)
    servicename = None

    if userdata and hasattr(userdata, 'service'):  # Look for the target's service name attribute
        servicename = userdata.service
    elif sbot:  # Or their service bot instance
        servicename = sbot.name
    if servicename:
        log.debug('(%s) services_support: respawning service %s after KILL.', irc.name, servicename)
        spawn_service(irc, source, command, {'name': servicename})

utils.add_hook(handle_kill, 'KILL')

def handle_kick(irc, source, command, args):
    """Handle KICKs to the PyLink service bots, rejoining channels as needed."""
    kicked = args['target']
    channel = args['channel']
    sbot = irc.getServiceBot(kicked)
    if sbot:
        sbot.join(irc, channel)
utils.add_hook(handle_kick, 'KICK')

def handle_commands(irc, source, command, args):
    """Handle commands sent to the PyLink service bots (PRIVMSG)."""
    target = args['target']
    text = args['text']

    sbot = irc.getServiceBot(target)
    if sbot:
        sbot.call_cmd(irc, source, text)

utils.add_hook(handle_commands, 'PRIVMSG')

# Register the main PyLink service. All command definitions MUST go after this!
# TODO: be more specific, and possibly allow plugins to modify this to mention
# their features?
mydesc = "\x02PyLink\x02 provides extended network services for IRC."
utils.registerService('pylink', desc=mydesc, manipulatable=True)
