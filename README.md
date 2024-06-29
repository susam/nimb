NIMB
====

NIMB IRC Matrix Bridge (NIMB) is a simple tool that can establish
multiple bridges between multiple IRC channels and Matrix rooms.

NIMB can join multiple IRC and Matrix channels simultaneously.
Whenever it finds a new message posted to any channel it has joined,
it forwards that message to a set of other channels specified via
configuration.

To see NIMB in action, join either of the two channels:

- [#susam:libera.chat](https://web.libera.chat/#susam)
- [#susam:matrix.org](https://app.element.io/#/room/#susam:matrix.org)

The first one is an IRC channel and the second one is a Matrix room.
There is an instance of NIMB running on a private system that has
joined both the channels to bridge them together.  When a message is
posted to one of the two above channels, NIMB forwards the message to
the other channel automatically.

Note: In this document we often refer to both IRC channels and Matrix
rooms as "channels" for the sake of simplicity and brevity.


Contents
--------

* [Get Started](#get-started)
* [Configuration](#configuration)
  * [Simple Configuration](#simple-configuration)
  * [Complex Configuration](#complex-configuration)
  * [Configuration Keys](#configuration-keys)
* [Differences from Matrix Appservice](#differences-from-matrix-appservice)
* [License](#license)
* [Support](#support)


Get Started
-----------

Perform the following steps to get started with NIMB:

 1. Clone this repository.  For example,

    ```sh
    git clone https://github.org/susam/nimb.git
    ```

 2. Create configuration file:

    ```sh
    cd nimb
    cp etc/simple.json nimb.json
    ```

    Then edit the new configuration file named `nimb.json`.  Some
    example values are already populated in this file to help you get
    started.  The initial configuration example provided in this file
    contains entries for two channels: an IRC channel and a Matrix
    room.  You can add more channels to the configuration if you need
    to bridge more than two channels together.

 3. Run NIMB:

    ```sh
    python3 nimb.py
    ```

Note that NIMB does not depend on any external Python library or
package.  It only depends on a recent version of Python 3 and its
standard library.


Configuration
-------------

NIMB reads its configuration from a file named `nimb.json` in the
current working directory.


### Simple Configuration

See [etc/simple.json](etc/simple.json) for a simple example of a
configuration.  Here is the content of this file:

```json
{
  "clients": [
    {
      "type": "irc",
      "tls": true,
      "host": "irc.libera.chat",
      "port": 6697,
      "nick": "...",
      "user": "...",
      "password": "...",
      "channels": [
        {
          "channel": "#nimb",
          "infix": " (libera): ",
          "label": "A",
          "to": ["B"]
        }
      ]
    },
    {
      "type": "matrix",
      "server": "https://matrix.org",
      "username": "@...:matrix.org",
      "password": "...",
      "rooms": [
        {
          "room": "#nimb:matrix.org",
          "infix": " (matrix): ",
          "label": "B",
          "to": ["A"]
        }
      ]
    }
  ]
}
```

The occurrences of triple-dots (`...`) in the above example represent
placeholders that need to be replaced with actual credentials.

The value of the top-level `"clients"` key defines all the IRC or
Matrix clients that NIMB should create to connect to IRC networks and
Matrix servers.  The configuration above specifies that NIMB should
create two clients: one to connect to `irc.libera.chat` and another to
connect to `matrix.org`.

Each client entry has various property names and values that define
the connection parameters.  Each IRC client entry has a `"channels"`
property that defines a list of channels the IRC client should join.
Similarly, each Matrix client entry has a `"rooms"` property that
defines a list of rooms that the Matrix room should join.

In the example above, the configuration for the IRC channel has
`"label"` set to `"A"` and the configuration for the Matrix room has
`"label"` set to `"B"`.  These label values are used in the values of
the `"to"` keys.  When NIMB finds a new message posted to a channel,
it looks up the `"to"` key for that channel.  Its value must be a list
of `"label"` values that were used to label other channels.  NIMB then
forwards the message to all channels labelled with the labels
specified by the `"to"` list.

For example, the above configuration says that when a message is
posted to the IRC channel labelled A, it should be forwarded to the
Matrix room labelled B.  Similarly, when a message is posted to the
room labelled B, it should be forwarded to the channel labelled A.  In
this manner, the above configuration bridges the channel labelled A
and the room labelled B.


### Complex Configuration

It is possible to label multiple channels/rooms with the same label
string.  For example, if three channels are labelled as `"A"` and a
message is received on another channel that has its `"to"` value set
to `["A"]`, then the message received on that channel would be
forwarded to all three channels labelled `"A"`.

It is possible to make quite complex configurations with an arbitrary
number of clients and channels defined with complex forwarding rules
to bridge them.  For example, see [etc/complex.json](etc/complex.json)
that creates two IRC clients and one Matrix client to connect to
several IRC channels and a matrix rooms.  Some of the IRC channels are
labelled A, some are labelled B, and the Matrix room is labelled C.
The `"to"` list for each channel/room specifies where the messages
received on each channel/room should be forwarded to.

It is also possible for the `"to"` list of a channel entry to have the
same label as that of the channel itself.  In such a case, NIMB will
copy every message received on that channel and post it again on the
same channel.  Thus members of the channel would see every message
twice: once posted by the original sender and once again reposted by
NIMB.  Such a configuration is perhaps pretty pointless.  Nevertheless
NIMB is flexible enough to support such a configuration.

NIMB only forwards messages posted by other users.  It never forwards
messages it has posted itself.  In this manner, it avoids infinite
forwarding loops.


### Configuration Keys

The meaning of most configuration keys in the example presented
earlier are self-explanatory, especially, the ones that specify the
connection parameters are self-descriptive.  The following list
describes the keys that are not so obvious:

  - `type`: Client protocol.  Must be either `irc` or `matrix`.

  - `infix`: A string that is inserted between the sender's name and
    the message while forwarding message.  For example, with the above
    configuration example, when a nick named `alice` says `hello,
    world` in the Libera channel, NIMB posts the following message in
    the Matrix channel: `alice (libera): hello, world`.

  - `label`: A string to label a channel.  The label can then be used
    in the `to` list described below.

  - `to`: A list of labels of target channels where messages posted to
    the current channel must be forwarded to.


Differences from Matrix Appservice
----------------------------------

Matrix has an official IRC bridge service that joins the bridged
Matrix room as a user named `appservice`.  Here are some points that
describe how NIMB is different from the Matrix bridge service.

- The Matrix bridge service joins the Matrix room with *Admin* power
  level.  NIMB joins the Matrix room as a regular user with default
  power level.

- In the initial years of this bridge service, it was clumsy to remove
  the Matrix bridge user `appservice` from the Matrix room because one
  admin could not remove another admin from the room.  This is no
  longer an issue.  Unlinking the bridge from a room does remove the
  bridge user from the room.  However, NIMB has always been easily
  removable.  Any admin of a Matrix room can remove NIMB from the room
  provided NIMB itself was not promoted to an admin.

- Since NIMB works as a regular IRC client and a regular Matrix
  client, it can work with any IRC network or Matrix server and does
  not depend on any special IRC or Matrix services to be present.

- The Matrix `appservice` can only bridge one Matrix room to one IRC
  channel.  NIMB can join multiple IRC and Matrix channels
  simultaneously and forward message from any channel to any subset of
  configured channels.  It can even bridge multiple IRC channels
  together.  Similarly, it can also bridge multiple Matrix channels
  together.

- Matrix `appservice` makes the IRC users appear in the Matrix room
  and Matrix users appear in the IRC channel in the respective user
  lists.  NIMB does not do this.  NIMB only forwards messages from one
  channel to another.

- Matrix `appservice` removes users who have been idle for 30+ days.
  This can be annoying to members of rooms with low activity where
  being idle 30+ days might be normal.  NIMB does no such thing.


License
-------

This is free and open source software.  You can use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of it,
under the terms of the MIT License.  See [LICENSE.md][L] for details.

This software is provided "AS IS", WITHOUT WARRANTY OF ANY KIND,
express or implied.  See [LICENSE.md][L] for details.

[L]: LICENSE.md


Support
-------

To report bugs, suggest improvements, or ask questions, please create
a new issue at <http://github.com/susam/nimb/issues>.

<!--

- Update version in pyproject.toml.

- Update CHANGES.md.

- Run the following commands:

  make checks

  git add -p
  git status
  git commit
  git push origin main

  make dist upload verify-upload

  VER=$(grep version pyproject.toml | cut -d '"' -f2)
  git tag $VER -m "NIMB $VER"
  git push origin $VER

-->
