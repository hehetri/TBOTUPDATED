import datetime
import re
from Packet.Write import Write as PacketWrite
from GameServer.Controllers.data.planet import PLANET_MAP_TABLE
from GameServer.Controllers.data.planet import PLANET_DROPS
from GameServer.Controllers.data.drops import CHEST_GREEN
from GameServer.Controllers.Character import get_items, get_available_inventory_slot, add_item
from GameServer.Controllers.Character import remove_item
import random
from GameServer.Controllers.data.quest_item_ids import QUEST_ITEM_IDS

MISSION_TYPES = [
    'clear_map',
    'kill_monsters',
    'repeat_clear',
    'no_death_clear',
    'daily_clear',
    'collect_item',
    'deliver_item',
    'raid_boss',
    'event_quest'
]


def _ensure_mysql(_args):
    if _args.get('mysql') is not None:
        return None

    import MySQL.Interface as MySQL
    connection = MySQL.get_connection()
    _args['mysql'] = connection.cursor(dictionary=True)
    return connection


def _cleanup_mysql(connection):
    if connection is None:
        return
    try:
        connection.commit()
    except Exception:
        pass


def _commit_if_possible(_args):
    if _args.get('mysql_connection') is not None:
        try:
            _args['mysql_connection'].commit()
        except Exception:
            pass
    try:
        connection.close()
    except Exception:
        pass


def _today_key():
    return datetime.datetime.utcnow().strftime('%Y-%m-%d')


def list_map_missions(_args, character_id, map_id):
    try:
        _args['mysql'].execute("""
            SELECT m.id, m.map_id, m.mission_type, m.title, m.description, m.target_value, m.reward_gold, m.reward_exp,
                   COALESCE(p.current_value,0) current_value, COALESCE(p.completed,0) completed,
                   COALESCE(p.reward_collected,0) reward_collected
            FROM missions m
            LEFT JOIN player_mission_progress p
              ON p.mission_id = m.id AND p.character_id = %s
            WHERE m.map_id = %s AND m.is_active = 1 AND m.mission_type != 'time_clear'
            ORDER BY m.id ASC
        """, [character_id, map_id])
        return _args['mysql'].fetchall()
    except Exception as e:
        # Backward compatibility for old schema without missions.title/description
        if 'Unknown column' not in str(e):
            raise

        _args['mysql'].execute("""
            SELECT m.id, m.map_id, m.mission_type, m.target_value, m.reward_gold, m.reward_exp,
                   COALESCE(p.current_value,0) current_value, COALESCE(p.completed,0) completed,
                   COALESCE(p.reward_collected,0) reward_collected
            FROM missions m
            LEFT JOIN player_mission_progress p
              ON p.mission_id = m.id AND p.character_id = %s
            WHERE m.map_id = %s AND m.is_active = 1 AND m.mission_type != 'time_clear'
            ORDER BY m.id ASC
        """, [character_id, map_id])
        rows = _args['mysql'].fetchall()
        for row in rows:
            row['title'] = row['mission_type']
            row['description'] = ''
        return rows


def send_map_missions_packet(_args, map_id):
    temp_connection = _ensure_mysql(_args)
    character_id = _args['client']['character']['id']
    missions = list_map_missions(_args, character_id, map_id)
    # NOTE: custom mission packet disabled for compatibility with legacy clients.
    # Mission visibility is delivered via room chat summaries in Room.set_level.
    print('[MISSIONS] map_select character_id={0} map_id={1} missions={2}'.format(character_id, map_id, len(missions)))
    _cleanup_mysql(temp_connection)


def get_map_mission_summaries(_args, character_id, map_id):
    temp_connection = _ensure_mysql(_args)
    missions = list_map_missions(_args, character_id, map_id)
    summaries = []
    has_completed = False
    for mission in missions:
        if mission.get('completed', 0) == 1:
            has_completed = True
            continue
        summaries.append(
            '[PENDING] {0} ({1}/{2})'.format(
                mission.get('description', mission.get('title', mission['mission_type'])),
                mission.get('current_value', 0),
                mission.get('target_value', 0)
            )
        )
    if has_completed:
        summaries.insert(0, '[COMPLETED] You already have completed quests on this map.')
    _cleanup_mysql(temp_connection)
    return summaries


def upsert_progress(_args, character_id, mission_id, delta=0, force_complete=False):
    _args['mysql'].execute("""
        INSERT INTO player_mission_progress(character_id, mission_id, current_value, completed, reward_collected, updated_at)
        VALUES (%s,%s,%s,%s,0,UTC_TIMESTAMP())
        ON DUPLICATE KEY UPDATE
            current_value = current_value + %s,
            completed = IF(%s = 1, 1, completed),
            updated_at = UTC_TIMESTAMP()
    """, [character_id, mission_id, delta, 1 if force_complete else 0, delta, 1 if force_complete else 0])


def _grant_reward_if_available(_args, character_id, mission_id, map_id=None):
    _args['mysql'].execute("""
        SELECT m.reward_gold, m.reward_exp, p.completed, p.reward_collected
        FROM missions m
        INNER JOIN player_mission_progress p ON p.mission_id = m.id
        WHERE m.id = %s AND p.character_id = %s
    """, [mission_id, character_id])
    row = _args['mysql'].fetchone()
    if row is None or row['completed'] != 1 or row['reward_collected'] == 1:
        return False

    _args['mysql'].execute("""
        UPDATE player_mission_progress
        SET reward_collected = 1, updated_at = UTC_TIMESTAMP()
        WHERE character_id = %s AND mission_id = %s AND reward_collected = 0
    """, [character_id, mission_id])

    if _args['mysql'].rowcount == 0:
        return False

    _args['mysql'].execute("""
        UPDATE characters
        SET currency_gigas = currency_gigas + %s,
            experience = experience + %s,
            currency_botstract = currency_botstract + %s
        WHERE id = %s
    """, [row['reward_gold'], row['reward_exp'], 10, character_id])

    _args['mysql'].execute("""
        INSERT INTO mission_reward_logs(character_id, mission_id, reward_gold, reward_exp, claimed_at)
        VALUES (%s,%s,%s,%s,UTC_TIMESTAMP())
    """, [character_id, mission_id, row['reward_gold'], row['reward_exp']])

    # Mission drop reward: grant one CHEST_GREEN reward roll if map supports it.
    if map_id is not None and map_id in PLANET_DROPS and CHEST_GREEN in PLANET_DROPS[map_id]:
        sc = random.random()
        last_chance = 0.0
        item_id = 0
        for iid, chance in PLANET_DROPS[map_id][CHEST_GREEN]:
            if sc <= (chance + last_chance):
                item_id = iid
                break
            last_chance += chance

        if item_id != 0:
            _args['mysql'].execute(
                '''SELECT `id`, `item_id`, `buyable`, `gold_price`, `cash_price`, `part_type`, `duration` FROM `game_items` WHERE `item_id` = %s''',
                [item_id]
            )
            item = _args['mysql'].fetchone()
            if item is not None:
                inventory = get_items(_args, character_id, 'inventory')
                available_slot = get_available_inventory_slot(inventory)
                if available_slot is not None:
                    add_item(_args, item, available_slot)
    return True


def _extract_item_requirements(description):
    requirements = []
    if not description:
        return requirements

    for item_name, item_ids in QUEST_ITEM_IDS.items():
        if item_name not in description:
            continue
        match = re.search(r'(\\d+)x\\s*' + re.escape(item_name), description, flags=re.IGNORECASE)
        qty = int(match.group(1)) if match else 1
        requirements.append((item_name, item_ids, qty))
    return requirements


def _validate_and_consume_mission_items(_args, character_id, mission):
    requirements = _extract_item_requirements(mission.get('description', ''))
    if len(requirements) == 0:
        return True

    inventory = get_items(_args, character_id, 'inventory')
    by_item_id = {}
    for slot, data in inventory.items():
        by_item_id.setdefault(data['id'], []).append((slot, data))

    to_consume = []
    for _, valid_ids, qty in requirements:
        found = []
        for iid in valid_ids:
            found.extend(by_item_id.get(iid, []))
        if len(found) < qty:
            return False
        to_consume.extend(found[:qty])

    # Consume selected inventory items (deliver-item style validation)
    consumed = set()
    for _, data in to_consume:
        cid = data.get('character_item_id')
        if cid is not None and cid not in consumed:
            remove_item(_args, cid)
            consumed.add(cid)
    return True


def update_kill_progress(_args, room, kills=1):
    temp_connection = _ensure_mysql(_args)
    if room['game_type'] != 2 or room['level'] not in PLANET_MAP_TABLE:
        _cleanup_mysql(temp_connection)
        return

    for _, slot in room['slots'].items():
        character_id = slot['client']['character']['id']
        _args['mysql'].execute("""
            SELECT m.id, m.target_value, COALESCE(p.current_value,0) current_value
            FROM missions m
            LEFT JOIN player_mission_progress p ON p.mission_id=m.id AND p.character_id=%s
            WHERE m.map_id=%s AND m.mission_type='kill_monsters' AND m.is_active=1
        """, [character_id, room['level']])
        for mission in _args['mysql'].fetchall():
            new_value = mission['current_value'] + kills
            upsert_progress(_args, character_id, mission['id'], delta=kills, force_complete=new_value >= mission['target_value'])

    _commit_if_possible(_args)
    _cleanup_mysql(temp_connection)


def complete_map_missions(_args, room):
    temp_connection = _ensure_mysql(_args)
    if room['game_type'] != 2 or room['level'] not in PLANET_MAP_TABLE:
        _cleanup_mysql(temp_connection)
        return

    completed_notifications = {}

    for _, slot in room['slots'].items():
        client = slot['client']
        character_id = client['character']['id']
        won = 1 if slot.get('won') else 0
        no_death = 1 if slot.get('deaths', 0) == 0 else 0

        try:
            _args['mysql'].execute("""
                SELECT m.id, m.mission_type, m.title, m.target_value, COALESCE(p.current_value,0) current_value, COALESCE(p.completed,0) completed
                FROM missions m
                LEFT JOIN player_mission_progress p ON p.mission_id=m.id AND p.character_id=%s
                WHERE m.map_id=%s AND m.is_active=1 AND m.mission_type != 'time_clear'
            """, [character_id, room['level']])
            missions = _args['mysql'].fetchall()
        except Exception as e:
            if 'Unknown column' not in str(e):
                raise
            _args['mysql'].execute("""
                SELECT m.id, m.mission_type, m.target_value, COALESCE(p.current_value,0) current_value, COALESCE(p.completed,0) completed
                FROM missions m
                LEFT JOIN player_mission_progress p ON p.mission_id=m.id AND p.character_id=%s
                WHERE m.map_id=%s AND m.is_active=1 AND m.mission_type != 'time_clear'
            """, [character_id, room['level']])
            missions = _args['mysql'].fetchall()
            for mission in missions:
                mission['title'] = mission['mission_type']

        for mission in missions:
            mtype = mission['mission_type']
            if mtype == 'clear_map' and won:
                upsert_progress(_args, character_id, mission['id'], delta=1, force_complete=True)
                if mission['completed'] == 0:
                    completed_notifications.setdefault(character_id, []).append(mission.get('title', 'clear_map'))
                _grant_reward_if_available(_args, character_id, mission['id'], room['level'])
            elif mtype == 'repeat_clear' and won:
                new_val = mission['current_value'] + 1
                upsert_progress(_args, character_id, mission['id'], delta=1, force_complete=new_val >= mission['target_value'])
                if mission['completed'] == 0 and new_val >= mission['target_value']:
                    completed_notifications.setdefault(character_id, []).append(mission.get('title', 'repeat_clear'))
                _grant_reward_if_available(_args, character_id, mission['id'], room['level'])
            elif mtype == 'no_death_clear' and won and no_death:
                upsert_progress(_args, character_id, mission['id'], delta=1, force_complete=True)
                if mission['completed'] == 0:
                    completed_notifications.setdefault(character_id, []).append(mission.get('title', 'no_death_clear'))
                _grant_reward_if_available(_args, character_id, mission['id'], room['level'])
            elif mtype == 'daily_clear' and won:
                day = _today_key()
                _args['mysql'].execute("""
                    INSERT INTO player_mission_progress(character_id, mission_id, current_value, completed, reward_collected, daily_key, updated_at)
                    VALUES (%s,%s,1,1,0,%s,UTC_TIMESTAMP())
                    ON DUPLICATE KEY UPDATE
                        current_value = IF(daily_key=%s, current_value + 1, 1),
                        completed = 1,
                        reward_collected = IF(daily_key=%s, reward_collected, 0),
                        daily_key = %s,
                        updated_at = UTC_TIMESTAMP()
                """, [character_id, mission['id'], day, day, day, day])
                if mission['completed'] == 0:
                    completed_notifications.setdefault(character_id, []).append(mission.get('title', 'daily_clear'))
                _grant_reward_if_available(_args, character_id, mission['id'], room['level'])
            elif mtype in ['collect_item', 'deliver_item', 'raid_boss', 'event_quest'] and won:
                if _validate_and_consume_mission_items(_args, character_id, mission):
                    upsert_progress(_args, character_id, mission['id'], delta=1, force_complete=True)
                    if mission['completed'] == 0:
                        completed_notifications.setdefault(character_id, []).append(mission.get('title', mtype))
                    _grant_reward_if_available(_args, character_id, mission['id'], room['level'])

    _cleanup_mysql(temp_connection)
    _commit_if_possible(_args)
    return completed_notifications


def claim_reward(_args, mission_id):
    character_id = _args['client']['character']['id']
    conn = _args.get('mysql_connection')
    if conn is None:
        return False, 'missing_transaction_context'

    _args['mysql'].execute("""
        SELECT m.id, m.reward_gold, m.reward_exp, p.completed, p.reward_collected
        FROM missions m
        INNER JOIN player_mission_progress p ON p.mission_id=m.id
        WHERE m.id=%s AND p.character_id=%s
        FOR UPDATE
    """, [mission_id, character_id])
    row = _args['mysql'].fetchone()
    if row is None:
        return False, 'mission_not_found'
    if row['completed'] != 1:
        return False, 'not_completed'
    if row['reward_collected'] == 1:
        return False, 'already_collected'

    _args['mysql'].execute("UPDATE player_mission_progress SET reward_collected=1, updated_at=UTC_TIMESTAMP() WHERE character_id=%s AND mission_id=%s", [character_id, mission_id])
    _args['mysql'].execute("UPDATE characters SET currency_gigas = currency_gigas + %s, experience = experience + %s WHERE id=%s", [row['reward_gold'], row['reward_exp'], character_id])
    _args['mysql'].execute("INSERT INTO mission_reward_logs(character_id, mission_id, reward_gold, reward_exp, claimed_at) VALUES (%s,%s,%s,%s,UTC_TIMESTAMP())", [character_id, mission_id, row['reward_gold'], row['reward_exp']])
    conn.commit()
    return True, 'ok'


def claim_reward_rpc(**_args):
    mission_id = int(_args['packet'].read_integer(2, 4, 'little'))
    import MySQL.Interface as MySQL
    conn = MySQL.get_connection()
    cursor = conn.cursor(dictionary=True)
    local_args = dict(_args)
    local_args['mysql'] = cursor
    local_args['mysql_connection'] = conn

    ok, reason = claim_reward(local_args, mission_id)

    print('[MISSIONS] claim_reward character_id={0} mission_id={1} ok={2} reason={3}'.format(
        _args['client']['character']['id'], mission_id, ok, reason
    ))

    cursor.close()
    conn.close()
