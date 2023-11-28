#!/usr/bin/env python3

"""NIMB - NIMB IRC Matrix Bridge."""


import json
import logging
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request

_NAME = 'nimb'
_log = logging.getLogger(_NAME)


# Internet Relay Chat
# -------------------

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


def _irc_sanitize(s):
    return s.translate(str.maketrans('', '', '\0\r\n'))


class IRCClient:
    def __init__(self, client_config, callback):
        self._log = logging.getLogger(type(self).__name__)
        self._tls = client_config['tls']
        self._host = client_config['host']
        self._port = client_config['port']
        self._nick = client_config['nick']
        self._password = client_config['password']
        self._channels = client_config['channels']
        self._socket = None
        self._lock = threading.Lock()
        self._callback = callback
        self._recovery_delay = 1
        self.running = True

    def __str__(self):
        return (f'{self.__class__.__name__}: '
                f'{self._host}, {self._port}, {self._nick}')

    def run(self):
        while self.running:
            try:
                self._run()
            except:
                self._log.exception('Client encountered error')
                self._log.info(f'Reconnecting in {self._recovery_delay} s ...')
                time.sleep(self._recovery_delay)
                self._recovery_delay = min(self._recovery_delay * 2, 3600)

    def _run(self):
        self._connect()
        self._auth()
        self._join()
        self._monitor()

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
        for channel in self._channels:
            self._send('JOIN {}'.format(channel['channel']))

    def _monitor(self):
        for line in self._recv():
            self._log.info('recv: %s', line)
            sender, command, middle, trailing = _parse_line(line)
            if command == 'PING':
                self._send('PONG :{}'.format(trailing))
            elif command == 'PRIVMSG':
                channel = self._find_channel_by_middle(middle)
                infix = channel['infix']
                self._callback(channel['to'], f'{sender}{infix}', trailing)
                self._recovery_delay = 1
        self._log.info('Stopping ...')

    def _find_channel_by_middle(self, middle):
        for channel in self._channels:
            if channel['channel'] == middle.lower():
                return channel
        return None

    def _recv(self):
        buffer = ''
        while self.running:
            data = self._socket.recv(1024)
            if len(data) == 0:
                message = 'Received zero-length payload from server'
                logging.error(message)
                raise Exception(message)
            buffer += data.decode(errors='replace')
            lines = buffer.split('\r\n')
            lines, buffer = lines[:-1], lines[-1]
            for line in lines:
                yield line
        self._log.info('Stopping ...')

    def _sock_send(self, message):
        self._socket.sendall(message.encode() + b'\r\n')
        self._log.info('sent: %s', message)

    def _send(self, message):
        with self._lock:
            self._sock_send(message)

    def _send_message(self, recipient, prefix, message):
        prefix = _irc_sanitize(prefix)
        message = _irc_sanitize(message)
        size = 400 - len(prefix)
        with self._lock:
            for line in message.splitlines():
                chunks = [line[i:i + size] for i in range(0, len(line), size)]
                for chunk in chunks:
                    self._sock_send(f'PRIVMSG {recipient} :{prefix}{chunk}')

    def forward_message(self, to_labels, prefix, message):
        channels = [c for c in self._channels if c['label'] in to_labels]
        for channel in channels:
            self._send_message(channel['channel'], prefix, message)


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


def lookup_map(data, keys):
    for key in keys:
        data = data.get(key)
        if data is None:
            break
    return data


class MatrixClient:
    def __init__(self, client_config, callback):
        self._log = logging.getLogger(type(self).__name__)
        self._server = client_config['server']
        self._username = client_config['username']
        self._password = client_config['password']
        self._rooms = client_config['rooms']
        self._room_id = None
        self._enc_room_id = None
        self._token = None
        self._txn = 0
        self._next_batch = None
        self._lock = threading.Lock()
        self._callback = callback
        self._recovery_delay = 1
        self.running = True

    def __str__(self):
        return f'{self.__class__.__name__}: {self._server}, {self._username}'

    def run(self):
        while self.running:
            try:
                self._run()
            except:
                self._log.exception('Client encountered error')
                self._log.info(f'Reconnecting in {self._recovery_delay} s ...')
                time.sleep(self._recovery_delay)
                self._recovery_delay = min(self._recovery_delay * 2, 60)

    def _run(self):
        self._connect()
        self._sync()
        self._join()
        self._monitor()

    def _connect(self):
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

    def _sync(self):
        url = '{}/_matrix/client/v3/sync'.format(self._server)
        headers = {'Authorization': 'Bearer ' + self._token}
        response = http_request('GET', url, {}, headers)
        self._next_batch = response['next_batch']

    def _join(self):
        for room in self._rooms:
            enc_room = urllib.parse.quote(room['room'])
            url = ('{}/_matrix/client/v3/join/{}'
                   .format(self._server, enc_room))
            headers = {'Authorization': 'Bearer ' + self._token}
            response = http_request('POST', url, {}, headers)
            room['room_id'] = response['room_id']

    def _monitor(self):
        while self.running:
            self._new_sync()
        self._log.info('Stopping ...')

    def _new_sync(self):
        url = '{}/_matrix/client/v3/sync'.format(self._server)
        headers = {'Authorization': 'Bearer ' + self._token}
        data = {'since': self._next_batch, 'timeout': 60000}
        response = http_request('GET', url, data, headers)
        self._next_batch = response['next_batch']
        for room, sender, message in self._read_messages(response):
            infix = room['infix']
            self._callback(room['to'], f'{sender}{infix}', message)
            self._recovery_delay = 1

    def _read_messages(self, response):
        for room in self._rooms:
            for sender, message in self._read_room_messages(room['room_id'],
                                                            response):
                yield room, sender, message

    def _read_room_messages(self, room_id, response):
        events = lookup_map(response, ['rooms', 'join', room_id,
                                       'timeline', 'events'])
        if events is None:
            return

        for event in events:
            msgtype = lookup_map(event, ['content', 'msgtype'])
            if msgtype != 'm.text':
                continue
            sender = lookup_map(event, ['sender'])
            if sender == self._username:
                continue
            sender_display_name = self._get_display_name(sender)
            sender = f'{sender_display_name} ({sender})'
            message = lookup_map(event, ['content', 'body'])
            yield sender, message

    def _get_display_name(self, user_id):
        enc_user_id = urllib.parse.quote(user_id)
        url = f'{self._server}/_matrix/client/v3/profile/{enc_user_id}'
        headers = {'Authorization': 'Bearer ' + self._token}
        response = http_request('GET', url, {}, headers)
        return response['displayname']

    def _send(self, room_id, message):
        enc_room_id = urllib.parse.quote(room_id)
        with self._lock:
            url = ('{}/_matrix/client/v3/rooms/{}/send/m.room.message/{}'
                   .format(self._server, enc_room_id, self._txn))
            headers = {'Authorization': 'Bearer ' + self._token}
            data = {
                'msgtype': 'm.text',
                'body': message,
            }
            self._txn += 1
            http_request('PUT', url, data, headers)

    def send_message(self, room_id, prefix, message):
        self._send(room_id, '{}{}'.format(prefix, message))

    def forward_message(self, to_labels, prefix, message):
        rooms = [r for r in self._rooms if r['label'] in to_labels]
        for room in rooms:
            self.send_message(room['room_id'], prefix, message)


def create_clients(clients_config):
    clients = []

    def callback(to_labels, sender_prefix, message):
        for client in clients:
            client.forward_message(to_labels, sender_prefix, message)

    for index, client_config in enumerate(clients_config):
        client_type = client_config['type']
        if client_type == 'irc':
            clients.append(IRCClient(client_config, callback))
        elif client_type == 'matrix':
            clients.append(MatrixClient(client_config, callback))
        else:
            _log.warning('Ignored unknown client type: %s', client_type)
        _log.info('Created client %d: %s', index, clients[-1])
    return clients


def run(clients):
    workers = []
    for client in clients:
        worker = threading.Thread(target=client.run)
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
    clients = create_clients(config['clients'])
    run(clients)


if __name__ == '__main__':
    main()
