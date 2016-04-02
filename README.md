# PyLink

PyLink is an extensible, plugin-based IRC services framework written in Python. It aims to be:

1) a replacement for the now-defunct Janus.

2) a versatile framework and gateway to IRC.

## Support

Please report any bugs you find to the [issue tracker](https://github.com/GLolol/PyLink/issues). Pull requests are open if you'd like to contribute, though new stuff generally goes to the **devel** branch.

You can also find support via our IRC channels: `#PyLink @ irc.overdrivenetworks.com `([webchat](https://webchat.overdrivenetworks.com/?channels=PyLink,dev)) or `#PyLink @ chat.freenode.net`. Ask your questions and be patient for a response.

## Dependencies

* Python 3.4+
* PyYAML (`pip install pyyaml`)
* *For the servprotect plugin*: python3-expiringdict (`apt-get install python3-expiringdict`; not available in pip)
* *For the changehost and opercmds plugins*: ircmatch (`pip install ircmatch`)

### Supported IRCds

* InspIRCd 2.0.x - module `inspircd`
* charybdis (3.5.x / git master) - module `ts6`
* Elemental-IRCd (6.6.x / git master) - module `ts6`
* UnrealIRCd 4.x - module `unreal`
   - Note: Unreal 3.2, or any mixed 3.2/4.0 networks are **NOT** supported (see [issue #193](https://github.com/GLolol/PyLink/issues/193))

## Setup

1) Rename `example-conf.yml` to `config.yml` and configure your instance there. Note that the configuration format isn't finalized yet - this means that your configuration may break in an update!

2) Run `./pylink` from the command line.

3) Profit???
