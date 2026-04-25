#!/usr/bin/env python3
from typing import Callable

from GameServer.Controllers import Lobby
from GameServer.Controllers.Shop import sync_cash, sync_inventory
from GameServer.Controllers.Character import add_item, get_available_inventory_slot, get_items


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
        Lobby.chat_message(_args['client'], 'This command is only available to game masters.', 2)
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
        Lobby.chat_message(_args['client'], f'Player {target_name} was not found.', 2)
        return

    _args['mysql'].execute('UPDATE `users` SET `cash` = (`cash` + %s) WHERE `id` = %s', [amount, record['user_id']])

    target_client = _args['connection_handler'].get_character_client(target_name)
    if target_client is not None:
        target_args = dict(_args)
        target_args['client'] = target_client
        target_args['socket'] = target_client['socket']
        sync_cash(target_args)
        _notify_target(_args, target_client, f'You received {amount} cash!')

    Lobby.chat_message(_args['client'], f'Sent {amount} cash to {target_name}.', 3)


def _apply_gigas(_args, target_name: str, amount: int):
    record = _find_user_by_character(_args, target_name)
    if record is None:
        Lobby.chat_message(_args['client'], f'Player {target_name} was not found.', 2)
        return

    _args['mysql'].execute(
        'UPDATE `characters` SET `currency_gigas` = (`currency_gigas` + %s) WHERE `id` = %s',
        [amount, record['character_id']]
    )

    target_client = _args['connection_handler'].get_character_client(target_name)
    if target_client is not None:
        target_client['character']['currency_gigas'] = target_client['character']['currency_gigas'] + amount
        _notify_target(_args, target_client, f'You received {amount} gigas!')

    Lobby.chat_message(_args['client'], f'Sent {amount} gigas to {target_name}.', 3)


def _apply_item(_args, target_name: str, item_id: int):
    record = _find_user_by_character(_args, target_name)
    if record is None:
        Lobby.chat_message(_args['client'], f'Player {target_name} was not found.', 2)
        return

    _args['mysql'].execute(
        '''SELECT `id`, `item_id`, `duration`, `part_type` FROM `game_items` WHERE `item_id` = %s''',
        [item_id]
    )
    item = _args['mysql'].fetchone()
    if item is None:
        Lobby.chat_message(_args['client'], f'Item ID {item_id} was not found.', 2)
        return

    # Reuse Character.get_items to avoid mismatches with how empty slots are represented in DB (NULL vs 0).
    inventory = get_items(_args, record['character_id'], 'inventory')
    available_slot = get_available_inventory_slot(inventory)
    if available_slot is None:
        Lobby.chat_message(_args['client'], f'{target_name} has a full inventory.', 2)
        return

    target_args = dict(_args)
    target_args['client'] = {'character': {'id': record['character_id']}}
    add_item(target_args, item, available_slot)

    target_client = _args['connection_handler'].get_character_client(target_name)
    if target_client is not None:
        sync_args = dict(_args)
        sync_args['client'] = target_client
        sync_args['socket'] = target_client['socket']
        sync_inventory(sync_args)
        _notify_target(_args, target_client, f'You received item {item_id}.')

    Lobby.chat_message(_args['client'], f'Sent item {item_id} to {target_name}.', 3)


def _find_items_by_name(_args, item_name: str):
    # Some databases store the display name as `name`, others as `item_name`.
    for column in ['name', 'item_name']:
        try:
            _args['mysql'].execute(
                f'''SELECT `item_id`, `{column}` AS `item_name`
                    FROM `game_items`
                    WHERE `{column}` LIKE %s
                    ORDER BY `item_id` ASC
                    LIMIT 10''',
                [f'%{item_name}%']
            )
            return _args['mysql'].fetchall()
        except Exception:
            continue

    return None


def handle_admin_command(_args, command_text: str) -> bool:
    if not command_text.startswith('@'):
        return False

    command_body = command_text[1:].strip()
    parts = command_body.split()
    if not parts:
        Lobby.chat_message(
            _args['client'],
            'Usage: @announce <message> | @cash <user> <amount> | @gigas <user> <amount> | @item <item_id> <user> | '
            '@itemname <name> | @exit | @win | @lose | @timeout | @timeoutdm | @speed <value> | @gauge <value> | '
            '@reset | @kick <player> | @ban <player>',
            2,
        )
        return True

    action = parts[0].lower()
    admin_actions = ANNOUNCEMENT_PREFIXES.union(
        {
            'cash',
            'gigas',
            'item',
            'itemname',
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
            Lobby.chat_message(_args['client'], 'Usage: @announce <message>', 2)
            return True
        _broadcast(_args, f'[Announcement] {announcement}', 3)
        return True

    if action in ['cash', 'gigas']:
        if len(parts) < 3:
            Lobby.chat_message(_args['client'], f'Usage: @{action} <user> <amount>', 2)
            return True
        target_name, amount_raw = parts[1], parts[2]
        if not amount_raw.isdigit():
            Lobby.chat_message(_args['client'], 'Amount must be a positive integer.', 2)
            return True
        amount = int(amount_raw)
        if amount <= 0:
            Lobby.chat_message(_args['client'], 'Amount must be greater than zero.', 2)
            return True

        handlers: dict[str, Callable] = {
            'cash': _apply_cash,
            'gigas': _apply_gigas,
        }
        handlers[action](_args, target_name, amount)
        return True

    if action == 'item':
        if len(parts) < 3:
            Lobby.chat_message(_args['client'], 'Usage: @item <item_id> <user>', 2)
            return True

        item_raw, target_name = parts[1], parts[2]
        if not item_raw.isdigit():
            Lobby.chat_message(_args['client'], 'Item ID must be a positive integer.', 2)
            return True

        item_id = int(item_raw)
        if item_id <= 0:
            Lobby.chat_message(_args['client'], 'Item ID must be greater than zero.', 2)
            return True

        _apply_item(_args, target_name, item_id)
        return True

    if action == 'itemname':
        query_name = command_body[len(parts[0]):].strip()
        if not query_name:
            Lobby.chat_message(_args['client'], 'Usage: @itemname <name>', 2)
            return True

        found_items = _find_items_by_name(_args, query_name)
        if found_items is None:
            Lobby.chat_message(_args['client'], 'This database does not expose an item name column in game_items.', 2)
            return True

        if len(found_items) == 0:
            Lobby.chat_message(_args['client'], f'No item found for "{query_name}".', 2)
            return True

        Lobby.chat_message(_args['client'], f'Item matches for "{query_name}" (max 10):', 2)
        for item in found_items:
            Lobby.chat_message(_args['client'], f'@itemname {item["item_name"]} + ID {item["item_id"]}', 2)
        return True

    if action == 'exit':
        from GameServer.Controllers import Room

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'You are not inside a room.', 2)
            return True
        Room.remove_slot(_args, room['id'], _args['client'])
        return True

    if action in ['win', 'lose', 'timeout', 'timeoutdm']:
        from GameServer.Controllers import Room
        from GameServer.Controllers.Game import game_end
        from GameServer.Controllers.data.game import MODE_DEATHMATCH, MODE_BATTLE, MODE_TEAM_BATTLE

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'You must be inside a room to use this command.', 2)
            return True

        status_map = {
            'win': 1,
            'lose': 0,
            'timeout': 2,
            'timeoutdm': 3,
        }

        if action == 'timeoutdm' and room['game_type'] not in [MODE_DEATHMATCH, MODE_BATTLE, MODE_TEAM_BATTLE]:
            Lobby.chat_message(_args['client'], 'Timeout DM can only be used in battle modes.', 2)
            return True

        game_end(_args=_args, room=room, status=status_map[action])
        return True

    if action in ['speed', 'gauge', 'reset']:
        from GameServer.Controllers import Room
        from GameServer.Controllers.data.game import MODE_BATTLE, MODE_DEATHMATCH, MODE_TEAM_BATTLE
        from GameServer.Controllers.data.bot import STAT_ATT_TRANS_GAUGE, STAT_KEY, STAT_SPEED

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'You must be inside a room to use this command.', 2)
            return True

        if room['game_type'] not in [MODE_DEATHMATCH, MODE_BATTLE, MODE_TEAM_BATTLE]:
            Lobby.chat_message(
                _args['client'],
                'Statistics can only be changed in Death-match, Battle, or Team Battle.',
                2,
            )
            return True

        if room['status'] != 0:
            Lobby.chat_message(_args['client'], 'Statistics can only be changed before the match starts.', 2)
            return True

        if action == 'reset':
            room['stat_override'] = {}
            message = Lobby.chat_message(
                target=None,
                message=f"{_args['client']['character']['name']} reset custom statistics.",
                color=3,
                return_packet=True,
            )
            _args['connection_handler'].room_broadcast(room['id'], message)
            return True

        if len(parts) != 2:
            Lobby.chat_message(_args['client'], f'Usage: @{action} <number>', 2)
            return True

        value = parts[1]
        if not value.isdigit():
            Lobby.chat_message(_args['client'], 'Value must be an integer.', 2)
            return True

        if int(value) not in range(200, 8000):
            Lobby.chat_message(_args['client'], 'Value must be between 200 and 8000.', 2)
            return True

        value_map = {
            'speed': STAT_SPEED,
            'gauge': STAT_ATT_TRANS_GAUGE,
        }

        room['stat_override'][value_map[action][STAT_KEY]] = int(value)
        message = Lobby.chat_message(
            target=None,
            message=f"{_args['client']['character']['name']} changed everyone's {action} to {value}.",
            color=3,
            return_packet=True,
        )
        _args['connection_handler'].room_broadcast(room['id'], message)
        return True

    if action == 'kick':
        from GameServer.Controllers import Room

        if len(parts) < 2:
            Lobby.chat_message(_args['client'], 'Usage: @kick <player>', 2)
            return True

        room = Room.get_room(_args)
        if not room:
            Lobby.chat_message(_args['client'], 'You must be inside a room to use this command.', 2)
            return True

        target_name = command_body[len(parts[0]):].strip()
        if not target_name:
            Lobby.chat_message(_args['client'], 'Usage: @kick <player>', 2)
            return True

        for _, slot in room['slots'].items():
            if slot['client']['character']['name'] == target_name:
                Room.remove_slot(_args, room['id'], slot['client'], 2)
                return True

        Lobby.chat_message(_args['client'], f'Player {target_name} was not found in this room.', 2)
        return True

    if action == 'ban':
        if len(parts) < 2:
            Lobby.chat_message(_args['client'], 'Usage: @ban <player>', 2)
            return True

        target_name = command_body[len(parts[0]):].strip()
        if not target_name:
            Lobby.chat_message(_args['client'], 'Usage: @ban <player>', 2)
            return True

        record = _find_user_by_character(_args, target_name)
        if record is None:
            Lobby.chat_message(_args['client'], f'Player {target_name} was not found.', 2)
            return True

        _args['mysql'].execute('UPDATE `users` SET `suspended` = 1 WHERE `id` = %s', [record['user_id']])

        target_client = _args['connection_handler'].get_character_client(target_name)
        if target_client is not None:
            Lobby.chat_message(target_client, 'You were banned by a game master.', 2)
            _args['connection_handler'].update_player_status(target_client, 2)

        Lobby.chat_message(_args['client'], f'{target_name} was banned.', 3)
        return True

    Lobby.chat_message(_args['client'], 'Unknown administrative command.', 2)
    return True
