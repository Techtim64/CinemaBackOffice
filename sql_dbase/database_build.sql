CREATE DATABASE cinema_db_uat;

#CREATE USER 'cinema_user'@'%' IDENTIFIED BY 'Cinema1919!';
GRANT ALL PRIVILEGES ON cinema_db_uat.* TO 'cinema_user'@'%';
FLUSH PRIVILEGES;


CREATE DATABASE IF NOT EXISTS cinema_db
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE cinema_db_uat;

-- 1) App instellingen (bv. weekcounter, exportpad, etc.)
CREATE TABLE IF NOT EXISTS settings (
  `key`   VARCHAR(64) PRIMARY KEY,
  `value` TEXT NOT NULL
);

INSERT INTO settings(`key`,`value`)
VALUES ('week_counter','1')
ON DUPLICATE KEY UPDATE `value`=`value`;

-- 2) Films master data
CREATE TABLE IF NOT EXISTS films (
  id INT AUTO_INCREMENT PRIMARY KEY,

  interne_titel   VARCHAR(255) NOT NULL,   -- titel zoals in je CSV/variant
  maccsbox_titel  VARCHAR(255) NOT NULL,   -- titel zoals maccsbox wil
  distributeur    VARCHAR(255) NOT NULL,
  land_herkomst   VARCHAR(100) NOT NULL,

  actief TINYINT(1) NOT NULL DEFAULT 1,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_interne_titel (interne_titel)
);

-- 3) Speelweken (dinsdag -> dinsdag)
CREATE TABLE IF NOT EXISTS speelweek (
  id INT AUTO_INCREMENT PRIMARY KEY,
  weeknummer INT NOT NULL,
  start_datum DATE NOT NULL,   -- dinsdag
  eind_datum  DATE NOT NULL,   -- volgende dinsdag

  gesloten TINYINT(1) NOT NULL DEFAULT 0,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  UNIQUE KEY uq_week_range (start_datum, eind_datum),
  UNIQUE KEY uq_weeknummer (weeknummer)
);

-- 4) Dagelijkse sales per film
CREATE TABLE IF NOT EXISTS daily_sales (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,

  datum DATE NOT NULL,
  speelweek_id INT NOT NULL,
  film_id INT NOT NULL,

  is_3d TINYINT(1) NOT NULL DEFAULT 0,

  aantal_volw INT NOT NULL DEFAULT 0,
  aantal_kind INT NOT NULL DEFAULT 0,
  bedrag_volw DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  bedrag_kind DECIMAL(10,2) NOT NULL DEFAULT 0.00,

  totaal_aantal INT NOT NULL DEFAULT 0,
  totaal_bedrag DECIMAL(10,2) NOT NULL DEFAULT 0.00,

  source_file VARCHAR(255) NULL,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  CONSTRAINT fk_daily_week
    FOREIGN KEY (speelweek_id) REFERENCES speelweek(id)
    ON DELETE RESTRICT ON UPDATE CASCADE,

  CONSTRAINT fk_daily_film
    FOREIGN KEY (film_id) REFERENCES films(id)
    ON DELETE RESTRICT ON UPDATE CASCADE,

  UNIQUE KEY uq_datum_film (datum, film_id),
  KEY ix_week (speelweek_id),
  KEY ix_film (film_id),
  KEY ix_datum (datum)
);

USE cinema_db_uat;

CREATE TABLE IF NOT EXISTS zalen (
  id INT AUTO_INCREMENT PRIMARY KEY,
  naam VARCHAR(64) NOT NULL,
  UNIQUE KEY uq_zaal (naam)
);

ALTER TABLE daily_sales
  ADD COLUMN zaal_id INT NULL AFTER film_id;

ALTER TABLE daily_sales
  ADD CONSTRAINT fk_daily_zaal
    FOREIGN KEY (zaal_id) REFERENCES zalen(id)
    ON DELETE RESTRICT ON UPDATE CASCADE;

-- uniqueness becomes per date + film + zaal (so you can track per auditorium)
ALTER TABLE daily_sales
  DROP INDEX uq_datum_film;

ALTER TABLE daily_sales
  ADD UNIQUE KEY uq_datum_film_zaal (datum, film_id, zaal_id);
  
  ALTER TABLE daily_sales
  ADD COLUMN gratis_volw INT NOT NULL DEFAULT 0 AFTER aantal_kind,
  ADD COLUMN gratis_kind INT NOT NULL DEFAULT 0 AFTER gratis_volw;

CREATE TABLE ticket_ranges (
  id INT AUTO_INCREMENT PRIMARY KEY,
  speelweek_id INT NOT NULL,
  film_id INT NOT NULL,
  zaal_id INT NULL,
  begin_volw INT NOT NULL,
  begin_kind INT NOT NULL,
  UNIQUE KEY uq_range (speelweek_id, film_id, zaal_id),
  FOREIGN KEY (speelweek_id) REFERENCES speelweek(id),
  FOREIGN KEY (film_id) REFERENCES films(id),
  FOREIGN KEY (zaal_id) REFERENCES zalen(id)
);


