# PyLink Services Bot API

The goal of PyLink's Services API is to make writing custom services easier. It is able to automatically spawn service bots on connect, handle rejoins on kill and kick, and expose a way for plugins to bind commands to various services bots. It also handles U-line servprotect modes when enabled and supported on a particular network (i.e. the `protect_services` option).

## Basic service creation

Services can be registered and created using code similar to the following in a plugin:

```python

from pylinkirc import utils, world

# Description is optional (though recommended), and usually around a sentence or two.
desc = "Optional description of servicenick, in sentence form."

# First argument is the internal service name.
# utils.register_service() returns a utils.ServiceBot instance, which is also stored
# as world.services['myservice'].
myservice = utils.register_service('myservice', desc=desc)
```

`utils.register_service()` passes its arguments directly to the `utils.ServiceBot` class constructor, which in turn supports the following options:

- **`name`** - defines the service name (mandatory)
- `default_help` - Determines whether the default HELP command should be used for the service. Defaults to True.
- `default_list` - Determines whether the default LIST command should be used for the service. Defaults to True.
- `default_nick` - Sets the default nick this service should use if the user doesn't provide it. Defaults to the same as the service name.
- `manipulatable` - Determines whether the bot is marked manipulatable. Only manipulatable clients can be force joined, etc. using PyLink commands. Defaults to False.
- `desc` - Sets the command description of the service. This is shown in the default HELP command if enabled.

**NOTE**: It is convention for the service name in `utils.register_service('SERVICE')` to match your plugin name, as the services API implicitly loads [configuration options](../advanced-services-config.md) from config blocks named `SERVICE:` (which you may want to put plugin options in as well).

Implementation note: if the `spawn_service` option is disabled (either globally or for your service bot), `register_service` will return the main PyLink `ServiceBot` instance (i.e. `world.services['pylink']`), which you can modify as usual. `unregister_service` calls to your service name will be silently ignored as no `ServiceBot` instance is actually registered for that name. Altogether, this allows service-spawning plugins to function normally regardless of the `spawn_service` value.

### Getting the UID of a bot

To obtain the UID of a service bot on a specific network, use `myservice.uids.get(irc.name)` (where `irc` is the network object).

### Removing services on unload

All plugins using the services API should have a `die()` function that unregisters all service bots that they've created. A simple example would be in the `games` plugin:

```python
def die(irc=None):
    utils.unregister_service('games')
```

Should your service bot define any persistent channels, you will also want to clear them on unload via `myservice.clear_persistent_channels(None, 'your-namespace', ...)`

## Persistent channel joining

Since PyLink 2.0-alpha3, persistent channels are handled in a plugin specific manner. For any service bot on any network, a plugin can register a list of channels that the bot should join persistently (i.e. through kicks and kills). Instead of removing channels from service bots directly, plugins then "request" parts through the services API, which succeed only if no other plugins still mark the channel as persistent. This rework fixes [edge-case desyncs](https://github.com/jlu5/PyLink/issues/265) in earlier versions when multiple plugins change a service bot's channel list, and replaces the `ServiceBot.extra_channels` attribute (which is no longer supported).

Note: Autojoin channels defined in a network's server block are always treated as persistent on that network.

### Channel management methods

Channels, persistent and otherwise are managed through the following functions implemented by `ServiceBot`. While namespaces for channel registrations can technically be any string, it is preferable to keep them close (or equal) to your plugin name.

- `myservice.add_persistent_channel(irc, namespace, channel, try_join=True)`: Adds a persistent channel to the service bot on the given network and namespace.
    - `try_join` determines whether the service bot should try to join the channel immediately; you can disable this if you prefer to manage joins by yourself.
- `myservice.remove_persistent_channel(irc, namespace, channel, try_part=True, part_reason='')`: Removes a persistent channel from the service bot on the given network and namespace.
    - `try_part` determines whether a part should be requested from the channel immediately. (`part_reason` is ignored if this is False)
- `myservice.get_persistent_channels(irc, namespace=None)`: Returns a set of persistent channels for the IRC network, optionally filtering by namespace is one is given. The channels defined in the network's server block are also included because they are always treated as persistent.
- `myservice.clear_persistent_channels(irc, namespace, try_part=True, part_reason='')`: Clears all the persistent channels defined by a namespace. `irc` can also be `None` to clear persistent channels for all networks in this namespace.
- `myservice.join(irc, channels, ignore_empty=True)`: Joins the given service bot to the given channel(s). `channels` can be an iterable of channel names or the name of a single channel (type `str`).
    - The `ignore_empty` option sets whether we should skip joining empty channels and join them later when we see someone else join (if it is marked persistent). This option is automatically *disabled* on networks where we cannot monitor channels we're not in (e.g. on Clientbot).
    - Before 2.0-alpha3, this function implicitly marks channels it receives to be persistent - this is no longer the case!
- `myservice.part(irc, channels, reason='')`: Requests a part from the given channel(s) - that is, leave only if no other plugins still register it as a persistent channel.
    - `channels` can be an iterable of channel names or the name of a single channel (type `str`).

### A note on dynamicness

As of PyLink 2.0-alpha3, persistent channels are also "dynamic" in the sense that PyLink service bots will part channels marked persistent when they become empty, and rejoin when they are recreated. This feature will hopefully be more fine-tunable in future releases.

Dynamic channels are disabled on networks with the [`visible-state-only` protocol capability](pmodule-spec.md#pylink-protocol-capabilities) (e.g. Clientbot), where it is impossible to monitor the state of channels the bot is not in.

## Service bots and commands

Commands for service bots and commands for the main PyLink bot have two main differences.

1) Commands for service bots are bound using `myservice.add_cmd(cmdfunc, 'cmdname')` instead of `utils.add_cmd(...)`

2) Replies for service bot commands are sent using `myservice.reply(irc, text)` instead of `irc.reply(...)`

### Featured commands

Commands for service bots can also be marked as *featured*, which shows it with its command arguments in the default `LIST` command. To mark a command as featured, enable the `featured` option when binding it: e.g. `myservice.add_cmd(cmdfunc, featured=True)`.

### Command aliases

Since PyLink 2.0-alpha1, `ServiceBot.add_cmd(...)` and `utils.add_cmd(...)` support assigning aliases to a command by defining the `aliases` argument. Command aliases do not show in `LIST`, allowing command listings to be much cleaner. Instead, they are only mentioned when `HELP` is called on an alias command name or its parent.

Example:

```python
myservice.add_cmd(functwo, aliases=('abc',))
myservice.add_cmd(somefunc, aliases=('command1', 'command2'))
```

Note: use `(variable,)` when defining one length tuples to [prevent them from being parsed as a single string](https://wiki.python.org/moin/TupleSyntax).
