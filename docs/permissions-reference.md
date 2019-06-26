# PyLink Permissions Reference

Below is a list of all the permissions defined by PyLink and its official plugins.

## PyLink Core
- `core.clearqueue` - Grants access to the `clearqueue` command.
- `core.load` - Grants access to the `load` command.
- `core.rehash` - Grants access to the `rehash` command.
- `core.reload` - Grants access to the `reload`, `load`, and `unload` commands. (This implies access to `load` and `unload` because `reload` is really just those two commands combined.)
- `core.shutdown` - Grants access to the `shutdown` command.
- `core.unload` - Grants access to the `unload` command.

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

- `bots.join` - Grants access to the `join` command. `bots.joinclient` is a deprecated alias for this, retained for compatibility with PyLink < 2.0-rc1.
- `bots.msg` - Grants access to the `msg` command.
- `bots.nick` - Grants access to the `nick` command.
- `bots.part` - Grants access to the `part` command.
- `bots.quit` - Grants access to the `quit` command.
- `bots.spawnclient` - Grants access to the `spawnclient` command.

## Changehost

- `changehost.applyhosts` - Grants access to the `applyhosts` command.

## Commands
- `commands.echo` - Grants access to the `echo` command.
- `commands.loglevel` - Grants access to the `loglevel` command.
- `commands.logout.force` - Allows forcing logouts on other users via the `logout` command.
- `commands.showchan` - Grants access to the `showchan` command. **With the default permissions set, this is granted to all users.**
- `commands.shownet` - Grants access to the `shownet` command (basic info including netname, protocol module, and encoding). **With the default permissions set, this is granted to all users.**
- `commands.shownet.extended` - Grants access to extended info in `shownet`, including connected status, target IP:port, and configured PyLink hostname / SID.
- `commands.showuser` - Grants access to the `showuser` command. **With the default permissions set, this is granted to all users.**
- `commands.status` - Grants access to the `status` command. **With the default permissions set, this is granted to all users.**

## Exec
- `exec.exec` - Grants access to the `exec` and `iexec` commands.
- `exec.eval` - Grants access to the `eval`, `ieval`, `peval`, and `pieval` commands.
- `exec.inject` - Grants access to the `inject` command.
- `exec.threadinfo` - Grants access to the `threadinfo` command.

## Global
- `global.global` - Grants access to the `global` command.

## Networks
- `networks.autoconnect` - Grants access to the `autoconnect` command.
- `networks.disconnect` - Grants access to the `disconnect` command.
- `networks.reloadproto` - Grants access to the `reloadproto` command.
- `networks.remote` - Grants access to the `remote` command.

## Opercmds
- `opercmds.checkban` - Grants access to the `checkban` command.
- `opercmds.checkban.re` - Grants access to the `checkbanre` command **if** the caller also has `opercmds.checkban`.
- `opercmds.chghost` - Grants access to the `chghost` command.
- `opercmds.chgident` - Grants access to the `chgident` command.
- `opercmds.chgname` - Grants access to the `chgname` command.
- `opercmds.jupe` - Grants access to the `jupe` command.
- `opercmds.kick` - Grants access to the `kick` command.
- `opercmds.kill` - Grants access to the `kill` command.
- `opercmds.massban` - Grants access to the `massban` command.
- `opercmds.massban.re` - Grants access to the `massbanre` command **if** the caller also has `opercmds.massban`.
- `opercmds.mode` - Grants access to the `mode` command.
- `opercmds.topic` - Grants access to the `topic` command.

## Raw
- `raw.raw` - Grants access to the `raw` command. `exec.raw` is equivalent to this and retained for compatibility with PyLink 1.x.
- `raw.raw.unsupported_network` - Allows use of the `raw` command on servers other than Clientbot.

## Relay
These permissions are granted to all opers when the `relay::allow_free_oper_links` option is set (this is the default):

- `relay.chandesc.remove` - Allows removing channel descriptions via the `chandesc` command.
- `relay.chandesc.set` - Allows setting / updating channel descriptions via the `chandesc` command.
- `relay.claim` - Grants access to the `claim` command.
- `relay.create` - Grants access to the `create` command.
- `relay.delink` - Grants access to the `delink` command.
- `relay.destroy` - Grants access to the `destroy` command.
- `relay.link` - Grants access to the `link` command.

These permissions are always granted to all opers:
- `relay.linkacl` - Allows managing LINKACL entries via the `linkacl` command.
- `relay.linkacl.view` - Allows viewing LINKACL entries via the `linkacl` command.

These permissions are not granted to anyone by default:
- `relay.destroy.remote` - Allows destroying remote channels.
- `relay.link.force_ts` - Grants access to the `link` command's `--force-ts` option (skip TS and target network is connected checks).
- `relay.linked` - Grants access to the `link` command. **With the default permissions set, this is granted to all users.**
- `relay.purge` - Grants access to the `purge` command.
- `relay.savedb` - Grants access to the `savedb` command.

## Servermaps
- `servermaps.localmap` - Grants access to the `localmap` command.
- `servermaps.map` - Grants access to the `map` command.

## Stats
- `stats.c`, `stats.o`, `stats.u` - Grants access to remote `/stats` calls with the corresponding letter.
- `stats.uptime` - Grants access to the `stats` command.
