# PyLink Services Bot API

Starting with PyLink 0.9.x, a services bot API was introduced to make writing custom services slightly easier. PyLink's Services API automatically connects service bots, and handles rejoin on kick/kill all by itself, meaning less code is needed per plugin to have functional service bots.

## Creating new services

Services can be created (registered) using code similar to the following in a plugin:

```python

from pylinkirc import utils, world

# Description is optional (though recommended), and usually around a sentence or two.
desc = "Optional description of servicenick, in sentence form."

# First argument is the internal service name.
# utils.registerService() returns a utils.ServiceBot instance, which can also be found
# by calling world["myservice"].
myservice = utils.registerService("myservice", desc=desc)
```

`utils.registerService()` passes its arguments directly to the `utils.ServiceBot` class constructor, which in turn supports the following options:

- **`name`** - defines the service name (mandatory)
- `default_help` - Determines whether the default HELP command should be used for the service. Defaults to True.
- `default_list` - Determines whether the default LIST command should be used for the service. Defaults to True.
- `nick`, `ident` - Sets the default nick and ident for the service bot. If not given, these simply default to the service name.
- `manipulatable` - Determines whether the bot is marked manipulatable. Only manipulatable clients can be force joined, etc. using PyLink commands. Defaults to False.
- `extra_channels` - Defines a dict mapping network names to a set of channels that the bot should autojoin on that network.
- `desc` - Sets the command description of the service. This is shown in the default HELP command if enabled.

### Getting the UID of a bot

Should you want to get the UID of a service bot on a specific server, use `myservice.uids.get('irc.name')`

### Setting channels to join

All services bots wil automatically join the autojoin channels configured for a specific network, if any.

However, plugins can modify the autojoin entries of a specific bot by adding items to the `myservice.extra_channels` channel set. After sending `irc.proto.join(...)` using the service bot's UID as a source, the bot should permanently remain on that channel throughout KILLs or disconnects.

## Removing services on unload

All plugins using the services API **MUST** have a `die()` function that unregisters all services that they've created. A simple example would be in the `games` plugin:

```python
def die(irc):
    utils.unregisterService('games')
```

## Service bots and commands

Commands for service bots and commands for the main PyLink bot have two main differences.

1) Commands for service bots are bound using `myservice.add_cmd(cmdfunc, 'cmdname')` instead of `utils.add_cmd(...)`

2) Replies for service bot commands are sent using `myservice.reply(irc, text)` instead of `irc.reply(...)`

### Featured commands

Commands for service bots can also be marked as *featured*, which shows it with its command arguments in the default `LIST` command. To mark a command as featured, use `myservice.add_cmd(cmdfunc, 'cmdname', featured=True)`.
