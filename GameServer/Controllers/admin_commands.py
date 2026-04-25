#!/usr/bin/env python3
from typing import Callable

from GameServer.Controllers import Lobby
from GameServer.Controllers.Shop import sync_cash


ANNOUNCEMENT_PREFIXES = {'announce', 'anuncio', 'anúncio'}


def _broadcast(_args, message: str, color: int = 3):
    packet = Lobby.chat_message(target=None, message=message, color=color, return_packet=True)
    for client in _args['connection_handler'].get_clients():
        try:
            client['socket'].sendall(packet)
        except Exception:
            pass


def _require_admin(_args) -> bool:
    if _args['client'].get('gm', 0) != 1:
        Lobby.chat_message(_args['client'], 'Esse comando é apenas para administradores.', 2)
        return False
    return True


def _find_user_by_character(_args, character_name: str):
    _args['mysql'].execute('''
        SELECT users.id as user_id, characters.id as character_id
        FROM characters
        INNER JOIN users ON characters.user_id = users.id
        WHERE characters.name = %s
    ''', [character_name])
    return _args['mysql'].fetchone()


def _notify_target(_args, target_client, message: str):
    if target_client is None:
        return
    Lobby.chat_message(target_client, message, 3)


def _apply_cash(_args, target_name: str, amount: int):
    record = _find_user_by_character(_args, target_name)
    if record is None:
        Lobby.chat_message(_args['client'], f'Jogador {target_name} não encontrado.', 2)
        return

    _args['mysql'].execute('UPDATE `users` SET `cash` = (`cash` + %s) WHERE `id` = %s', [amount, record['user_id']])

    target_client = _args['connection_handler'].get_character_client(target_name)
    if target_client is not None:
        target_args = dict(_args)
        target_args['client'] = target_client
        target_args['socket'] = target_client['socket']
        sync_cash(target_args)
        _notify_target(_args, target_client, f'Você recebeu {amount} cash!')

    Lobby.chat_message(_args['client'], f'{amount} cash enviado para {target_name}.', 3)


def _apply_gigas(_args, target_name: str, amount: int):
    record = _find_user_by_character(_args, target_name)
    if record is None:
        Lobby.chat_message(_args['client'], f'Jogador {target_name} não encontrado.', 2)
        return

    _args['mysql'].execute(
        'UPDATE `characters` SET `currency_gigas` = (`currency_gigas` + %s) WHERE `id` = %s',
        [amount, record['character_id']]
    )

    target_client = _args['connection_handler'].get_character_client(target_name)
    if target_client is not None:
        target_client['character']['currency_gigas'] = target_client['character']['currency_gigas'] + amount
        _notify_target(_args, target_client, f'Você recebeu {amount} gigas!')

    Lobby.chat_message(_args['client'], f'{amount} gigas enviados para {target_name}.', 3)


def handle_admin_command(_args, command_text: str) -> bool:
    if not command_text.startswith('@'):
        return False

    command_body = command_text[1:].strip()
    parts = command_body.split()
    if not parts:
        Lobby.chat_message(
            _args['client'],
            'Uso: @announce <mensagem> | @cash <user> <quantia> | @gigas <user> <quantia> | @exit | @win | @lose | @timeout | '
            '@timeoutdm | @speed <valor> | @gauge <valor> | @reset | @kick <jogador> | @ban <jogador>',
            2,
        )
        return True

    action = parts[0].lower()
    admin_actions = ANNOUNCEMENT_PREFIXES.union(
        {
            'cash',
            'gigas',
            'exit',
            'win',
            'lose',
            'timeout',
            'timeoutdm',
            'speed',
            'gauge',
            'reset',
            'kick',
            'ban',
        }
    )

    if action not in admin_actions:
        return False

    if not _require_admin(_args):
        return True

    if action in ANNOUNCEMENT_PREFIXES:
        announcement = command_body[len(parts[0]):].strip()
        if not announcement:
            Lobby.chat_message(_args['client'], 'Uso: @announce <mensagem>', 2)
            return True
        _broadcast(_args, f'[Anúncio] {announcement}', 3)
        return True

    if action in ['cash', 'gigas']:
        if len(parts) < 3:
            Lobby.chat_message(_args['client'], f'Uso: @{action} <usuario> <quantia>', 2)
            return True
        target_name, amount_raw = parts[1], parts[2]
        if not amount_raw.isdigit():
            Lobby.chat_message(_args['client'], 'A quantia deve ser um número inteiro positivo.', 2)
            return True
        amount = int(amount_raw)
        if amount <= 0:
            Lobby.chat_message(_args['client'], 'A quantia deve ser maior que zero.', 2)
            return True

        handlers: dict[str, Callable] = {
            'cash': _apply_cash,
            'gigas': _apply_gigas,
        }
        handlers[action](_args, target_name, amount)
        return True

    if action == 'exit':
        from GameServer.Controllers import Room

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'Você não está em uma sala.', 2)
            return True
        Room.remove_slot(_args, room['id'], _args['client'])
        return True

    if action in ['win', 'lose', 'timeout', 'timeoutdm']:
        from GameServer.Controllers import Room
        from GameServer.Controllers.Game import game_end
        from GameServer.Controllers.data.game import MODE_DEATHMATCH, MODE_BATTLE, MODE_TEAM_BATTLE

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'Você precisa estar em uma sala para usar este comando.', 2)
            return True

        status_map = {
            'win': 1,
            'lose': 0,
            'timeout': 2,
            'timeoutdm': 3,
        }

        if action == 'timeoutdm' and room['game_type'] not in [MODE_DEATHMATCH, MODE_BATTLE, MODE_TEAM_BATTLE]:
            Lobby.chat_message(_args['client'], 'Timeout DM só pode ser usado em modos de batalha.', 2)
            return True

        game_end(_args=_args, room=room, status=status_map[action])
        return True

    if action in ['speed', 'gauge', 'reset']:
        from GameServer.Controllers import Room
        from GameServer.Controllers.data.game import MODE_BATTLE, MODE_DEATHMATCH, MODE_TEAM_BATTLE
        from GameServer.Controllers.data.bot import STAT_ATT_TRANS_GAUGE, STAT_KEY, STAT_SPEED

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'Você precisa estar em uma sala para usar este comando.', 2)
            return True

        if room['game_type'] not in [MODE_DEATHMATCH, MODE_BATTLE, MODE_TEAM_BATTLE]:
            Lobby.chat_message(
                _args['client'],
                'Estatísticas só podem ser alteradas em Death-match, Battle ou Team Battle.',
                2,
            )
            return True

        if room['status'] != 0:
            Lobby.chat_message(_args['client'], 'As estatísticas só podem ser alteradas antes do início da partida.', 2)
            return True

        if action == 'reset':
            room['stat_override'] = {}
            message = Lobby.chat_message(
                target=None,
                message=f"{_args['client']['character']['name']} resetou as estatísticas personalizadas.",
                color=3,
                return_packet=True,
            )
            _args['connection_handler'].room_broadcast(room['id'], message)
            return True

        if len(parts) != 2:
            Lobby.chat_message(_args['client'], f'Uso: @{action} <número>', 2)
            return True

        value = parts[1]
        if not value.isdigit():
            Lobby.chat_message(_args['client'], 'O valor deve ser um número inteiro.', 2)
            return True

        if int(value) not in range(200, 8000):
            Lobby.chat_message(_args['client'], 'O valor deve estar entre 200 e 8000.', 2)
            return True

        value_map = {
            'speed': STAT_SPEED,
            'gauge': STAT_ATT_TRANS_GAUGE,
        }

        room['stat_override'][value_map[action][STAT_KEY]] = int(value)
        message = Lobby.chat_message(
            target=None,
            message=f"{_args['client']['character']['name']} alterou {action} de todos para {value}.",
            color=3,
            return_packet=True,
        )
        _args['connection_handler'].room_broadcast(room['id'], message)
        return True

    if action == 'kick':
        from GameServer.Controllers import Room

        if len(parts) < 2:
            Lobby.chat_message(_args['client'], 'Uso: @kick <jogador>', 2)
            return True

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'Você precisa estar em uma sala para usar este comando.', 2)
            return True

        target_name = command_body[len(parts[0]):].strip()
        if not target_name:
            Lobby.chat_message(_args['client'], 'Uso: @kick <jogador>', 2)
            return True

        for _, slot in room['slots'].items():
            if slot['client']['character']['name'] == target_name:
                Room.remove_slot(_args, room['id'], slot['client'], 2)
                return True

        Lobby.chat_message(_args['client'], f'Jogador {target_name} não encontrado na sala.', 2)
        return True

    if action == 'ban':
        if len(parts) < 2:
            Lobby.chat_message(_args['client'], 'Uso: @ban <jogador>', 2)
            return True

        target_name = command_body[len(parts[0]):].strip()
        if not target_name:
            Lobby.chat_message(_args['client'], 'Uso: @ban <jogador>', 2)
            return True

        record = _find_user_by_character(_args, target_name)
        if record is None:
            Lobby.chat_message(_args['client'], f'Jogador {target_name} não encontrado.', 2)
            return True

        _args['mysql'].execute('UPDATE `users` SET `suspended` = 1 WHERE `id` = %s', [record['user_id']])

        target_client = _args['connection_handler'].get_character_client(target_name)
        if target_client is not None:
            Lobby.chat_message(target_client, 'Você foi banido pelo administrador.', 2)
            _args['connection_handler'].update_player_status(target_client, 2)

        Lobby.chat_message(_args['client'], f'{target_name} foi banido.', 3)
        return True

    Lobby.chat_message(_args['client'], 'Comando administrativo desconhecido.', 2)
    return True

