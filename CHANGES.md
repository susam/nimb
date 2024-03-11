Changelog
=========

0.2.0 (UNRELEASED)
------------------

### Added

- Forward `JOIN`, `PART`, `NICK`, and `QUIT` messages from IRC.
- Forward member joining and leaving messages from Matrix.
- Send membership change messages as notice to Matrix rooms.

### Changed

- One client/connection per IRC network or Matrix server.
- Channels in the same network/server are joined by the same client.
- Include Matrix user's display name in forwarded messages.
- Reconnect to network/server on encountering error.


0.1.0 (2022-12-28)
------------------

### Added

- Initial release.
- Bridging between multiple IRC channels and Matrix rooms.
- One client/connection per channel/room.
