-- 004: project, api_key 추가 + consultation → request 리네이밍 + client_id, project_id 추가
-- (client는 003_client.sql에서 생성, hippocrat 로우 삽입됨)

-- 1. project 테이블 (client 소속)
CREATE TABLE IF NOT EXISTS project (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_project_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. api_key 테이블 (client + project 발급 대상)
CREATE TABLE IF NOT EXISTS api_key (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id BIGINT UNSIGNED NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    key_hash VARCHAR(255) NOT NULL,
    key_prefix VARCHAR(20) NOT NULL,
    name VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_key_hash (key_hash),
    CONSTRAINT fk_api_key_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE CASCADE,
    CONSTRAINT fk_api_key_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. 기존 consultation에 client_id, project_id 추가 (nullable)
ALTER TABLE consultation
ADD COLUMN client_id BIGINT UNSIGNED NULL AFTER id,
ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER client_id;

-- 5. 기본 project 생성 (client id=1 hippocrat 소속, 기존 데이터 마이그레이션용)
INSERT INTO project (id, client_id, name) VALUES (1, 1, 'default');

-- 6. 기존 consultation에 기본 client_id, project_id 설정
UPDATE consultation SET client_id = 1, project_id = 1 WHERE client_id IS NULL OR project_id IS NULL;

-- 7. client_id, project_id NOT NULL로 변경 및 FK 추가
ALTER TABLE consultation
MODIFY COLUMN client_id BIGINT UNSIGNED NOT NULL,
MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL,
ADD CONSTRAINT fk_consultation_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE RESTRICT,
ADD CONSTRAINT fk_consultation_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE RESTRICT;

-- 8. consultation → request 리네이밍
RENAME TABLE consultation TO request;

-- 9. consultation_log → request_log 리네이밍 + consultation_id → request_id
ALTER TABLE consultation_log
CHANGE COLUMN consultation_id request_id BIGINT UNSIGNED NOT NULL,
DROP FOREIGN KEY fk_log_consultation,
ADD CONSTRAINT fk_log_request FOREIGN KEY (request_id) REFERENCES request (id) ON DELETE CASCADE,
DROP INDEX uk_consultation_id,
ADD UNIQUE KEY uk_request_id (request_id);
RENAME TABLE consultation_log TO request_log;

-- 10. consultation_summary → request_summary 리네이밍 + consultation_id → request_id
ALTER TABLE consultation_summary
CHANGE COLUMN consultation_id request_id BIGINT UNSIGNED NOT NULL,
DROP FOREIGN KEY fk_summary_consultation,
ADD CONSTRAINT fk_summary_request FOREIGN KEY (request_id) REFERENCES request (id) ON DELETE CASCADE,
DROP INDEX uk_consultation_id,
ADD UNIQUE KEY uk_request_id (request_id);
RENAME TABLE consultation_summary TO request_summary;
