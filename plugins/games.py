"""
games.py: Create a bot that provides game functionality (dice, 8ball, etc).
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import json
import utils
from log import log
import world

exportdb_timer = None

dbname = utils.getDatabaseName('pylinkgames')

def main(irc=None):
    """Main function, called during plugin loading at start."""

    # Load the games database.
    loadDB()

    # Schedule periodic exports of the games database.
    scheduleExport(starting=True)

    if irc is not None:
        # irc is defined when the plugin is reloaded. Otherweise,
        # it means that we've just started the server.
        # Iterate over all known networks and initialize them.
        for ircobj in world.networkobjects.values():
            initializeAll(ircobj)

def initializeAll(irc):
    """Initializes all games stuff for the given IRC object."""

    # Wait for all IRC objects to be created first. This prevents the
    # games client from being spawned too early (before server authentication),
    # which would break connections.
    world.started.wait(2)

def handle_endburst(irc, numeric, command, args):
    if numeric == irc.uplink:
        initializeAll(irc)
utils.add_hook(handle_endburst, "ENDBURST")

def scheduleExport(starting=False):
    """
    Schedules exporting of the games database in a repeated loop.
    """
    global exportdb_timer

    if not starting:
        # Export the datbase, unless this is being called the first
        # thing after start (i.e. DB has just been loaded).
        exportDB()

    # TODO: possibly make delay between exports configurable
    exportdb_timer = threading.Timer(30, scheduleExport)
    exportdb_timer.name = 'PyLink Games exportDB Loop'
    exportdb_timer.start()

## DB
def loadDB():
    """Loads the games database, creating a new one if this fails."""
    global db
    try:
        with open(dbname, "rb") as f:
            db = json.loads(str(f.read()))
    except (ValueError, IOError, FileNotFoundError):
        log.exception("Games: failed to load links database %s"
            ", creating a new one in memory...", dbname)
        db = {}

def exportDB():
    """Exports the games database."""

    log.debug("Games: exporting links database to %s", dbname)
    with open(dbname, 'wb') as f:
        f.write(json.dumps(db).encode('utf8'))

