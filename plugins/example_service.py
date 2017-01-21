# example_service.py: An example using the PyLink services API.
import random

from pylinkirc import utils
from pylinkirc.log import log

# The first step is to register ourselves as a service. utils.registerService() passes keyword
# arguments (configuration options) to ServiceBot, which in turn supports the following:
#
# - name (required):     The name of the service.
#
# - default_help=True:   Determines whether the built-in 'help' command should be enabled for this
#                        bot.
#
# - default_list=True:   Determines whether the built-in 'list' command should be enabled for this
#                        bot.
#
# - nick=None:           The fallback nick that the service bot should use if nothing is specified
#                        in the config (i.e. both serverdata:SERVICENAME_nick and conf:SERVICE:nick
#                        are missing). If left empty, the fallback nick will just be the service
#                        name.
#
# - ident=None:          The fallback ident that the service bot should use if nothing is specified
#                        in the config (i.e. both serverdata:SERVICENAME_ident and
#                        conf:SERVICE:ident are missing). If left empty, the fallback ident will
#                        just be the service name.
#
# - manipulatable=False: Determines whether the service bot should be manipulable by things like
#                        the 'join' command in the 'bots' plugin. Depending on the nature of your
#                        plugin, it's really up to you whether you want to enable this.
#
# - desc=None:           An optional service description that's shown (if present) when the 'help'
#                        command is called without an argument.

mydesc = "Example service plugin."
# Note: the service name is case-insensitive and always lowercase.
servicebot = utils.registerService("exampleserv", manipulatable=True, desc=mydesc,
                                   nick='ExampleServ')

# These convenience assignments allow calling reply() and error() more quickly, but you can remove
# them and call the functions directly if you don't want them.
reply = servicebot.reply
error = servicebot.error

# Command functions for service bots are mostly the same as commands for the main PyLink client,
# with a couple of key differences:
def greet(irc, source, args):
    """takes no arguments.

    Greets the caller.
    """
    response = random.choice(['Hi!', 'Hello!'])
    # 1) Instead of calling irc.reply() or irc.error(), which return data through the main PyLink
    #    bot, use the reply() and error() commands in the ServiceBot instance (servicebot).
    #    These functions take the Irc object as the first argument, but otherwise use the same
    #    options as irc.reply().
    reply(irc, response)

# 2) Instead of using utils.add_cmd(function, 'name'), bind functions to your ServiceBot instance.
#    You can also use the featured=True argument to display the command's syntax directly in 'list'.
servicebot.add_cmd(greet, featured=True)
servicebot.add_cmd(greet, 'g')
