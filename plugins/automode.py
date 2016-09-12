"""
automode.py - Provide simple channel ACL management by giving prefix modes to users matching
hostmasks or exttargets.
"""
import collections
import threading
import json

from pylinkirc import utils, conf, world
from pylinkirc.log import log
from pylinkirc.coremods import permissions

mydesc = ("The \x02Automode\x02 plugin provides simple channel ACL management by giving prefix modes "
          "to users matching hostmasks or exttargets.")

# Register ourselves as a service.
modebot = world.services.get("automode", utils.registerService("automode", desc=mydesc))
reply = modebot.reply

# Databasing variables.
dbname = utils.getDatabaseName('automode')
db = collections.defaultdict(dict)
exportdb_timer = None

save_delay = conf.conf['bot'].get('save_delay', 300)

# The default set of Automode permissions.
default_permissions = {"$ircop": ['automode.manage.relay_owned', 'automode.sync.relay_owned',
                                  'automode.list']}

def loadDB():
    """Loads the Automode database, silently creating a new one if this fails."""
    global db
    try:
        with open(dbname, "r") as f:
            db.update(json.load(f))
    except (ValueError, IOError, OSError):
        log.info("Automode: failed to load links database %s; creating a new one in "
                 "memory.", dbname)

def exportDB():
    """Exports the automode database."""

    log.debug("Automode: exporting database to %s.", dbname)
    with open(dbname, 'w') as f:
        # Pretty print the JSON output for better readability.
        json.dump(db, f, indent=4)

def scheduleExport(starting=False):
    """
    Schedules exporting of the Automode database in a repeated loop.
    """
    global exportdb_timer

    if not starting:
        # Export the database, unless this is being called the first
        # thing after start (i.e. DB has just been loaded).
        exportDB()

    exportdb_timer = threading.Timer(save_delay, scheduleExport)
    exportdb_timer.name = 'Automode exportDB Loop'
    exportdb_timer.start()

def main(irc=None):
    """Main function, called during plugin loading at start."""

    # Load the automode database.
    loadDB()

    # Schedule periodic exports of the automode database.
    scheduleExport(starting=True)

    # Register our permissions.
    permissions.addDefaultPermissions(default_permissions)

    # Queue joins to all channels where Automode has entries.
    for entry in db:
        netname, channel = entry.split('#', 1)
        channel = '#' + channel
        log.debug('automode: auto-joining %s on %s', channel, netname)
        modebot.extra_channels[netname].add(channel)

        # This explicitly forces a join to connected networks (on plugin load, etc.).
        mb_uid = modebot.uids.get(netname)
        if netname in world.networkobjects and mb_uid in world.networkobjects[netname].users:
            remoteirc = world.networkobjects[netname]
            remoteirc.proto.join(mb_uid, channel)

            # Call a join hook manually so other plugins like relay can understand it.
            remoteirc.callHooks([mb_uid, 'PYLINK_AUTOMODE_JOIN', {'channel': channel, 'users': [mb_uid],
                                                                  'modes': remoteirc.channels[channel].modes,
                                                                  'parse_as': 'JOIN'}])

def die(sourceirc):
    """Saves the Automode database and quit."""
    exportDB()

    # Kill the scheduling for exports.
    global exportdb_timer
    if exportdb_timer:
        log.debug("Automode: cancelling exportDB timer thread %s due to die()", threading.get_ident())
        exportdb_timer.cancel()

    permissions.removeDefaultPermissions(default_permissions)
    utils.unregisterService('automode')

def checkAccess(irc, uid, channel, command):
    """Checks the caller's access to Automode."""
    # Automode defines the following permissions, where <command> is either "manage", "list",
    # "sync", or "clear":
    # - automode.<command> OR automode.<command>.*: ability to <command> automode on all channels.
    # - automode.<command>.relay_owned: ability to <command> automode on channels owned via Relay.
    #   If Relay isn't loaded, this permission check FAILS.
    # - automode.<command>.#channel: ability to <command> automode on the given channel.
    # - automode.savedb: ability to save the automode DB.
    log.debug('(%s) Automode: checking access for %s/%s for %s capability on %s', irc.name, uid,
              irc.getHostmask(uid), command, channel)

    baseperm = 'automode.%s' % command
    try:
        # First, check the catch all and channel permissions.
        perms = [baseperm, baseperm+'.*', '%s.%s' % (baseperm, channel)]
        return permissions.checkPermissions(irc, uid, perms)
    except utils.NotAuthorizedError:
        log.debug('(%s) Automode: falling back to automode.%s.relay_owned', irc.name, command)
        permissions.checkPermissions(irc, uid, [baseperm+'.relay_owned'], also_show=perms)

        relay = world.plugins.get('relay')
        if relay is None:
            raise utils.NotAuthorizedError("You are not authorized to use Automode when Relay is "
                                           "disabled. You are missing one of the following "
                                           "permissions: %s or %s.%s" % (baseperm, baseperm, channel))
        elif (irc.name, channel) not in relay.db:
            raise utils.NotAuthorizedError("The network you are on does not own the relay channel %s." % channel)
        return True

def match(irc, channel, uids=None):
    """
    Automode matcher engine.
    """
    dbentry = db.get(irc.name+channel)
    if dbentry is None:
        return

    modebot_uid = modebot.uids.get(irc.name)

    # Check every mask defined in the channel ACL.
    outgoing_modes = []

    # If UIDs are given, match those. Otherwise, match all users in the given channel.
    uids = uids or irc.channels[channel].users

    for mask, modes in dbentry.items():
        for uid in uids:
            if irc.matchHost(mask, uid):
                # User matched a mask. Filter the mode list given to only those that are valid
                # prefix mode characters.
                outgoing_modes += [('+'+mode, uid) for mode in modes if mode in irc.prefixmodes]
                log.debug("(%s) automode: Filtered mode list of %s to %s (protocol:%s)",
                          irc.name, modes, outgoing_modes, irc.protoname)

    # If the Automode bot is missing, send the mode through the PyLink server.
    if modebot_uid not in irc.users:
        modebot_uid = irc.sid

    log.debug("(%s) automode: sending modes from modebot_uid %s",
              irc.name, modebot_uid)

    irc.proto.mode(modebot_uid, channel, outgoing_modes)

    # Create a hook payload to support plugins like relay.
    irc.callHooks([modebot_uid, 'AUTOMODE_MODE',
                  {'target': channel, 'modes': outgoing_modes, 'parse_as': 'MODE'}])

def handle_join(irc, source, command, args):
    """
    Automode JOIN listener. This sets modes accordingly if the person joining matches a mask in the
    ACL.
    """
    channel = irc.toLower(args['channel'])
    match(irc, channel, args['users'])

utils.add_hook(handle_join, 'JOIN')
utils.add_hook(handle_join, 'PYLINK_RELAY_JOIN')  # Handle the relay version of join
utils.add_hook(handle_join, 'PYLINK_SERVICE_JOIN')  # And the version for service bots

def handle_services_login(irc, source, command, args):
    """
    Handles services login change, to trigger Automode matching.
    """
    for channel in irc.users[source].channels:
        # Look at all the users' channels for any possible changes.
        match(irc, channel, [source])

utils.add_hook(handle_services_login, 'CLIENT_SERVICES_LOGIN')
utils.add_hook(handle_services_login, 'PYLINK_RELAY_SERVICES_LOGIN')

def setacc(irc, source, args):
    """<channel> <mask> <mode list>

    Assigns the given prefix mode characters to the given mask for the channel given. Extended targets are supported for masks - use this to your advantage!

    Examples:
    SET #channel *!*@localhost ohv
    SET #channel $account v
    SET #channel $oper:Network?Administrator qo
    SET #staffchan $channel:#mainchan:op o
    """

    try:
        channel, mask, modes = args
    except ValueError:
        reply(irc, "Error: Invalid arguments given. Needs 3: channel, mask, mode list.")
        return
    else:
        if not utils.isChannel(channel):
            reply(irc, "Error: Invalid channel name %s." % channel)
            return

        # Store channels case insensitively
        channel = irc.toLower(channel)

    checkAccess(irc, source, channel, 'manage')

    # Database entries for any network+channel pair are automatically created using
    # defaultdict. Note: string keys are used here instead of tuples so they can be
    # exported easily as JSON.
    dbentry = db[irc.name+channel]

    # Otherwise, update the modes as is.
    dbentry[mask] = modes
    log.info('(%s) %s set modes +%s for %s on %s', irc.name, irc.getHostmask(source), modes, mask, channel)
    reply(irc, "Done. \x02%s\x02 now has modes \x02%s\x02 in \x02%s\x02." % (mask, modes, channel))

    # Join the Automode bot to the channel if not explicitly told to.
    modebot.extra_channels[irc.name].add(channel)
    mbuid = modebot.uids.get(irc.name)
    if mbuid and mbuid not in irc.channels[channel].users:
        irc.proto.join(mbuid, channel)

modebot.add_cmd(setacc, 'setaccess')
modebot.add_cmd(setacc, 'set')
modebot.add_cmd(setacc, featured=True)

def delacc(irc, source, args):
    """<channel> <mask>

    Removes the Automode entry for the given mask on the given channel, if one exists.
    """
    try:
        channel, mask = args
        channel = irc.toLower(channel)
    except ValueError:
        reply(irc, "Error: Invalid arguments given. Needs 2: channel, mask")
        return

    checkAccess(irc, source, channel, 'manage')

    dbentry = db.get(irc.name+channel)

    if dbentry is None:
        reply(irc, "Error: no Automode access entries exist for \x02%s\x02." % channel)
        return

    if mask in dbentry:
        del dbentry[mask]
        log.info('(%s) %s removed modes for %s on %s', irc.name, irc.getHostmask(source), mask, channel)
        reply(irc, "Done. Removed the Automode access entry for \x02%s\x02 in \x02%s\x02." % (mask, channel))
    else:
        reply(irc, "Error: No Automode access entry for \x02%s\x02 exists in \x02%s\x02." % (mask, channel))

    # Remove channels if no more entries are left.
    if not dbentry:
        log.debug("Automode: purging empty channel pair %s/%s", irc.name, channel)
        del db[irc.name+channel]

    return
modebot.add_cmd(delacc, 'delaccess')
modebot.add_cmd(delacc, 'del')
modebot.add_cmd(delacc, featured=True)

def listacc(irc, source, args):
    """<channel>

    Lists all Automode entries for the given channel."""
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        reply(irc, "Error: Invalid arguments given. Needs 1: channel.")
        return

    checkAccess(irc, source, channel, 'list')

    dbentry = db.get(irc.name+channel)
    if not dbentry:
        reply(irc, "Error: No Automode access entries exist for \x02%s\x02." % channel)
        return

    else:
        # Iterate over all entries and print them. Do this in private to prevent channel
        # floods.
        reply(irc, "Showing Automode entries for \x02%s\x02:" % channel, private=True)
        for entrynum, entry in enumerate(dbentry.items(), start=1):
            mask, modes = entry
            reply(irc, "[%s] \x02%s\x02 has modes +\x02%s\x02" % (entrynum, mask, modes), private=True)
        reply(irc, "End of Automode entries list.", private=True)
modebot.add_cmd(listacc, featured=True)
modebot.add_cmd(listacc, 'listaccess')

def save(irc, source, args):
    """takes no arguments.

    Saves the Automode database to disk."""
    permissions.checkPermissions(irc, source, ['automode.savedb'])
    exportDB()
    reply(irc, 'Done.')
modebot.add_cmd(save)

def syncacc(irc, source, args):
    """<channel>

    Syncs Automode access lists to the channel.
    """
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        reply(irc, "Error: Invalid arguments given. Needs 1: channel.")
        return

    checkAccess(irc, source, channel, 'sync')
    log.info('(%s) %s synced modes on %s', irc.name, irc.getHostmask(source), channel)
    match(irc, channel)

    reply(irc, 'Done.')

modebot.add_cmd(syncacc, featured=True)
modebot.add_cmd(syncacc, 'sync')
modebot.add_cmd(syncacc, 'syncaccess')

def clearacc(irc, source, args):
    """<channel>

    Removes all Automode entries for the given channel.
    """

    try:
        channel = irc.toLower(args[0])
    except IndexError:
        reply(irc, "Error: Invalid arguments given. Needs 1: channel.")
        return

    checkAccess(irc, source, channel, 'clear')

    if db.get(irc.name+channel):
        log.debug("Automode: purging channel pair %s/%s", irc.name, channel)
        del db[irc.name+channel]
        log.info('(%s) %s cleared modes on %s', irc.name, irc.getHostmask(source), channel)
        reply(irc, "Done. Removed all Automode access entries for \x02%s\x02." %  channel)
    else:
        reply(irc, "Error: No Automode access entries exist for \x02%s\x02." % channel)

modebot.add_cmd(clearacc, 'clearaccess')
modebot.add_cmd(clearacc, 'clear')
modebot.add_cmd(clearacc, featured=True)
