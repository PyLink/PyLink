"""
automode.py - Provide simple channel ACL management by giving prefix modes to users matching
hostmasks or exttargets.
"""
import collections
import threading
import json

from pylinkirc import utils
from pylinkirc.log import log

mydesc = ("The \x02Automode\x02 plugin provides simple channel ACL management by giving prefix modes "
          "to users matching hostmasks or exttargets.")

# Register ourselves as a service.
modebot = utils.registerService("Automode", desc=mydesc)
reply = modebot.reply

# Databasing variables.
dbname = utils.getDatabaseName('automode')
db = collections.defaultdict(dict)
exportdb_timer = None

def loadDB():
    """Loads the Automode database, silently creating a new one if this fails."""
    global db
    try:
        with open(dbname, "r") as f:
            db.update(json.load(f))
    except (ValueError, IOError, OSError):
        log.info("Automode: failed to load links database %s; using the one in"
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

    # TODO: possibly make delay between exports configurable
    exportdb_timer = threading.Timer(30, scheduleExport)
    exportdb_timer.name = 'Automode exportDB Loop'
    exportdb_timer.start()

def main(irc=None):
    """Main function, called during plugin loading at start."""

    # Load the relay links database.
    loadDB()

    # Schedule periodic exports of the automode database.
    scheduleExport(starting=True)

def die(sourceirc):
    """Saves the Automode database and quit."""
    exportDB()

    # Kill the scheduling forexports.
    global exportdb_timer
    if exportdb_timer:
        log.debug("Automode: cancelling exportDB timer thread %s due to die()", threading.get_ident())
        exportdb_timer.cancel()

def setacc(irc, source, args):
    """<channel> <mask> <mode list OR literal ->

    Assigns the given prefix mode characters to the given mask for the channel given. Extended targets are supported for masks - use this to your advantage!

    Examples:
    SET #channel *!*@localhost ohv
    SET #channel $account v
    SET #channel $oper:Network?Administrator qo
    SET #staffchan $channel:#mainchan:op o
    """
    irc.checkAuthenticated(source)
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

    # Database entries for any network+channel pair are automatically created using
    # defaultdict. Note: string keys are used here instead of tuples so they can be
    # exported easily as JSON.
    dbentry = db[irc.name+channel]

    # Otherwise, update the modes as is.
    dbentry[mask] = modes
    reply(irc, "Done. \x02%s\x02 now has modes \x02%s\x02 in \x02%s\x02." % (mask, modes, channel))

modebot.add_cmd(setacc, 'setaccess')
modebot.add_cmd(setacc, 'set')
modebot.add_cmd(setacc, featured=True)

def delacc(irc, source, args):
    """<channel> <mask>

    Removes the Automode entry for the given mask on the given channel, if one exists.
    """
    irc.checkAuthenticated(source)

    try:
        channel, mask = args
    except ValueError:
        reply(irc, "Error: Invalid arguments given. Needs 2: channel, mask")
        return

    dbentry = db.get(irc.name+channel)

    if dbentry is None:
        reply(irc, "Error: no Automode access entries exist for \x02%s\x02." % channel)
        return

    if mask in dbentry:
        del dbentry[mask]
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
    irc.checkAuthenticated(source)
    try:
        channel = irc.toLower(args[0])
    except IndexError:
        reply(irc, "Error: Invalid arguments given. Needs 1: channel.")
        return
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
    irc.checkAuthenticated(source)
    exportDB()
    reply(irc, 'Done.')
modebot.add_cmd(save)

def match(irc, channel, uid):
    """
    Automode matcher engine.
    """
    dbentry = db.get(irc.name+channel)
    if dbentry is None:
        return

    modebot_uid = modebot.uids.get(irc.name)

    # Check every mask defined in the channel ACL.
    for mask, modes in dbentry.items():
        if irc.matchHost(mask, uid):
            # User matched a mask. Filter the mode list given to only those that are valid
            # prefix mode characters.
            outgoing_modes = [('+'+mode, uid) for mode in modes if mode in irc.prefixmodes]
            log.debug("(%s) automode: Filtered mode list of %s to %s (protocol:%s)",
                      irc.name, modes, outgoing_modes, irc.protoname)

            # If the Automode bot is missing, send the mode through the PyLink server.
            if not modebot_uid:
                modebot_uid = irc.sid

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

    # Iterate over all the joining UIDs:
    for uid in args['users']:
        match(irc, channel, uid)
utils.add_hook(handle_join, 'JOIN')
utils.add_hook(handle_join, 'PYLINK_RELAY_JOIN')  # Handle the relay verison of join

def handle_services_login(irc, source, command, args):
    """
    Handles services login change, to trigger Automode matching."""
    for channel in irc.users[source].channels:
        # Look at all the users' channels for any possible changes.
        match(irc, channel, source)

utils.add_hook(handle_services_login, 'CLIENT_SERVICES_LOGIN')
