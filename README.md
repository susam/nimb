NIMB
====

NIMB IRC Matrix Bridge (NIMB) is a simple tool that can establish
multiple bridges between multiple IRC channels and Matrix rooms.

In this document we will often refer to both IRC channels and Matrix
rooms as "channels" for the sake of simplicity and brevity.

NIMB can join multiple IRC and Matrix channels simultaneously.
Whenever it finds a new message posted to any channel it has joined,
it forwards that message to a set of other channels specified via
configuration.

To see NIMB in action, join either of the two channels:

- [#susam:libera.chat](https://web.libera.chat/#susam)
- [#susam:matrix.org](https://app.element.io/#/room/#susam:matrix.org)

The first one is an IRC channel and the second one is a Matrix room.
There is an instance of NIMB running on one of my private systems that
has joined both the channels to bridge them together. When a message
is posted to one of the two above channels, NIMB will forward the
message to the other channel automatically.


Get Started
-----------

Perform the following steps to get started with NIMB:

 1. Clone this repository. For example,

    ```sh
    git clone https://github.org/susam/nimb.git
    ```

 2. Create configuration file:

    ```sh
    cd nimb
    cp etc/template.json nimb.json
    ```

    Then edit the new configuration file named `nimb.json`. Some
    example values are already populated in this file to help you get
    started. The initial configuration example provided in this file
    contains entries for two channels: an IRC channel and a Matrix
    room. You can add more channels to the configuration if you need
    to bridge more than two channels together.

 3. Run NIMB:

    ```sh
    python3 nimb.py
    ```

Note that NIMB does not depend on any external Python library or
package. It only depends on a recent version of Python 3 and its
standard library.


Configuration
-------------

NIMB reads its configuration from a file named `nimb.json` in the
current working directory.

See [etc/nimb.json](etc/simple.json) for a simple example of a
configuration. Here is the content of this file:

```json
{
  "channels": [
    {
      "id": "A",
      "to": ["B"],
      "type": "irc",
      "tls": true,
      "host": "irc.libera.chat",
      "port": 6697,
      "nick": "...",
      "password": "...",
      "channel": "#nimb",
      "infix": " (libera): "
    },
    {
      "id": "B",
      "to": ["A"],
      "type": "matrix",
      "server": "https://matrix.org",
      "username": "@...:matrix.org",
      "password": "...",
      "room": "#nimb:matrix.org",
      "infix": " (matrix): "
    }
  ]
}
```

The triple-dots (`...`) in the above example represents placeholders
that need to be replaced with actual credentials.

The value of the top-level `"channels"` key defines all the channels
that NIMB should join. The configuration above specifies an IRC
channel and a Matrix room.

The configuration for the IRC channel has `"id"` set to `"A"` and the
configuration for the Matrix room has `"id"` set to `"B"`. These ID
values are used in the values of the `"to"` keys. When NIMB finds a
new message posted to a channel, it looks up the `"to"` key for that
channel. Its value must be a list of `"id"` values that define other
channels. NIMB then forwards the message to all channels identified by
the IDs specified by the `"to"` list.

For example, the above configuration says that when a message is
posted to channel A (an IRC channel on Libera), it should be forwarded
to channel B (a Matrix room). Similarly, when a message is posted to
channel B, it should be forwarded to channel A. In this manner, the
above configuration bridges channels A and B.

The meaning of most configuration keys for each channel entry in the
configuration example above are self-explanatory, especially, the ones
that specify the connection parameters are self-descriptive. The
following list describes the keys that are not so obvious:

  - `id`: An identifier that identifies the configuration entry.

  - `to`: A list of identifiers of target channels where messages
    posted to the current channel must be forwarded to.

  - `type`: Protocol name. Must be either `irc` or `matrix`.

  - `infix`: A string that is inserted between the sender's name and
    the message while forwarding message. For example, with the above
    configuration example, when a nick named `alice` says `hello,
    world` in the Libera channel, NIMB posts the following message in
    the Matrix channel: `alice (libera): hello, world`.

It is possible to make quite complex configurations with an arbitrary
number of channels defined with complex forwarding rules to bridge
them. For example, see [etc/complex.json](etc/complex.json) that
defines four channels A, B, C, and D and forwards messages from A to B
and C, from B to C and D, from C to A and B, and from D to C.

NIMB only forwards messages posted by other users. It never forwards
messages it has posted itself. In this manner, it avoids infinite
forwarding loops.


Differences from Matrix Appservice
----------------------------------

Matrix has an official IRC bridge service that joins the bridged
Matrix room as a user named `appservice`. Here are some points that
describe how NIMB is different from the Matrix bridge service.

- The Matrix bridge service joins the Matrix room with *Admin* power
  level. NIMB joins the Matrix room as a regular user with default
  power level.

- In the initial years of this bridge service, it was clumsy to remove
  the Matrix bridge user `appservice` from the Matrix room because one
  admin cannot remove another admin from the room. This is no longer
  an issue. Unlinking the bridge from a room does remove the bridge
  user from the room. However, NIMB has always been easily removable.
  Any admin of a Matrix room can remove NIMB from the room.

- Since NIMB works as a regular IRC client and a regular Matrix
  client, it can work with any IRC network or Matrix server and does
  not depend on any special IRC or Matrix services to be present.

- The Matrix `appservice` can only bridge one Matrix room to one IRC
  channel. NIMB can join multiple IRC and Matrix channels
  simultaneously and forward message from any channel to any subset of
  other channels. It can even bridge multiple IRC channels together.
  Similarly, it can also bridge multiple Matrix channels together.

- Matrix `appservice` makes the IRC users appear in the Matrix room
  and Matrix users appear in the IRC channel in the respective user
  lists. NIMB does not do this. NIMB only forwards messages from one
  channel to another.

- Matrix `appservice` removes users who have been idle for 30+ days.
  This can be annoying to members of rooms with low activity where
  being idle 30+ days might be normal. NIMB does no such thing.


License
-------

This is free and open source software. You can use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of it,
under the terms of the MIT License. See [LICENSE.md][L] for details.

This software is provided "AS IS", WITHOUT WARRANTY OF ANY KIND,
express or implied. See [LICENSE.md][L] for details.

[L]: LICENSE.md


Support
-------

To report bugs, suggest improvements, or ask questions, please create
a new issue at <http://github.com/susam/nimb/issues>.
