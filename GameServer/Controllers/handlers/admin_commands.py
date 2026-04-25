#!/usr/bin/env python3
from typing import Callable

from GameServer.Controllers import Lobby
from GameServer.Controllers.Shop import sync_cash


ANNOUNCEMENT_PREFIXES = {'announce', 'anuncio', 'anúncio', '!'}


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

    if not _require_admin(_args):
        return True

    command_body = command_text[1:].strip()
    if not command_body:
        Lobby.chat_message(_args['client'], 'Uso: @announce <mensagem> | @cash <user> <quantia> | @gigas <user> <quantia>', 2)
        return True

    parts = command_body.split()
    action = parts[0].lower()

    if action in ANNOUNCEMENT_PREFIXES:
        announcement = command_body[len(parts[0]):].strip()
        if not announcement:
            Lobby.chat_message(_args['client'], 'Uso: @announce <mensagem>', 2)
            return True
        _broadcast(_args, f'[News] {announcement}', 3)
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

    Lobby.chat_message(_args['client'], 'Unknow Command', 2)
    return True

