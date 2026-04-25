from Packet.Write import Write as PacketWrite
from GameServer.Controllers.Room import get_slot
import MySQL.Interface as MySQL
import datetime

class UnreliableRelayRouter:

    def __init__(self, client, packet):
        self.client = client
        self.server = self.client['server']
        self.packet = packet

        # Read relay id and get relay client from it as well
        self.relay_id = int.from_bytes(self.packet.data[:2], byteorder='little')
        self.relay_client = self.server.relay.clients[self.relay_id]

        # If the client's address information does not match with our own, attempt to validate through the last
        # known IP stored on the user and update it to the UDP source if necessary.
        relay_ip = self.relay_client['socket'].getpeername()[0]
        client_ip = self.client['address'][0]

        if relay_ip != client_ip:
            # Attempt to verify the account's last_ip matches the incoming UDP packet. If it does, update the
            # stored IP to the client's UDP source to keep future checks in sync.
            user_account = self.relay_client.get('account')
            connection = MySQL.get_connection()
            cursor = connection.cursor(dictionary=True)

            cursor.execute('''SELECT `username`, `last_ip` FROM `users` WHERE `username` = %s''', [user_account])
            user = cursor.fetchone()

            if user is not None:
                if user['last_ip'] != client_ip:
                    cursor.execute('''UPDATE `users` SET `last_ip` = %s WHERE `username` = %s''', [
                        client_ip,
                        user_account
                    ])
                    connection.commit()
                    user['last_ip'] = client_ip
            connection.close()

            if user is None or user['last_ip'] != client_ip:
                raise 'client sent invalid relay id'

    def route(self):

        match self.packet.header:

            case b'\x34\xa0':
                self.command_ping()

            case b'\x35\xa0':
                self.request_virtual_ip()

            case b'\x38\xa0':
                self.command_relay()

            case _:
                print('unknown packet header: {0}'.format(self.packet.id))

    def command_ping(self):

        # Get last ping timestamp
        self.client['last_ping'] = datetime.datetime.now()

    def request_virtual_ip(self):

        # Build response packet. We don't need to do anything here.
        acknowledgment = PacketWrite(header=b'\x1D\xA4')
        acknowledgment.append_bytes(bytes=[0x01, 0xCC])
        self.server.socket.sendto(acknowledgment.packet, (self.client['address']))

    def command_relay(self):

         # Read action data from the packet we have received
        action = self.packet.data[8:]

        # If our client isn't a room, we'll drop the packet
        if 'room' not in self.relay_client['game_client']:
            return

        # Retrieve room and slot number
        room = self.relay_client['game_server'].rooms[str(self.relay_client['game_client']['room'])]
        slot = room['slots'][str(get_slot({'client': self.relay_client['game_client']}, room))]

        # Loop through the relay IDs and bein sending the action packet to each of them
        for remote_relay_id in slot['relay_ids']:

            # Get our remote client which will be receiving the action packet
            remote_client = self.server.relay.clients[remote_relay_id]

            # We'll require p2p_host to be present in the remote's game client object. If this isn't present
            # we can't send them their packet. We'll just wait for it to become present in the next packet.
            if 'p2p_host' not in remote_client['game_client']:
                continue

            # Retrieve peer information from the game client object. This information will be used to send the action packet.
            peer_information = remote_client['game_client']['p2p_host']

            # Send UDP action packet to the peer we have retrieved. We'll send it through the room host server
            self.server.room.socket.sendto(action, (peer_information['ip'], peer_information['port']))