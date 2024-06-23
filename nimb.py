#!/usr/bin/env python3

"""NIMB - NIMB IRC Matrix Bridge."""

from __future__ import annotations

import json
import logging
import pathlib
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator

_NAME = "nimb"
_log = logging.getLogger(_NAME)


# Internet Relay Chat
# -------------------


def _parse_line(line: str) -> tuple[str | None, str, str | None, str | None]:
    # RFC 1459 - 2.3.1
    # <message>  ::= [':' <prefix> <SPACE> ] <command> <params> <crlf>
    # <prefix>   ::= <servername> | <nick> [ '!' <user> ] [ '@' <host> ]
    # <command>  ::= <letter> { <letter> } | <number> <number> <number>
    # <SPACE>    ::= ' ' { ' ' }
    # <params>   ::= <SPACE> [ ':' <trailing> | <middle> <params> ]
    #
    # Example: :alice!Alice@user/alice PRIVMSG #hello :hello
    # Example: PING :foo.example.com
    if line[0] == ":":
        prefix, rest = line[1:].split(maxsplit=1)
    else:
        prefix, rest = None, line

    sender, command, middle, trailing = None, None, None, None

    if prefix:
        sender = prefix.split("!")[0]

    command_and_rest = rest.split(None, 1)
    command = command_and_rest[0].upper()

    if len(command_and_rest) == 2:  # noqa: PLR2004 (magic-value-comparison)
        params = command_and_rest[1].split(":", 1)
        middle = params[0].strip()
        if len(params) == 2:  # noqa: PLR2004 (magic-value-comparison)
            trailing = params[1].strip()

    return sender, command, middle, trailing


class IRCClient:
    """IRC client."""

    def __init__(
        self,
        client_config: dict[str, Any],
        callback: Callable[[list[str], str, str], None],
    ) -> None:
        """Initialize IRC client."""
        self._log = logging.getLogger(type(self).__name__)
        self._tls = client_config["tls"]
        self._host = client_config["host"]
        self._port = client_config["port"]
        self._nick = client_config["nick"]
        self._password = client_config["password"]
        self._channels = client_config["channels"]
        self._lock = threading.Lock()
        self._callback = callback
        self._recovery_delay = 1
        self.running = True
        self._channel_nicks: dict[str, set[str]] = {}

    def __str__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}: {self._host}, {self._port}, {self._nick}"

    def run(self) -> None:
        """Connect to IRC network and forward messages."""
        while self.running:
            try:
                self._run()
            except Exception:  # noqa: PERF203, BLE001 (try-except-in-loop, blind-except)
                self._log.exception("Client encountered error")
                self._log.info("Reconnecting in %d s", self._recovery_delay)
                time.sleep(self._recovery_delay)
                self._recovery_delay = min(self._recovery_delay * 2, 3600)

    def _run(self) -> None:
        self._connect()
        self._auth()
        self._join()
        self._monitor()

    def _connect(self) -> None:
        self._socket = socket.create_connection((self._host, self._port))
        if self._tls:
            tls_context = ssl.create_default_context()
            self._socket = tls_context.wrap_socket(
                self._socket,
                server_hostname=self._host,
            )

    def _auth(self) -> None:
        self._lock_send(f"PASS {self._password}")
        self._lock_send(f"NICK {self._nick}")
        self._lock_send(
            f"USER {self._nick} {self._nick} {self._host} :{self._nick}",
        )

    def _join(self) -> None:
        for channel in self._channels:
            self._lock_send(f"JOIN {channel['channel']}")
            self._channel_nicks[channel["channel"]] = set()

    def _monitor(self) -> None:  # noqa: C901, PLR0915, PLR0912
        for line in self._recv():
            self._log.info("recv: %s", line)
            sender, command, middle, trailing = _parse_line(line)
            self._log.info("parsed: %s, %s, %s, %s", sender, command, middle, trailing)
            if command == "PING":
                self._lock_send(f"PONG :{trailing}")
            elif command == "353":
                if middle is None or trailing is None:
                    _log.warning("Malformed 353 payload")
                    continue
                channel_name = middle.split()[-1]
                nicks = trailing.split()
                nicks = [nick[1:] if nick[0] == "@" else nick for nick in nicks]
                nicks = [nick[1:] if nick[0] == "+" else nick for nick in nicks]
                for nick in nicks:
                    self._channel_nicks[channel_name].add(nick)
            elif command == "PRIVMSG":
                if middle is None or trailing is None:
                    _log.warning("Malformed PRIVMSG payload")
                    continue
                channel = self._find_channel_config(middle)
                infix = channel["infix"]
                self._callback(channel["to"], f"<{sender}{infix}> ", trailing)
                self._recovery_delay = 1
            elif command == "JOIN":
                if sender is None or middle is None:
                    _log.warning("Malformed JOIN payload")
                    continue
                channel = self._find_channel_config(middle)
                message = (
                    f'{sender}{channel["infix"]} has joined '
                    f'{channel["channel"]} ({self._host})'
                )
                self._channel_nicks[channel["channel"]].add(sender)
                self._callback(channel["to"], "", message)
                self._recovery_delay = 1
            elif command == "PART":
                if sender is None or middle is None:
                    _log.warning("Malformed PART payload")
                    continue
                channel = self._find_channel_config(middle)
                reason = f" [{trailing}]" if trailing is not None else ""
                message = (
                    f'{sender}{channel["infix"]} has left '
                    f'{channel["channel"]} ({self._host}){reason}'
                )
                self._channel_nicks[channel["channel"]].discard(sender)
                self._callback(channel["to"], "", message)
                self._recovery_delay = 1
            elif command == "NICK":
                if sender is None or trailing is None:
                    _log.warning("Malformed NICK payload")
                    continue
                nick_channels = self._find_channels_containing_nick(sender)
                message = f"{sender} is now known as {trailing} on {self._host}"
                for channel_name in nick_channels:
                    channel = self._find_channel_config(channel_name)
                    self._channel_nicks[channel_name].discard(sender)
                    self._channel_nicks[channel_name].add(trailing)
                    self._callback(channel["to"], "", message)
                self._recovery_delay = 1
            elif command == "QUIT":
                if sender is None:
                    _log.warning("Malformed QUIT payload")
                    continue
                nick_channels = self._find_channels_containing_nick(sender)
                reason = f" [{trailing}]" if trailing is not None else ""
                message = f"{sender} has quit {self._host}{reason}"
                for channel_name in nick_channels:
                    channel = self._find_channel_config(channel_name)
                    self._channel_nicks[channel_name].discard(sender)
                    self._callback(channel["to"], "", message)
                self._recovery_delay = 1

        self._log.info("Stopping ...")

    def _find_channel_config(self, channel_name: str) -> dict:
        for channel_config in self._channels:
            if channel_config["channel"] == channel_name.lower():
                return channel_config
        msg = f"Unknown channel name: {channel_name}"
        raise ValueError(msg)

    def _find_channels_containing_nick(self, nick: str) -> list[str]:
        return [k for k, v in self._channel_nicks.items() if nick in v]

    def _recv(self) -> Iterator[str]:
        buffer = ""
        while self.running:
            data = self._socket.recv(1024)
            if len(data) == 0:
                message = "Received zero-length payload from server"
                logging.error(message)
                raise ZeroLengthPayloadError(message)
            buffer += data.decode(errors="replace")
            lines = buffer.split("\r\n")
            lines, buffer = lines[:-1], lines[-1]
            yield from lines
        self._log.info("Stopping ...")

    def _sock_send(self, message: str) -> None:
        self._socket.sendall(message.encode() + b"\r\n")
        self._log.info("sent: %s", message)

    def _lock_send(self, message: str) -> None:
        with self._lock:
            self._sock_send(message)

    def _send_action(self, recipient: str, message: str) -> None:
        self._lock_send(f"PRIVMSG {recipient} :\x01ACTION {message}\x01")

    def _send_message(self, recipient: str, prefix: str, message: str) -> None:
        prefix = prefix.translate(str.maketrans("\0\r\n", "   "))
        message = message.replace("\0", " ")
        size = 400 - len(prefix)
        with self._lock:
            for line in message.splitlines():
                chunks = [line[i : i + size] for i in range(0, len(line), size)]
                for chunk in chunks:
                    self._sock_send(f"PRIVMSG {recipient} :{prefix}{chunk}")

    def forward_message(self, to_labels: list[str], prefix: str, message: str) -> None:
        """Forward message to channels with the specified labels."""
        channels = [c for c in self._channels if c["label"] in to_labels]
        for channel in channels:
            self._send_message(channel["channel"], prefix, message)


# Matrix
# ------


def http_request(
    method: str,
    url: str,
    data: dict[str, Any],
    headers: dict[str, str],
) -> dict:
    """Send an HTTP request and return JSON response as a dictionary."""
    if method == "GET":
        url = url + "?" + urllib.parse.urlencode(data)
        data = {}

    encoded_data = json.dumps(data).encode()

    try:
        _log.info("Sending HTTP request %s ...", url)
        request = urllib.request.Request(  # noqa: S310 (suspicious-url-open-usage)
            url,
            data=encoded_data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request) as response:  # noqa: S310 (suspicious-url-open-usage)
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as err:
        body = err.read().decode()
        logging.exception("HTTP Error response: %r", body)
        raise


def lookup_map(data: dict[Any, Any], keys: list[str]) -> Any:  # noqa: ANN401 (any-type)
    """Recursively look up value in dictionary using given keys."""
    d: Any = data
    for key in keys:
        d = d.get(key)
        if d is None:
            break
    return d


class MatrixClient:
    """Matrix client."""

    MSG_MESSAGE = "msg_message"
    MSG_MEMBER = "msg_member"

    def __init__(
        self,
        client_config: dict[str, Any],
        callback: Callable[[list[str], str, str], None],
    ) -> None:
        """Initialize Matrix client."""
        self._log = logging.getLogger(type(self).__name__)
        self._server = client_config["server"]
        self._username = client_config["username"]
        self._password = client_config["password"]
        self._rooms = client_config["rooms"]
        self._room_id = None
        self._enc_room_id = None
        self._txn = 0
        self._next_batch = None
        self._lock = threading.Lock()
        self._callback = callback
        self._recovery_delay = 1
        self.running = True

    def __str__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}: {self._server}, {self._username}"

    def run(self) -> None:
        """Connect to Matrix server and forward messages."""
        while self.running:
            try:
                self._run()
            except Exception:  # noqa: PERF203, BLE001 (try-except-in-loop, blind-except)
                self._log.exception("Client encountered error")
                self._log.info("Reconnecting in %d s", self._recovery_delay)
                time.sleep(self._recovery_delay)
                self._recovery_delay = min(self._recovery_delay * 2, 60)

    def _run(self) -> None:
        self._connect()
        self._sync()
        self._join()
        self._monitor()

    def _connect(self) -> None:
        url = f"{self._server}/_matrix/client/v3/login"
        headers = {"Content-Type": "application/json"}
        data = {
            "identifier": {
                "type": "m.id.user",
                "user": self._username,
            },
            "password": self._password,
            "type": "m.login.password",
        }
        response = http_request("POST", url, data, headers)
        self._token = response["access_token"]

    def _sync(self) -> None:
        url = f"{self._server}/_matrix/client/v3/sync"
        headers = {"Authorization": "Bearer " + self._token}
        response = http_request("GET", url, {}, headers)
        self._next_batch = response["next_batch"]

    def _join(self) -> None:
        for room in self._rooms:
            enc_room = urllib.parse.quote(room["room"])
            url = f"{self._server}/_matrix/client/v3/join/{enc_room}"
            headers = {"Authorization": "Bearer " + self._token}
            response = http_request("POST", url, {}, headers)
            room["room_id"] = response["room_id"]

    def _monitor(self) -> None:
        while self.running:
            self._new_sync()
        self._log.info("Stopping ...")

    def _new_sync(self) -> None:
        url = f"{self._server}/_matrix/client/v3/sync"
        headers = {"Authorization": "Bearer " + self._token}
        data = {"since": self._next_batch, "timeout": 60000}
        response = http_request("GET", url, data, headers)
        self._next_batch = response["next_batch"]
        for msgtype, room, sender, content in self._read_messages(response):
            self._log.info(
                "read: %s: %s: %s: %s", msgtype, room["room"], sender, content
            )
            infix = room["infix"]
            if msgtype == MatrixClient.MSG_MESSAGE:
                self._callback(room["to"], f"<{sender}{infix}> ", content)
                self._recovery_delay = 1
            elif msgtype == MatrixClient.MSG_MEMBER:
                action = {
                    "join": " has joined ",
                    "leave": " has left ",
                }[content] + f'{room["room"]} ({self._server})'
                message = f"{sender}{action}"
                self._callback(room["to"], "", message)
                self._recovery_delay = 1

    def _read_messages(
        self, response: dict[str, str]
    ) -> Iterator[tuple[str, dict[str, Any], str, str]]:
        for room in self._rooms:
            for msgtype, sender, content in self._read_room_messages(
                room["room_id"],
                response,
            ):
                yield msgtype, room, sender, content

    def _read_room_messages(
        self, room_id: str, response: dict[str, str]
    ) -> Iterator[tuple[str, str, str]]:
        events = lookup_map(response, ["rooms", "join", room_id, "timeline", "events"])
        if events is None:
            return

        for event in events:
            msgtype = event.get("type")
            if msgtype not in ["m.room.message", "m.room.member"]:
                continue

            sender = lookup_map(event, ["sender"])
            if sender == self._username:
                continue
            sender_display_name = self._get_display_name(sender)
            sender = f"{sender_display_name} ({sender})"

            if msgtype == "m.room.message":
                message = lookup_map(event, ["content", "body"])
                yield MatrixClient.MSG_MESSAGE, sender, message
            elif msgtype == "m.room.member":
                membership = lookup_map(event, ["content", "membership"])
                yield MatrixClient.MSG_MEMBER, sender, membership

    def _get_display_name(self, user_id: str) -> str:
        enc_user_id = urllib.parse.quote(user_id)
        url = f"{self._server}/_matrix/client/v3/profile/{enc_user_id}"
        headers = {"Authorization": "Bearer " + self._token}
        response = http_request("GET", url, {}, headers)
        return response["displayname"]

    def _send(self, msgtype: str, room_id: str, message: str) -> None:
        enc_room_id = urllib.parse.quote(room_id)
        with self._lock:
            url = (
                f"{self._server}/_matrix/client/v3/"
                f"rooms/{enc_room_id}/send/m.room.message/{self._txn}"
            )
            headers = {"Authorization": "Bearer " + self._token}
            data = {
                "msgtype": msgtype,
                "body": message,
            }
            self._txn += 1
            http_request("PUT", url, data, headers)
        self._log.info("sent: %s", message)

    def _send_message(self, room_id: str, prefix: str, message: str) -> None:
        self._send("m.text", room_id, f"{prefix}{message}")

    def _send_notice(self, room_id: str, message: str) -> None:
        self._send("m.notice", room_id, message)

    def forward_message(self, to_labels: list[str], prefix: str, message: str) -> None:
        """Forward message to rooms with the specified labels."""
        rooms = [r for r in self._rooms if r["label"] in to_labels]
        for room in rooms:
            if prefix == "":
                self._send_notice(room["room_id"], message)
            else:
                self._send_message(room["room_id"], prefix, message)


Client = IRCClient | MatrixClient


def create_clients(clients_config: list[dict[str, Any]]) -> list[Client]:
    """Create all configured clients."""
    clients: list[Client] = []

    def callback(to_labels: list[str], sender_prefix: str, message: str) -> None:
        for client in clients:
            client.forward_message(to_labels, sender_prefix, message)

    for index, client_config in enumerate(clients_config):
        client_type = client_config["type"]
        if client_type == "irc":
            clients.append(IRCClient(client_config, callback))
        elif client_type == "matrix":
            clients.append(MatrixClient(client_config, callback))
        else:
            _log.warning("Ignored unknown client type: %s", client_type)
        _log.info("Created client %d: %s", index, clients[-1])
    return clients


def run(clients: list[Client]) -> None:
    """Execute all clients."""
    workers = []
    for client in clients:
        worker = threading.Thread(target=client.run)
        workers.append(worker)

    for worker in workers:
        worker.start()

    for worker in workers:
        worker.join()

    _log.info("All workers have quit")


def main() -> None:
    """Run this tool."""
    log_fmt = (
        "%(asctime)s %(levelname)s %(threadName)s "
        "%(filename)s:%(lineno)d %(name)s.%(funcName)s() %(message)s"
    )
    logging.basicConfig(format=log_fmt, level=logging.INFO)
    with pathlib.Path(f"{_NAME}.json").open() as stream:
        config = json.load(stream)
    clients = create_clients(config["clients"])
    run(clients)


class ZeroLengthPayloadError(Exception):
    """Zero length payload has been received from the server."""


if __name__ == "__main__":
    main()
