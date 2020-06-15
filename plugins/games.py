"""
games.py: Creates a bot providing a few simple games.
"""
import random

from pylinkirc import utils

mydesc = "The \x02Games\x02 plugin provides simple games for IRC."

gameclient = utils.register_service("Games", default_nick="Games", manipulatable=True, desc=mydesc)
reply = gameclient.reply  # TODO find a better syntax for ServiceBot.reply()
error = gameclient.error  # TODO find a better syntax for ServiceBot.error()
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

gameclient.add_cmd(dice, aliases=('d'), featured=True)

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
gameclient.add_cmd(eightball, featured=True, aliases=('8ball', '8b'))

def die(irc=None):
    utils.unregister_service('games')
