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

    # Get the ServiceBot object.
    sbot = world.services[name]

    # Look up the nick or ident in the following order:
    # 1) Network specific nick/ident settings for this service (servers::irc.name::servicename_nick)
    # 2) Global settings for this service (servicename::nick)
    # 3) The preferred nick/ident combination defined by the plugin (sbot.nick / sbot.ident)
    # 4) The literal service name.
    # settings, and then falling back to the literal service name.
    nick = irc.serverdata.get("%s_nick" % name) or irc.conf.get(name, {}).get('nick') or sbot.nick or name
    ident = irc.serverdata.get("%s_ident" % name) or irc.conf.get(name, {}).get('ident') or sbot.ident or name

    # TODO: make this configurable?
    host = irc.serverdata["hostname"]

    # Prefer spawning service clients with umode +io, plus hideoper and
    # hidechans if supported.
    modes = []
    for mode in ('oper', 'hideoper', 'hidechans', 'invisible', 'bot'):
        mode = irc.umodes.get(mode)
        if mode:
            modes.append((mode, None))

    # Track the service's UIDs on each network.
    userobj = irc.proto.spawnClient(nick, ident, host, modes=modes, opertype="PyLink Service",
                                    manipulatable=sbot.manipulatable)

    sbot.uids[irc.name] = u = userobj.uid

    # Special case: if this is the main PyLink client being spawned,
    # assign this as irc.pseudoclient.
    if name == 'pylink':
        irc.pseudoclient = userobj

    # TODO: channels should be tracked in a central database, not hardcoded
    # in conf.
    channels = set(irc.serverdata.get('channels', [])) | sbot.extra_channels

    for chan in channels:
        irc.proto.join(u, chan)

utils.add_hook(spawn_service, 'PYLINK_NEW_SERVICE')

def handle_disconnect(irc, source, command, args):
    """Handles network disconnections."""
    for name, sbot in world.services.items():
        try:
            del sbot.uids[irc.name]
            log.debug("coreplugin: removing uids[%s] from service bot %s", irc.name, sbot.name)
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
    sbot = irc.isServiceBot(target)
    if sbot:
        spawn_service(irc, source, command, {'name': sbot.name})
        return
utils.add_hook(handle_kill, 'KILL')

def handle_kick(irc, source, command, args):
    """Handle KICKs to the PyLink service bots, rejoining channels as needed."""
    kicked = args['target']
    channel = args['channel']
    if irc.isServiceBot(kicked):
        irc.proto.join(kicked, channel)
utils.add_hook(handle_kick, 'KICK')

def handle_commands(irc, source, command, args):
    """Handle commands sent to the PyLink service bots (PRIVMSG)."""
    target = args['target']
    text = args['text']

    sbot = irc.isServiceBot(target)
    if sbot:
        sbot.call_cmd(irc, source, text)

utils.add_hook(handle_commands, 'PRIVMSG')

# Register the main PyLink service. All command definitions MUST go after this!
mynick = conf.conf['bot'].get("nick", "PyLink")
myident = conf.conf['bot'].get("ident", "pylink")
utils.registerService('pylink', nick=mynick, ident=myident, manipulatable=True)
