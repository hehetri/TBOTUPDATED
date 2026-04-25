import datetime

from GameServer.Controllers import Room, Lobby
from GameServer.Controllers.data.game import MODE_PLANET
from Packet.Write import Write as PacketWrite

"""
This method will register this event, if the conditions in the method are met
"""


def register(room):
    for event in ['start_game', 'reset']:
        Room.register_callback(room, event, 'event_weekends')


def reset(_args, room):
    room['experience_modifier'] = 1.0


'''
This method will execute once the game is started
'''


def start_game(_args, room):

    # Determine whether we are awarding +50% experience
    awarding = (datetime.datetime.today().weekday() >= 5 or (
                datetime.datetime.now().month == 12 and (datetime.datetime.now().day == 11))) and room[
                   'game_type'] == MODE_PLANET

    # If we are awarding more experience, mutate the experience modifier
    if awarding:
        room['experience_modifier'] = 1.5

        message = Lobby.chat_message(target=None,
                                     message='Evento semanal ativo! Ganhe 50% de EXP extra em planeta.',
                                     color=3,
                                     return_packet=True)
        _args['connection_handler'].room_broadcast(room['id'], message)

    # Send experience banner state to the room
    banner = PacketWrite()
    banner.add_header([0x28, 0x27])
    banner.append_bytes([0x01 if awarding else 0x00, 0x00])
    _args['connection_handler'].room_broadcast(room['id'], banner.packet)