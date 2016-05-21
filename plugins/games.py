"""
games.py: Create a bot that provides game functionality (dice, 8ball, etc).
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import random

import utils
from log import log
import world

gameclient = utils.registerService("Games", manipulatable=True)
reply = gameclient.reply  # TODO find a better syntax for ServiceBot.reply()

# commands
def dice(irc, source, args):
    """<num>d<sides>

    Rolls a die with <sides> sides <num> times.
    """
    if not args:
        reply(irc, "No string given.")
        return

    try:
        # Split num and sides and convert them to int.
        num, sides = map(int, args[0].split('d', 1))
    except ValueError:
        # Invalid syntax. Show the command help.
        gameclient.help(irc, source, ['dice'])
        return

    assert 1 < sides <= 100, "Invalid side count (must be 2-100)."
    assert 1 <= num <= 100, "Cannot roll more than 100 dice at once."

    results = []
    for _ in range(num):
        results.append(random.randint(1, sides))

    # Convert results to strings, join them, format, and reply.
    s = 'You rolled %s: %s (total: %s)' % (args[0], ' '.join([str(x) for x in results]), sum(results))
    reply(irc, s)

gameclient.add_cmd(dice, 'd')
gameclient.add_cmd(dice)

eightball_responses = ["It is certain.",
             "It is decidedly so.",
             "Without a doubt.",
             "Yes, definitely.",
             "You may rely on it.",
             "As I see it, yes.",
             "Most likely.",
             "Outlook good.",
             "Yes.",
             "Signs point to yes.",
             "Reply hazy, try again.",
             "Ask again later.",
             "Better not tell you now.",
             "Cannot predict now.",
             "Concentrate and ask again.",
             "Don't count on it.",
             "My reply is no.",
             "My sources say no.",
             "Outlook not so good.",
             "Very doubtful."]
def eightball(irc, source, args):
    """[<question>]

    Asks the Magic 8-ball a question.
    """
    reply(irc, random.choice(eightball_responses))
gameclient.add_cmd(eightball)
gameclient.add_cmd(eightball, '8ball')
gameclient.add_cmd(eightball, '8b')

# loading
def main(irc=None):
    """Main function, called during plugin loading at start."""

    # seed the random
    random.seed()

def die(irc):
    utils.unregisterService('games')
