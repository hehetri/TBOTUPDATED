from GameServer.Controllers.data.planet import PLANET_MAP_TABLE
import MySQL.Interface as MySQL

MISSION_TYPES = ['clear_map', 'kill_monsters', 'time_clear', 'repeat_clear', 'no_death_clear', 'daily_clear']

def run():
    conn = MySQL.get_connection()
    cur = conn.cursor()
    for map_id in range(0, 49):
        if map_id not in PLANET_MAP_TABLE:
            continue
        base_exp, minutes_limit, _, _, minimum_kills = PLANET_MAP_TABLE[map_id]
        rows = [
            ('clear_map', 1, 100, base_exp),
            ('kill_monsters', int(minimum_kills), 120, base_exp),
            ('time_clear', int(minutes_limit), 150, base_exp),
            ('repeat_clear', 3, 200, base_exp * 2),
            ('no_death_clear', 1, 180, base_exp),
            ('daily_clear', 1, 80, int(base_exp * 0.8)),
        ]
        for mtype, target, gold, exp in rows:
            cur.execute('''
                INSERT INTO missions(map_id, mission_type, target_value, reward_gold, reward_exp, is_active)
                VALUES (%s,%s,%s,%s,%s,1)
                ON DUPLICATE KEY UPDATE target_value=VALUES(target_value), reward_gold=VALUES(reward_gold), reward_exp=VALUES(reward_exp), is_active=1
            ''', [map_id, mtype, target, gold, exp])
    conn.commit()
    conn.close()

if __name__ == '__main__':
    run()
