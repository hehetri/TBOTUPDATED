#!/usr/bin/env python3
__author__ = "Icseon"
__copyright__ = "Copyright (C) 2020 Icseon"
__version__ = "1.0"

from ChannelServer.Packets import Channels

"""
This method will execute a command based on the received command ID
"""


def unknown(**_args):
    print('[ChannelServer] Unknown command ID', _args['packet'].id)


PACKET_HANDLERS = {
    'fa2a': Channels.get_channels
}


def execute(server, address, packet, game_server):
    PACKET_HANDLERS.get(packet.id, unknown)(**locals())
