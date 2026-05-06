CREATE TABLE IF NOT EXISTS missions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  map_id INT NOT NULL,
  mission_type VARCHAR(32) NOT NULL,
  title VARCHAR(128) NOT NULL DEFAULT '',
  description VARCHAR(255) NOT NULL DEFAULT '',
  target_value INT NOT NULL DEFAULT 1,
  reward_gold INT NOT NULL DEFAULT 0,
  reward_exp INT NOT NULL DEFAULT 0,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_map_type (map_id, mission_type),
  KEY idx_map_active (map_id, is_active)
);

CREATE TABLE IF NOT EXISTS player_mission_progress (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  character_id INT NOT NULL,
  mission_id INT NOT NULL,
  current_value INT NOT NULL DEFAULT 0,
  completed TINYINT(1) NOT NULL DEFAULT 0,
  reward_collected TINYINT(1) NOT NULL DEFAULT 0,
  daily_key VARCHAR(10) DEFAULT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_character_mission (character_id, mission_id),
  KEY idx_character_completed (character_id, completed, reward_collected),
  KEY idx_daily (character_id, daily_key)
);

CREATE TABLE IF NOT EXISTS mission_reward_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  character_id INT NOT NULL,
  mission_id INT NOT NULL,
  reward_gold INT NOT NULL,
  reward_exp INT NOT NULL,
  claimed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_character_claimed (character_id, claimed_at),
  KEY idx_mission_claimed (mission_id, claimed_at)
);

