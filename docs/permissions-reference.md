# PyLink Permissions Reference

Below is a list of all the permissions defined by PyLink and its official plugins. For instructions on how to fine-tune permissions, see [example-permissions.yml](../example-permissions.yml).

## PyLink Core
- `core.clearqueue` - Allows access to the `clearqueue` command.
- `core.shutdown` - Allows access to the `shutdown` command.
- `core.load` - Allows access to the `load` command.
- `core.unload` - Allows access to the `unload` command.
- `core.reload` - Allows access to the `reload`, `load`, and `unload` commands. (This implies access to `load` and `unload` because `reload` is really just those two commands combined.)
- `core.rehash` - Allows access to the `rehash` command.

## Automode

By default, Automode integrates with Relay by only allowing access lists to be created / manipulated on channels that are owned by a network via Relay.

- `automode.manage` OR `automode.manage.*`: ability to manage Automode (use `setacc` and `delacc`) on all channels on the network where the user is connected.
- `automode.manage.relay_owned`: ability to manage Automode on channels owned by the current network in Relay. If Relay isn't loaded or the channel in question isn't shared via Relay, this permission check FAILS. **With the default permissions set, this is granted to all opers.**
- `automode.manage.#channel`: ability to manage Automode on the specific given channel.

- `automode.list` OR `automode.list.*`: ability to list Automode on all channels. **With the default permissions set, this is granted to all opers.**
- `automode.list.relay_owned`: ability to list automode on channels owned via Relay. If Relay isn't loaded or the channel in question isn't shared via Relay, this permission check FAILS.
- `automode.list.#channel`: ability to list Automode access entries on the specific given channel.

- `automode.sync` OR `automode.sync.*`: ability to sync automode on all channels.
- `automode.sync.relay_owned`: ability to sync automode on channels owned via Relay. If Relay isn't loaded or the channel in question isn't shared via Relay, this permission check FAILS. **With the default permissions set, this is granted to all opers.**
- `automode.sync.#channel`: ability to sync automode on the specific given channel.

- `automode.clear` OR `automode.clear.*`: ability to clear automode on all channels.
- `automode.clear.relay_owned`: ability to clear automode on channels owned via Relay. If Relay isn't loaded or the channel in question isn't shared via Relay, this permission check FAILS.
- `automode.clear.#channel`: ability to clear automode on the specific given channel.

- `automode.savedb`: ability to save the automode DB.

Remote versions of the `manage`, `list`, `sync`, and `clear` commands also exist for cross-network manipulation (e.g. `automode.remotemanage.*`)

## Bots

- `bots.spawnclient` - Allows access to the `spawnclient` command.
- `bots.quit` - Allows access to the `quit` command.
- `bots.joinclient` - Allows access to the `joinclient` command.
- `bots.nick` - Allows access to the `nick` command.
- `bots.part` - Allows access to the `part` command.
- `bots.msg` - Allows access to the `msg` command.

## Changehost

- `changehost.applyhosts` - Allows access to the `applyhosts` command.

## Commands
- `commands.status` - Allows access to the `status` command. **With the default permissions set, this is granted to all users.**
- `commands.showuser` - Allows access to the `showuser` command. **With the default permissions set, this is granted to all users.**
- `commands.showchan` - Allows access to the `showchan` command. **With the default permissions set, this is granted to all users.**
- `commands.echo` - Allows access to the `echo` command.
- `commands.logout.force` - Allows forcing logouts on other users via the `logout` command.
- `commands.loglevel` - Allows access to the `loglevel` command.

## Exec
- `exec.exec` - Allows access to the `exec` command.
- `exec.eval` - Allows access to the `eval` command.
- `exec.raw` - Allows access to the `raw` command.
- `exec.inject` - Allows access to the `inject` command.

## Global
- `global.global` - Allows access to the `global` command.

## Networks
- `networks.disconnect` - Allows access to the `disconnect` command.
- `networks.autoconnect` - Allows access to the `autoconnect` command.
- `networks.remote` - Allows access to the `remote` command.
- `networks.reloadproto` - Allows access to the `reloadproto` command.

## Opercmds
- `opercmds.checkban` - Allows access to the `checkban` command.
- `opercmds.jupe` - Allows access to the `jupe` command.
- `opercmds.kick` - Allows access to the `kick` command.
- `opercmds.kill` - Allows access to the `kill` command.
- `opercmds.mode` - Allows access to the `mode` command.
- `opercmds.topic` - Allows access to the `topic` command.

## Relay
- `relay.claim` - Allows access to the `claim` command.
- `relay.create` - Allows access to the `create` command. **With the default permissions set, this is granted to all opers.**
- `relay.delink` - Allows access to the `delink` command. **With the default permissions set, this is granted to all opers.**
- `relay.destroy` - Allows access to the `destroy` command. **With the default permissions set, this is granted to all opers.**
- `relay.destroy.remote` - Allows access to the `remote` command.
- `relay.linkacl` - Allows access to the `linkacl` command. **With the default permissions set, this is granted to all opers.**
- `relay.linkacl.view` - Allows access to the `view` command. **With the default permissions set, this is granted to all opers.**
- `relay.link` - Allows access to the `link` command. **With the default permissions set, this is granted to all opers.**
- `relay.link.force` - Allows access to the `--force` option in the `link` command (skip TS and target network is connected checks).
- `relay.linked` - Allows access to the `link` command. **With the default permissions set, this is granted to all users.**
- `relay.purge` - Allows access to the `purge` command.
- `relay.savedb` - Allows access to the `savedb` command.

## Servermaps
- `servermaps.map` - Allows access to the `map` and `localmap` commands.

## Stats
- `stats.uptime` - Allows access to the `stats` command.
