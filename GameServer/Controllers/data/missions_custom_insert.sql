-- Custom mission inserts with extended mission types
-- Source: operator-defined content

INSERT INTO `missions`
  (`map_id`, `mission_type`, `title`, `description`, `target_value`, `reward_gold`, `reward_exp`, `is_active`, `created_at`)
VALUES
(0, 'collect_item','Chip Collector','Gather 1x Chip, 1x SilverChip, and 1x GoldChip from battle drops and deliver them to the Guild NPC.',3,3000,400,1,NOW()),
(1, 'daily_clear','Daily Guild Supply','Deliver 3x GoldBar(1) or 1x GoldBar(3) to the Guild Warehouse. Resets every 24 hours.',1,8000,500,1,NOW()),
(2, 'kill_monsters','Beast Hunter','Defeat 10 DireFang and 10 Crawler enemies in Camp Spike. Collect LionK(Drop) and Spide(Drop) as proof.',20,5000,600,1,NOW()),
(2, 'collect_item','Beast Hunter: Proof of the Hunt','Deliver 10x LionK(Drop) and 10x Spide(Drop) to the NPC to complete the Beast Hunter quest.',20,0,0,1,NOW()),
(3, 'deliver_item','Disk Recovery','The laboratory needs critical components. Collect 2x Disk and 1x GoldDisk from enemies in Camp Escape and deliver them to the Scientist NPC.',3,6500,700,1,NOW()),
(4, 'collect_item','Letter Hunt','Find all 6 scattered fragments: [O], [R], [A], [N], [G], [E]. Each drops randomly in Planet Alderan battles. Deliver the complete set.',6,0,1500,1,NOW())
ON DUPLICATE KEY UPDATE
  title=VALUES(title),
  description=VALUES(description),
  target_value=VALUES(target_value),
  reward_gold=VALUES(reward_gold),
  reward_exp=VALUES(reward_exp),
  is_active=VALUES(is_active);
