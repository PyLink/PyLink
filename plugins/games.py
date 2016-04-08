"""
games.py: Create a bot that provides game functionality (dice, 8ball, etc).
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import threading
from datetime import timedelta
import json
import utils
from log import log
import world

# database
exportdb_timer = None


class DataStore:
    # will come into play with subclassing and db version upgrading
    initial_version = 1

    def __init__(self, name, filename, db_format='json', save_frequency={'seconds': 30}):
        self.name = name

        self._filename = os.path.abspath(os.path.expanduser(filename))
        self._tmp_filename = self._filename + '.tmp'

        log.debug('(db:{}) database path set to {}'.format(self.name, self._filename))

        self._format = db_format

        log.debug('(db:{}) format set to {}'.format(self.name, self._format))

        self._save_frequency = timedelta(**save_frequency).total_seconds()

        log.debug('(db:{}) saving every {} seconds'.format(self.name, self._save_frequency))

    def create_or_load(self):
        log.debug('(db:{}) creating/loading datastore using {}'.format(self.name, self._format))

        if self._format == 'json':
            self._store = {}
            self._store_lock = threading.Lock()

            log.debug('(db:{}) loading json data store from {}'.format(self.name, self._filename))
            try:
                self._store = json.loads(open(self._filename, 'r').read())
            except (ValueError, IOError, FileNotFoundError):
                log.exception('(db:{}) failed to load existing db, creating new one in memory'.format(self.name))
                self.put('db.version', self.initial_version)
        else:
            raise Exception('(db:{}) Data store format [{}] not recognised'.format(self.name, self._format))

    def save_callback(self, starting=False):
        """Start the DB save loop."""
        if self._format == 'json':
            # don't actually save the first time
            if not starting:
                self.save()

            # schedule
            global exportdb_timer
            exportdb_timer = threading.Timer(self._save_frequency, self.save_callback)
            exportdb_timer.name = 'PyLink {} save_callback Loop'.format(self.name)
            exportdb_timer.start()
        else:
            raise Exception('(db:{}) Data store format [{}] not recognised'.format(self.name, self._format))

    def save(self):
        log.debug('(db:{}) saving datastore'.format(self.name))
        if self._format == 'json':
            with open(self._tmp_filename, 'w') as store_file:
                store_file.write(json.dumps(self._store))
            os.rename(self._tmp_filename, self._filename)

    # single keys
    def __contains__(self, key):
        if self._format == 'json':
            return key in self._store

    def get(self, key, default=None):
        if self._format == 'json':
            return self._store.get(key, default)

    def put(self, key, value):
        if self._format == 'json':
            # make sure we can serialize the given data
            # so we don't choke later on saving the db out
            json.dumps(value)

            self._store[key] = value

            return True

    def delete(self, key):
        if self._format == 'json':
            try:
                with self._store_lock:
                    del self._store[key]
            except KeyError:
                # key is already gone, nothing to do
                ...

            return True

    # multiple keys
    def list_keys(self, prefix=None):
        """Return all key names. If prefix given, return only keys that start with it."""
        if self._format == 'json':
            keys = []

            with self._store_lock:
                for key in self._store:
                    if prefix is None or key.startswith(prefix):
                        keys.append(key)

            return keys

    def delete_keys(self, prefix):
        """Delete all keys with the given prefix."""
        if self._format == 'json':
            with self._store_lock:
                for key in tuple(self._store):
                    if key.startswith(prefix):
                        del self._store[key]


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
    def __init__(self, default_help_cmd=True, default_request_cmds=True):
        self.public_command_prefix = '.'
        self.commands = {}
        self.command_help = None

        # default commands
        if default_help_cmd:
            self.add('help', self.help_cmd)
        if default_request_cmds:
            self.add('request', self.request_cmd)
            self.add('remove', self.remove_cmd)

    def add(self, name, handler):
        self.commands[name.casefold()] = handler
        self.command_help = None

    @staticmethod
    def help_cmd(self, bot, irc, user, command):
        "[command] -- Help for the given commands"
        print('COMMAND DETAILS:', command)
        # TODO(dan): Write help handler
        irc.proto.notice(user.uid, command.sender, '== Help ==')

    @staticmethod
    def request_cmd(self, bot, irc, user, command):
        "<channel> -- Make this bot join your channel!"
        channel = command.args.split(' ', 1)[0]
        if channel is None:
            return
        # TODO: casefold this as per irc net
        channame = channel.lower()

        # make sure they're an op in there
        channel = irc.channels.get(channame)
        if channel is None or not channel.isOpPlus(command.sender):
            irc.proto.notice(user.uid, command.sender, "You are not an op in that channel")
            return

        # check if we're already joined to the channel
        joinedkey = 'channels.joined_to {} {}'.format(irc.name, channame)
        joined_to_chan = bot.db.get(joinedkey, default=False)

        if joined_to_chan:
            irc.proto.notice(user.uid, command.sender, "I'm already joined to that channel!")
            return

        # join the channel
        irc.proto.notice(user.uid, command.sender, "Joining channel ".format(channame))
        bot.db.put(joinedkey, True)
        irc.proto.join(user.uid, channame)

    @staticmethod
    def remove_cmd(self, bot, irc, user, command):
        "<channel> -- Make this bot leave your channel!"
        channel = command.args.split(' ', 1)[0]
        if channel is None:
            return
        # TODO: casefold this as per irc net
        channame = channel.lower()

        # make sure they're an op in there
        channel = irc.channels.get(channame)
        if channel is None or not channel.isOpPlus(command.sender):
            irc.proto.notice(user.uid, command.sender, "You are not an op in that channel")
            return

        # check if we're already joined to the channel
        joinedkey = 'channels.joined_to {} {}'.format(irc.name, channame)
        joined_to_chan = bot.db.get(joinedkey, default=False)

        if not joined_to_chan:
            irc.proto.notice(user.uid, command.sender, "I'm not in that channel!")
            return

        # join the channel
        irc.proto.notice(user.uid, command.sender, "Leaving channel ".format(channame))
        bot.db.delete(joinedkey)
        irc.proto.part(user.uid, channame)

    def handle_messages(self, bot, user, irc, numeric, command, args):
        notice = (command in ('NOTICE', 'PYLINK_SELF_NOTICE'))
        target = args['target']
        text = args['text']

        # check sender
        if target != user.uid:
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
            handler(self, bot, irc, user, command)


# bot clients
class BotClient:
    def __init__(self, name, cmd_handler=None, process_self_messages=False):
        self.name = name
        self.db = None

        # cmd_handler
        if cmd_handler is None:
            cmd_handler = CommandHandler()
        self.cmds = cmd_handler

        # events
        utils.add_hook(self.handle_endburst, 'ENDBURST')
        for cmd in ('PRIVMSG', 'NOTICE'):
            utils.add_hook(self.handle_messages, cmd)
        if process_self_messages:
            for cmd in ('PYLINK_SELF_NOTICE', 'PYLINK_SELF_PRIVMSG'):
                utils.add_hook(self.handle_messages, cmd)

    def handle_endburst(self, irc, numeric, command, args):
        # TODO(dan): name/user/hostname to be configurable, just passed in with __init__?
        # possible status channel?
        user = irc.proto.spawnClient(self.name, self.name, irc.serverdata["hostname"])
        irc.bot_clients[self.name] = user

        # join required channels
        for key in self.db.list_keys(prefix='channels.joined_to {}'.format(irc.name)):
            channel = key.rsplit(' ', 1)[-1]
            irc.proto.join(user.uid, channel)

    def handle_messages(self, irc, numeric, command, args):
        # make sure we're spawned
        user = irc.bot_clients.get(self.name)
        if user is None:
            return

        self.cmds.handle_messages(self, user, irc, numeric, command, args)

gameclient = BotClient('games')


# commands
def dice_cmd(command_handler, irc, user, command):
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

        irc.proto.message(user.uid, command.from_to, output)

    except Exception:
        output_lines = ['DICE SYNTAX: {}d <dice>'.format(command_handler.public_command_prefix),
                        '        <dice> is a string like d12+4d8-13',
                        '        or any other permutation of rpg dice and numbers',]

        for i in range(0, len(output_lines)):
            output = output_lines[i]

            irc.proto.message(user.uid, command.from_to, output)

gameclient.cmds.add('d', dice_cmd)
gameclient.cmds.add('dice', dice_cmd)


# loading
def main(irc=None):
    """Main function, called during plugin loading at start."""

    # seed the random
    random.seed()

    # Load the games database.
    db_filename = utils.getDatabaseName('pylinkgames')

    # TODO: make db save frequency adjustable, pass in here
    db = DataStore('games', db_filename)
    db.create_or_load()

    gameclient.db = db

    # Schedule periodic exports of the games database.
    db.save_callback(starting=True)
