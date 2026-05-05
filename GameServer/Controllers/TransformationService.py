#!/usr/bin/env python3
import time

from GameServer.Controllers import Lobby, Room
from GameServer.Controllers.Character import get_items
from Packet.Write import Write as PacketWrite

# Loaded from DB/client metadata; do not hardcode fake IDs.
TRANSFORMATION_SETS = {}
TRANSFORMATION_SETS_LOADED = False

TRANSFORM_GAUGE_FULL = 100


def get_equipped_transformation_parts(_args):
    wearing = get_items(_args, _args['client']['character']['id'], 'wearing')['items']

    head = next((item['id'] for item in wearing.values() if item['type'] == 'head' and item['id'] != 0), 0)
    body = next((item['id'] for item in wearing.values() if item['type'] == 'body' and item['id'] != 0), 0)
    # Project uses 'arms' in Character types.
    arm = next((item['id'] for item in wearing.values() if item['type'] == 'arms' and item['id'] != 0), 0)
    return head, body, arm


def load_transformation_sets(_args):
    global TRANSFORMATION_SETS_LOADED
    if TRANSFORMATION_SETS_LOADED:
        return

    mysql = _args.get('mysql')
    if mysql is None:
        return

    # Try known schema variants. Uses only IDs found in DB.
    candidates = [
        ("SELECT `transformation_id`, `head_item_id`, `body_item_id`, `arm_item_id` FROM `transformation_sets`",
         ('transformation_id', 'head_item_id', 'body_item_id', 'arm_item_id')),
        ("SELECT `id`, `head_id`, `body_id`, `arms_id` FROM `game_transformations`",
         ('id', 'head_id', 'body_id', 'arms_id')),
        ("SELECT `id`, `head`, `body`, `arm` FROM `character_id_map`",
         ('id', 'head', 'body', 'arm')),
    ]

    for query, cols in candidates:
        try:
            mysql.execute(query)
            rows = mysql.fetchall()
            loaded = 0
            for row in rows:
                tid, h, b, a = row[cols[0]], row[cols[1]], row[cols[2]], row[cols[3]]
                if all([tid, h, b, a]):
                    TRANSFORMATION_SETS[int(tid)] = {"head": int(h), "body": int(b), "arm": int(a)}
                    loaded += 1
            if loaded > 0:
                print(f"[Transform] loaded {loaded} transformation set(s) from DB.")
                TRANSFORMATION_SETS_LOADED = True
                return
        except Exception:
            continue

    TRANSFORMATION_SETS_LOADED = True
    print('[Transform] no complete transformation mapping table found. Sets remain empty.')


def resolve_transformation_id(head_id, body_id, arm_id):
    for transformation_id, parts in TRANSFORMATION_SETS.items():
        if parts['head'] == head_id and parts['body'] == body_id and parts['arm'] == arm_id:
            return transformation_id
    return 0


def can_transform(_args, room):
    slot = Room.get_slot(_args, room)
    slot_data = room['slots'][str(slot)]
    gauge = slot_data.get('transformation_gauge', 0)
    is_alive = not slot_data.get('dead', False)
    return gauge >= TRANSFORM_GAUGE_FULL and is_alive, gauge


def activate_transformation(_args):
    load_transformation_sets(_args)
    room = Room.get_room(_args)
    if not room:
        return False

    slot = Room.get_slot(_args, room)
    slot_data = room['slots'][str(slot)]

    can_activate, gauge = can_transform(_args, room)
    head_id, body_id, arm_id = get_equipped_transformation_parts(_args)
    transformation_id = resolve_transformation_id(head_id, body_id, arm_id)

    character_name = _args['client']['character']['name']
    if not can_activate:
        print(f"[Transform] {character_name} failed: gauge={gauge}, reason=gauge_not_full_or_dead")
        return False

    if transformation_id == 0:
        print(f"[Transform] {character_name} failed: head={head_id}, body={body_id}, arm={arm_id}, reason=invalid_parts")
        return False

    slot_data['is_transformed'] = True
    slot_data['transformation_id'] = transformation_id
    slot_data['transformation_gauge'] = 0
    slot_data['transformation_at'] = int(time.time())

    print(
        f"[Transform] {character_name} head={head_id} body={body_id} arm={arm_id} "
        f"gauge={gauge} transformation_id={transformation_id} success"
    )
    broadcast_transformation_state(_args, room, slot, transformation_id)
    return True


def broadcast_transformation_state(_args, room, slot, transformation_id):
    result = PacketWrite()
    result.add_header([0x5C, 0x2F])
    result.append_bytes([0x01, 0x00])
    result.append_integer(slot - 1, 2, 'little')
    result.append_integer(transformation_id, 4, 'little')
    _args['connection_handler'].room_broadcast(room['id'], result.packet)
    Lobby.chat_message(_args['client'], f'Transformation activated ({transformation_id}).', 3)
