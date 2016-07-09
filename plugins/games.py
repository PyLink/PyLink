"""
games.py: Create a bot that provides game functionality (dice, 8ball, etc).
"""
import random
import urllib.request
import urllib.error
from xml.etree import ElementTree

from pylinkirc import utils
from pylinkirc.log import log

mydesc = "The \x02Games\x02 plugin provides simple games for IRC."

gameclient = utils.registerService("Games", manipulatable=True, desc=mydesc)
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
gameclient.add_cmd(dice, featured=True)

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
gameclient.add_cmd(eightball, featured=True)
gameclient.add_cmd(eightball, '8ball')
gameclient.add_cmd(eightball, '8b')

def fml(irc, source, args):
    """[<id>]

    Displays an entry from fmylife.com. If <id> is not given, fetch a random entry from the API."""
    try:
        query = args[0]
    except IndexError:
        # Get a random FML from the API.
        query = 'random'

    # TODO: configurable language?
    url = ('http://api.betacie.com/view/%s/nocomment'
          '?key=4be9c43fc03fe&language=en' % query)
    try:
        data = urllib.request.urlopen(url).read()
    except urllib.error as e:
        reply(irc, 'Error: %s' % e)
        return

    tree = ElementTree.fromstring(data.decode('utf-8'))
    tree = tree.find('items/item')

    try:
        category = tree.find('category').text
        text = tree.find('text').text
        fmlid = tree.attrib['id']
        url = tree.find('short_url').text
    except AttributeError as e:
        log.debug("games.FML: Error fetching FML %s from URL %s: %s",
                  query, url, e)
        reply(irc, "Error: That FML does not exist or there was an error "
                   "fetching data from the API.")
        return

    if not fmlid:
        reply(irc, "Error: That FML does not exist.")
        return

    # TODO: customizable formatting
    votes = "\x02[Agreed: %s / Deserved: %s]\x02" % \
            (tree.find('agree').text, tree.find('deserved').text)
    s = '\x02#%s [%s]\x02: %s - %s \x02<\x0311%s\x03>\x02' % \
        (fmlid, category, text, votes, url)
    reply(irc, s)
gameclient.add_cmd(fml, featured=True)

def die(irc):
    utils.unregisterService('games')
