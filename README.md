# PyLink IRC Services

[webchatlink]: https://webchat.overdrivenetworks.com/?channels=PyLink

[![PyPI version](https://img.shields.io/pypi/v/pylinkirc.svg?maxAge=2592000)](https://pypi.python.org/pypi/pylinkirc/)
[![PyPI supported Python versions](https://img.shields.io/pypi/pyversions/pylinkirc.svg?maxAge=2592000)](https://www.python.org/downloads/)
[![PyPi license](https://img.shields.io/pypi/l/pylinkirc.svg?maxAge=2592000)](LICENSE.MPL2)
[![Live chat](https://img.shields.io/badge/IRC-live%20chat%20%C2%BB-green.svg)][webchatlink]

PyLink is an extensible, plugin-based IRC services framework written in Python. It aims to be:

1) a replacement for the now-defunct Janus.

2) a versatile framework for developing IRC services.

PyLink and any bundled software are licensed under the Mozilla Public License, version 2.0 ([LICENSE.MPL2](LICENSE.MPL2)). The corresponding documentation in the [docs/](docs/) folder is licensed under the Creative Attribution-ShareAlike 4.0 International License. ([LICENSE.CC-BY-SA-4.0](LICENSE.CC-BY-SA-4.0))

## Support the project
[![Donate via PayPal](https://img.shields.io/badge/donate-paypal-50CAF2.svg)](https://www.paypal.me/jlucode)

## Obtaining support

**First, MAKE SURE you've read the [FAQ](docs/faq.md)!**

**When upgrading between major versions, remember to read the [release notes](RELNOTES.md) for any breaking changes!**

Please report any bugs you find to the [issue tracker](https://github.com/jlu5/PyLink/issues). Pull requests are open if you'd like to contribute, though new stuff generally goes to the **devel** branch.

You can also find support via our IRC channel at `#PyLink @ irc.overdrivenetworks.com `([webchat][webchatlink]). Ask your questions and be patient for a response.

## Installation

### Pre-requisites
* CPython 3.4 or above (other intepreters are untested and unsupported)
* A Unix-like operating system: PyLink is actively developed on Linux only, so we cannot guarantee that things will work properly on other systems.

If you are a developer and want to help make PyLink more portable, patches are welcome.

### Installing from source

1) First, make sure the following dependencies are met:

    * Setuptools (`pip3 install setuptools`)
    * PyYAML (`pip3 install pyyaml`)
    * ircmatch (`pip3 install ircmatch`)
    * *For password encryption*: Passlib (`pip3 install passlib`)
    * *For better PID file tracking (i.e. removing stale PID files in the case of a crash)*: psutil (`pip3 install psutil`)
    * *For the servprotect plugin*: expiringdict (`pip3 install expiringdict`)

2) Clone the repository: `git clone https://github.com/jlu5/PyLink && cd PyLink`

3) Pick your branch.
    * By default you'll be on the **master** branch, which contains the latest stable code. This branch is recommended for production networks that don't require new features or intensive bug fixes as they are developed.
    * The **devel** branch is where active development goes, and it can be accessed by running `git checkout devel` in your Git tree.

4) Install PyLink using `python3 setup.py install` (global install) or `python3 setup.py install --user` (local install)
    * Note: `--user` is a *literal* string; *do not* replace it with your username.
    *  **Whenever you switch branches or update PyLink's sources via `git pull`, you will need to re-run this command for changes to apply!**

### Installing via PyPI (stable branch only)
1) Make sure you're running the right pip command: on most distros, pip for Python 3 uses the command `pip3`.

2) Run `pip3 install pylinkirc` to download and install PyLink. pip will automatically resolve dependencies.

3) Download or copy https://github.com/jlu5/PyLink/blob/master/example-conf.yml for an example configuration.

## Configuration

1) Rename `example-conf.yml` to `pylink.yml` (or a similarly named `.yml` file) and configure your instance there. Note that the configuration format isn't finalized yet - this means that your configuration may break in an update!

2) Run `pylink` from the command line. PyLink will load its configuration from `pylink.yml` by default, but you can override this by running `pylink` with a config argument (e.g. `pylink mynet.yml`).

## Supported IRCds

### Primary support

These IRCds (in alphabetical order) are frequently tested and well supported. If any issues occur, please file a bug on the issue tracker.

* [charybdis](https://github.com/charybdis-ircd/charybdis) (3.5+) - module `ts6`
    - For KLINE support to work, a `shared{}` block should be added for PyLink on all servers.
* [InspIRCd](http://www.inspircd.org/) 2.0.x - module `inspircd`
    - For vHost setting to work, `m_chghost.so` must be loaded. For ident and realname changing support, `m_chgident.so` and `m_chgname.so` must be loaded respectively.
    - Supported channel, user, and prefix modes are negotiated on connect, but hotloading modules that change these is not supported. After changing module configuration, it is recommended to SQUIT PyLink to force a protocol renegotiation.
* [Nefarious IRCu](https://github.com/evilnet/nefarious2) (2.0.0+) - module `p10`
    - Note: Both account cloaks (user and oper) and hashed IP cloaks are optionally supported (`HOST_HIDING_STYLE` settings 0 to 3). Make sure you configure PyLink to match your IRCd settings.
* [UnrealIRCd](https://www.unrealircd.org/) 4.x (4.0.12+) - module `unreal`
    - UnrealIRCd 4.x before version 4.0.12 suffers from [bug #4890](https://bugs.unrealircd.org/view.php?id=4890) which causes hostname desyncs on servers not directly linked to PyLink (e.g. `pylink<->serverA<->serverB` creates desynced hostnames on server B). This problem is fixed by upgrading your IRCds.
    - Linking to UnrealIRCd 3.2 servers is only possible when using an UnrealIRCd 4.x server as a hub, with topology such as `pylink<->unreal4<->unreal3.2`. We nevertheless encourage you to upgrade so all your IRCds are running the same version.

### Extended support

Support for these IRCds exist, but are not tested as frequently and thoroughly. Bugs should be filed if there are any issues, though they may not always be fixed in a timely fashion.

* [beware-ircd](http://ircd.bircd.org/) (1.6.3) - module `p10`
    - Because bircd disallows BURST after ENDBURST for regular servers, U-lines are required for all PyLink servers. Fortunately, wildcards are supported in U-lines, so you can add something along the lines of `U:<your pylink server>:` and `U:*.relay:` (adjust accordingly for your relay server suffix).
    - Use `ircd: snircd` as the target IRCd.
    - Halfops, `sethost` (`+h`), and account-based cloaking (`VHostStyle=1`) are supported. Crypted IPs and static hosts (`VHostStyle` 2 and 3) are NOT.
* [ChatIRCd](http://www.chatlounge.net/software) (1.2.x / git master) - module `ts6`
    - For KLINE support to work, a `shared{}` block should be added for PyLink on all servers.
* [Elemental-IRCd](https://github.com/Elemental-IRCd/elemental-ircd) (6.6.x / git master) - module `ts6`
    - For KLINE support to work, a `shared{}` block should be added for PyLink on all servers.
* [InspIRCd](http://www.inspircd.org/) 3.0.x (git master) - module `inspircd`
    - The same notes for InspIRCd 2.x apply here as well.
* [IRCd-Hybrid](http://www.ircd-hybrid.org/) (8.2.x / svn trunk) - module `hybrid`
    - For host changing support and optimal functionality, a `service{}` block / U-line should be added for PyLink on every IRCd across your network.
    - For KLINE support to work, a `shared{}` block should also be added for PyLink on all servers.
* [ircd-ratbox](http://www.ratbox.org/) (3.x) - module `ts6`
    - Host changing is not supported.
    - On ircd-ratbox, all known IPs of users will be shown in `/whois`, even if the client is e.g. a cloaked relay client. If you're paranoid about this, turn off Relay IP forwarding on the ratbox network(s).
    - For KLINE support to work, a `shared{}` block should be added for PyLink on all servers.
* [IRCu](http://coder-com.undernet.org/) (u2.10.12.16+) - module `p10`
    - Host changing is not supported.
* [juno-ircd](https://github.com/cooper/juno) (13.x / ava) - module `ts6` (see [configuration example](https://github.com/cooper/juno/blob/master/doc/ts6.md#pylink))
* [ngIRCd](https://ngircd.barton.de/) (24+) - module `ngircd`
    - For GLINEs to propagate, the `AllowRemoteOper` option must be enabled in ngIRCd.
    - `+` (modeless) channels are not supported, and should be disabled for PyLink to function correctly.
* [snircd](https://development.quakenet.org/) (1.3.x+) - module `p10`
    - Outbound host changing (i.e. for the `changehost` plugin) is not supported on P10 variants other than Nefarious.

Other TS6 and P10 variations may work, but are not officially supported.

### Clientbot

Since v1.0, PyLink supports connecting to IRCds as a relay bot and forwarding users back, similar to Janus' Clientbot. This can be useful if the IRCd a network used isn't supported, or if you want to relay certain channels without fully linking with a network.

For Relay to work properly with Clientbot, be sure to load the `relay_clientbot` plugin in conjunction with `relay`.
