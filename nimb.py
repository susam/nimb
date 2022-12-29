#!/usr/bin/env python3

"""NIMB - NIMB IRC Matrix Bridge."""


import json
import logging
import socket
import ssl
import threading
import urllib.parse
import urllib.request

_NAME = 'nimb'
_log = logging.getLogger(_NAME)


# IRC
# ---

def _parse_line(line):
    # RFC 1459 - 2.3.1
    # <message>  ::= [':' <prefix> <SPACE> ] <command> <params> <crlf>
    # <prefix>   ::= <servername> | <nick> [ '!' <user> ] [ '@' <host> ]
    # <command>  ::= <letter> { <letter> } | <number> <number> <number>
    # <SPACE>    ::= ' ' { ' ' }
    # <params>   ::= <SPACE> [ ':' <trailing> | <middle> <params> ]
    #
    # Example: :alice!Alice@user/alice PRIVMSG #hello :hello
    # Example: PING :foo.example.com
    if line[0] == ':':
        prefix, rest = line[1:].split(maxsplit=1)
    else:
        prefix, rest = None, line

    sender, command, middle, trailing = None, None, None, None

    if prefix:
        sender = prefix.split('!')[0]

    rest = rest.split(None, 1)
    command = rest[0].upper()

    if len(rest) == 2:
        params = rest[1]
        params = params.split(':', 1)
        middle = params[0].strip()
        if len(params) == 2:
            trailing = params[1].strip()

    return sender, command, middle, trailing


class IRCChannel:
    def __init__(self, channel_config, callback):
        self._log = logging.getLogger(self.__class__.__name__)
        self.idx = channel_config['id']
        self._to = channel_config['to']
        self._host = channel_config['host']
        self._port = channel_config['port']
        self._tls = channel_config['tls']
        self._nick = channel_config['nick']
        self._password = channel_config['pass']
        self._channel = channel_config['chan']
        self._infix = channel_config['infix']
        self._socket = None
        self._lock = threading.Lock()
        self._callback = callback
        self.running = True

    def connect(self):
        self._connect()
        self._auth()
        self._join()

    def _connect(self):
        self._socket = socket.create_connection((self._host, self._port))
        if self._tls:
            tls_context = ssl.create_default_context()
            self._socket = tls_context.wrap_socket(self._socket,
                                                   server_hostname=self._host)

    def _auth(self):
        self._send('PASS {}'.format(self._password))
        self._send('NICK {}'.format(self._nick))
        self._send('USER {} {} {} :{}'
                   .format(self._nick, self._nick, self._host, self._nick))

    def _join(self):
        self._send('JOIN {}'.format(self._channel))

    def loop(self):
        for line in self._recv():
            self._log.info('received: %s', line)
            sender, command, middle, trailing = _parse_line(line)
            from_channel = (middle is not None and
                            middle.lower() == self._channel.lower())
            middle = middle.lower()
            if command == 'PING':
                self._send_with_lock('PONG :{}'.format(trailing))
            elif command == 'PRIVMSG' and from_channel:
                sender_prefix = '{}{}'.format(sender, self._infix)
                self._callback(self._to, sender_prefix, trailing)
        self._log.info('Stopping ...')

    def _recv(self):
        buffer = ''
        while self.running:
            data = self._socket.recv(1024)
            if len(data) == 0:
                msg = 'Received zero-length payload from server'
                logging.error(msg)
                raise Exception(msg)
            buffer += data.decode(errors='replace')
            lines = buffer.split('\r\n')
            lines, buffer = lines[:-1], lines[-1]
            for line in lines:
                yield line
        self._log.info('Stopping ...')

    def _send(self, msg):
        self._socket.sendall(msg.encode() + b'\r\n')

    def _send_with_lock(self, msg):
        with self._lock:
            self._send(msg)

    def send_message(self, prefix, msg):
        size = 400 - len(prefix)
        chunks = [msg[i:i + size] for i in range(0, len(msg), size)]
        with self._lock:
            for chunk in chunks:
                self._send('PRIVMSG {} :{}{}\r\n'
                           .format(self._channel, prefix, chunk))


# Matrix
# ------

def http_request(method, url, data, headers):
    if method == 'GET':
        url = url + '?' + urllib.parse.urlencode(data)
        data = {}
    data = json.dumps(data).encode()
    try:
        _log.info('Sending HTTP request %s ...', url)
        request = urllib.request.Request(url, data=data, headers=headers,
                                         method=method)
        with urllib.request.urlopen(request) as response:
            body = json.loads(response.read().decode())
            return body
    except urllib.error.HTTPError as err:
        body = err.read().decode()
        logging.exception('HTTP Error response: %r', body)
        raise


def dict_value(data, keys):
    for key in keys:
        data = data.get(key)
        if data is None:
            break
    return data


class MatrixChannel:
    def __init__(self, channel_config, callback):
        self._log = logging.getLogger(self.__class__.__name__)
        self.idx = channel_config['id']
        self._to = channel_config['to']
        self._username = channel_config['username']
        self._password = channel_config['password']
        self._server = channel_config['server']
        self._room = channel_config['room']
        self._infix = channel_config['infix']
        self._enc_room = urllib.parse.quote(self._room)
        self._room_id = None
        self._enc_room_id = None
        self._token = None
        self._txn = 0
        self._next_batch = None
        self._lock = threading.Lock()
        self._callback = callback
        self.running = True

    def connect(self):
        url = '{}/_matrix/client/v3/login'.format(self._server)
        headers = {'Content-Type': 'application/json'}
        data = {
            'identifier': {
                'type': 'm.id.user',
                'user': self._username,
            },
            'password': self._password,
            'type': 'm.login.password',
        }
        response = http_request('POST', url, data, headers)
        self._token = response['access_token']
        self._sync()
        self._join()

    def _sync(self):
        url = '{}/_matrix/client/v3/sync'.format(self._server)
        headers = {'Authorization': 'Bearer ' + self._token}
        response = http_request('GET', url, {}, headers)
        self._next_batch = response['next_batch']

    def _join(self):
        url = ('{}/_matrix/client/v3/join/{}'
               .format(self._server, self._enc_room))
        headers = {'Authorization': 'Bearer ' + self._token}
        response = http_request('POST', url, {}, headers)
        self._room_id = response['room_id']
        self._enc_room_id = urllib.parse.quote(self._room_id)

    def loop(self):
        while self.running:
            url = '{}/_matrix/client/v3/sync'.format(self._server)
            headers = {'Authorization': 'Bearer ' + self._token}
            data = {'since': self._next_batch, 'timeout': 60000}
            response = http_request('GET', url, data, headers)
            self._next_batch = response['next_batch']
            for sender, message in self._read_message(response):
                sender_prefix = '{}{}'.format(sender, self._infix)
                self._callback(self._to, sender_prefix, message)
        self._log.info('Stopping ...')

    def _read_message(self, response):
        events = dict_value(response, ['rooms', 'join', self._room_id,
                                       'timeline', 'events'])
        if events is None:
            return

        for event in events:
            msgtype = dict_value(event, ['content', 'msgtype'])
            if msgtype != 'm.text':
                continue
            sender = dict_value(event, ['sender'])
            if sender == self._username:
                continue
            message = dict_value(event, ['content', 'body'])
            yield sender, message

    def _send(self, message):
        with self._lock:
            url = ('{}/_matrix/client/v3/rooms/{}/send/m.room.message/{}'
                   .format(self._server, self._enc_room_id, self._txn))
            headers = {'Authorization': 'Bearer ' + self._token}
            data = {
                'msgtype': 'm.text',
                'body': message,
            }
            self._txn += 1
            http_request('PUT', url, data, headers)

    def send_message(self, prefix, message):
        self._send('{}{}'.format(prefix, message))


def connect_all(channels_config):
    channels = []

    def callback(to_channels, sender, message):
        selected_channels = [c for c in channels if c.idx in to_channels]
        for channel in selected_channels:
            channel.send_message(sender, message)

    for sno, channel_config in enumerate(channels_config):
        channel_type = channel_config['type']
        if channel_type == 'irc':
            channel = IRCChannel(channel_config, callback)
        elif channel_type == 'matrix':
            channel = MatrixChannel(channel_config, callback)
        else:
            continue
        _log.info('Connecting to channel %d of type %s ...', sno, channel_type)
        channel.connect()
        channels.append(channel)

    return channels


def loop_all(channels):
    workers = []
    for channel in channels:
        worker = threading.Thread(target=channel.loop)
        workers.append(worker)

    for worker in workers:
        worker.start()

    for worker in workers:
        worker.join()

    _log.info('All workers have quit')


def main():
    log_fmt = ('%(asctime)s %(levelname)s %(threadName)s '
               '%(filename)s:%(lineno)d %(name)s.%(funcName)s() %(message)s')
    logging.basicConfig(format=log_fmt, level=logging.INFO)
    with open('{}.json'.format(_NAME), encoding='utf-8') as stream:
        config = json.load(stream)
    channels = connect_all(config['channels'])
    loop_all(channels)


if __name__ == '__main__':
    main()
