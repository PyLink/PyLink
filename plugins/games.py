"""
games.py: Create a bot that provides game functionality (dice, 8ball, etc).
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import threading
import json
import utils
from log import log
import world

exportdb_timer = None

dbname = utils.getDatabaseName('pylinkgames')


# commands
class Command:
    def __init__(self, name, args, sender, sender_nick, target, from_to):
        self.name = name
        self.args = args
        self.sender = sender
        self.sender_nick = sender_nick
        self.target = target
        # from_to represents the channel if sent to a channel, and the sender
        # if sent to the user directly. stops commands from having to worry
        # about and handle sender vs target themselves for responses that can
        # be public, but can also be sent privately for privmsgs
        self.from_to = from_to


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
        from_to = numeric
        if utils.isChannel(target):
            from_to = target
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

        command = Command(command_name, command_args, numeric, irc.users[numeric].nick, target, from_to)

        # check for matching handler and dispatch
        handler = self.commands.get(command_name)
        if handler:
            handler(self, irc, command)

cmdhandler = CommandHandler()


# commands
def help_cmd(command_handler, irc, command):
    "[command] -- Help for the given commands"
    print('COMMAND DETAILS:', command)
    # TODO(dan): Write help handler
    irc.proto.notice(irc.games_user.uid, command.sender, '== Help ==')

cmdhandler.add_command('help', help_cmd)


def dice_cmd(command_handler, irc, command):
    "<dice string> -- Roll the dice!"
    try:
        iline = command.args

        if iline == '':
            raise Exception

        if iline[0] == '-':
            iline = '0' + iline  # fixes negatives
        oline = []
        idice = []
        odice = []
        out_dice_line = ''

        # split line into seperate parts
        for split in iline.split('+'):
            oline = oline + split.split('-')

        for line in oline:
            if('d' in line):
                if line.split('d')[0].isdigit():
                    if (len(str(line.split('d')[1])) > 6 or
                            len(str(line.split('d')[0])) > 10):
                        raise Exception
                    idice.append(line.split('d'))
                else:
                    idice.append(['1', line.split('d')[1]])
            else:
                idice.append(line.split('d'))

        # negatives
        i = 1
        for char in iline:
            if char == '+':
                i += 1
            if char == '-':
                if(len(idice[i]) == 2):
                    idice[i][1] = str(-int(idice[i][1]))
                else:
                    idice[i][0] = str(-int(idice[i][0]))
                i += 1

        # run and construct random numbers
        i = 0
        for split in idice:
            dice = []

            if(len(split) == 2):
                for i in range(int(split[0])):
                    if(int(split[1]) > 0):
                        result = random.randint(1, int(split[1]))
                        dice.append(result)
                        out_dice_line += str(result) + ', '
                    else:
                        result = random.randint(int(split[1]), -1)
                        dice.append(result)
                        out_dice_line += str(result) + ', '
                    i += 1
                    if i > 10000:
                        raise Exception
            else:
                dice += split

            odice.append(dice)

        # use calculated numbers to form result
        result = 0
        for li1 in odice:
            for li2 in li1:
                result += int(li2)

        output = command.sender_nick + ': '
        output += iline + '    =    ' + str(result)
        if len(out_dice_line.split(',')) < 13:
            output += '    =    ' + out_dice_line[:-2]

        irc.proto.message(irc.games_user.uid, command.from_to, output)

    except Exception:
        output_lines = ['DICE SYNTAX: {}d <dice>'.format(command_handler.public_command_prefix),
                        '        <dice> is a string like d12+4d8-13',
                        '        or any other permutation of rpg dice and numbers',]

        for i in range(0, len(output_lines)):
            output = output_lines[i]

            irc.proto.message(irc.games_user.uid, command.from_to, output)

cmdhandler.add_command('d', dice_cmd)
cmdhandler.add_command('dice', dice_cmd)


# loading
def main(irc=None):
    """Main function, called during plugin loading at start."""

    # seed the random
    random.seed()

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
    # TODO(dan): handle this more nicely, don't just append to games_user (esp.
    # when/as we make CommandHandler applicable to more bots)
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

