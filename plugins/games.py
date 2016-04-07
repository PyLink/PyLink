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


# commands
class Command:
    def __init__(self, irc, name, args, sender, target):
        self.irc = irc
        self.name = name
        self.args = args
        self.sender = sender
        self.target = target


class CommandHandler:
    def __init__(self):
        self.public_command_prefix = '.'
        self.commands = {}
        self.command_help = ''

    def add_command(self, name, handler):
        self.commands[name.casefold()] = handler
        self.regenerate_help()

    def regenerate_help(self):
        log.warning('games: regenerate_help not written')

    def handle_messages(self, irc, numeric, command, args):
        notice = (command in ('NOTICE', 'PYLINK_SELF_NOTICE'))
        target = args['target']
        text = args['text']

        # check sender
        if target != irc.games_user.uid:
            # message not targeted at us
            return
        elif numeric not in irc.users:
            # sender isn't a user.
            log.debug('(%s) games.handle_messages: Unknown message sender %s.', irc.name, numeric)
            return

        # HACK: Don't break on sending to @#channel or similar.
        try:
            prefix, target = target.split('#', 1)
        except ValueError:
            prefix = ''
        else:
            target = '#' + target

        log.debug('(%s) games.handle_messages: prefix is %r, target is %r', irc.name, prefix, target)

        # check public command prefixes
        if utils.isChannel(target):
            if text.startswith(self.public_command.prefix):
                text = text[len(self.public_command.prefix) - 1:]
            else:
                # not a command for us
                return

        # handle commands
        if ' ' in text:
            command_name, command_args = text.split(' ', 1)
        else:
            command_name = text
            command_args = ''

        command_name = command_name.casefold()

        command = Command(irc, command_name, command_args, numeric, target)

        # check for matching handler and dispatch
        handler = self.commands.get(command_name)
        if handler:
            handler(self, command)

cmdhandler = CommandHandler()

def help_cmd(command_handler, command):
    "[command] -- Help for the given commands"
    print('COMMAND DETAILS:', command)

cmdhandler.add_command('help', help_cmd)

# loading
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
    # TODO(dan): name/user/hostname to be configurable, possible status channel?
    user = irc.proto.spawnClient("games", "g", irc.serverdata["hostname"])
    irc.games_user = user
    if numeric == irc.uplink:
        initializeAll(irc)
utils.add_hook(handle_endburst, "ENDBURST")

# handle_messages
for cmd in ('PRIVMSG', 'NOTICE', 'PYLINK_SELF_NOTICE', 'PYLINK_SELF_PRIVMSG'):
    utils.add_hook(cmdhandler.handle_messages, cmd)

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
            db = json.loads(f.read().decode('utf8'))
    except (ValueError, IOError, FileNotFoundError):
        log.exception("Games: failed to load links database %s"
            ", creating a new one in memory...", dbname)
        db = {
            'version': 1,
            'channels': {},
        }

def exportDB():
    """Exports the games database."""

    log.debug("Games: exporting links database to %s", dbname)
    with open(dbname, 'wb') as f:
        f.write(json.dumps(db).encode('utf8'))

