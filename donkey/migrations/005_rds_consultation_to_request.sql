-- 005: 운영 RDS (consultation 기반) → develop 스키마 마이그레이션
-- 기존 데이터는 모두 client_id=1, project_id=1로 할당
-- 전제: 001_consultation_tables.sql, 002_consultation_stored_audio_url.sql 적용됨

-- 1. client 테이블 + 기본 행
CREATE TABLE IF NOT EXISTS client (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(64) NOT NULL,
    display_name VARCHAR(128) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_client_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO client (id, name, display_name) VALUES (1, 'hippo', '마이그레이션 데이터');

-- 2. project 테이블 + 기본 행
CREATE TABLE IF NOT EXISTS project (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_project_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO project (id, client_id, name) VALUES (1, 1, 'datahippo');

-- 3. api_key 테이블 (빈 상태로 생성, 스키마만)
CREATE TABLE IF NOT EXISTS api_key (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id BIGINT UNSIGNED NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    key_hash VARCHAR(255) NOT NULL,
    key_prefix VARCHAR(20) NOT NULL DEFAULT '',
    name VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_key_hash (key_hash),
    CONSTRAINT fk_api_key_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE CASCADE,
    CONSTRAINT fk_api_key_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. consultation에 client_id, project_id 추가
ALTER TABLE consultation
ADD COLUMN client_id BIGINT UNSIGNED NULL AFTER id,
ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER client_id;

-- 5. 기존 데이터를 모두 client=1, project=1로 할당
UPDATE consultation SET client_id = 1, project_id = 1 WHERE client_id IS NULL OR project_id IS NULL;

-- 6. NOT NULL + FK 적용
ALTER TABLE consultation
MODIFY COLUMN client_id BIGINT UNSIGNED NOT NULL,
MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL,
ADD CONSTRAINT fk_consultation_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE RESTRICT,
ADD CONSTRAINT fk_consultation_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE RESTRICT;

-- 7. consultation → request 리네이밍
RENAME TABLE consultation TO request;

-- 8. request에 request_type 추가 (admin/develop 호환)
ALTER TABLE request ADD COLUMN request_type VARCHAR(32) NOT NULL DEFAULT 'consultation' AFTER project_id;

-- 9. consultation_log → request_log
ALTER TABLE consultation_log
CHANGE COLUMN consultation_id request_id BIGINT UNSIGNED NOT NULL,
DROP FOREIGN KEY fk_log_consultation,
ADD CONSTRAINT fk_log_request FOREIGN KEY (request_id) REFERENCES request (id) ON DELETE CASCADE,
DROP INDEX uk_consultation_id,
ADD UNIQUE KEY uk_request_id (request_id);
RENAME TABLE consultation_log TO request_log;

-- 10. consultation_summary → request_summary
ALTER TABLE consultation_summary
CHANGE COLUMN consultation_id request_id BIGINT UNSIGNED NOT NULL,
DROP FOREIGN KEY fk_summary_consultation,
ADD CONSTRAINT fk_summary_request FOREIGN KEY (request_id) REFERENCES request (id) ON DELETE CASCADE,
DROP INDEX uk_consultation_id,
ADD UNIQUE KEY uk_request_id (request_id);
RENAME TABLE consultation_summary TO request_summary;

-- 11. admin_user 테이블 + 기본 계정
CREATE TABLE IF NOT EXISTS admin_user (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(128) NULL,
    client_id BIGINT UNSIGNED NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_user_id (user_id),
    CONSTRAINT fk_admin_user_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO admin_user (user_id, password_hash, display_name, client_id, is_active)
VALUES ('hippocrat', '$2b$12$fI3Lf64zuMdc62wmGyFWX.pGHx2zBrXtiNibepiPqoj4wI9728WK2', 'Hippocrat', 1, 1);