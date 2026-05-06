import os
import sys

# Allow running this script directly from repository root or by full path on Windows.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from GameServer.Controllers.data.map_missions import MAP_MISSIONS
import MySQL.Interface as MySQL


def run():
    conn = MySQL.get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT `COLUMN_NAME`
        FROM `INFORMATION_SCHEMA`.`COLUMNS`
        WHERE `TABLE_SCHEMA` = DATABASE() AND `TABLE_NAME` = 'missions'
    """)
    mission_columns = [row[0] for row in cur.fetchall()]
    has_title_columns = ('title' in mission_columns and 'description' in mission_columns)
    for map_id in range(0, 49):
        mission_meta = MAP_MISSIONS.get(map_id)
        if mission_meta is None:
            continue

        map_name = mission_meta['map_name']
        mission_rows = mission_meta['missions']
        type_order = ['clear_map', 'kill_monsters', 'time_clear', 'repeat_clear', 'no_death_clear', 'daily_clear']

        # target defaults; parser from description for kills/time
        targets = [1, 1, 1, 3, 1, 1]
        try:
            targets[1] = int(mission_rows[1][1].split('Defeat ')[1].split(' monsters')[0])
            targets[2] = int(float(mission_rows[2][1].split('within ')[1].split(' minutes')[0]) * 60)
        except Exception:
            pass

        for idx, mtype in enumerate(type_order):
            title, desc = mission_rows[idx]
            if has_title_columns:
                cur.execute('''
                    INSERT INTO missions(map_id, mission_type, title, description, target_value, reward_gold, reward_exp, is_active)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,1)
                    ON DUPLICATE KEY UPDATE
                        title=VALUES(title),
                        description=VALUES(description),
                        target_value=VALUES(target_value),
                        reward_gold=VALUES(reward_gold),
                        reward_exp=VALUES(reward_exp),
                        is_active=1
                ''', [map_id, mtype, title, desc, targets[idx], 100 + (idx * 20), 1000 + (map_id * 10)])
            else:
                cur.execute('''
                    INSERT INTO missions(map_id, mission_type, target_value, reward_gold, reward_exp, is_active)
                    VALUES (%s,%s,%s,%s,%s,1)
                    ON DUPLICATE KEY UPDATE
                        target_value=VALUES(target_value),
                        reward_gold=VALUES(reward_gold),
                        reward_exp=VALUES(reward_exp),
                        is_active=1
                ''', [map_id, mtype, targets[idx], 100 + (idx * 20), 1000 + (map_id * 10)])

    conn.commit()
    conn.close()


if __name__ == '__main__':
    run()
