-- 004: admin 스키마 → develop 스키마 정렬
-- (project 추가, api_key/request에 project_id, consultation 제거)

-- 1. project 테이블 생성
CREATE TABLE IF NOT EXISTS project (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_project_client FOREIGN KEY (client_id) REFERENCES client (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. 기본 project 생성 (client id=1 소속)
INSERT IGNORE INTO project (id, client_id, name) VALUES (1, 1, 'default');

-- 3. api_key에 project_id 추가
ALTER TABLE api_key ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER client_id;
UPDATE api_key SET project_id = 1 WHERE project_id IS NULL;
ALTER TABLE api_key MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL;
ALTER TABLE api_key ADD CONSTRAINT fk_api_key_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE CASCADE;

-- 4. api_key에 name, updated_at 추가 (develop 스키마)
ALTER TABLE api_key ADD COLUMN name VARCHAR(255) NULL AFTER key_prefix;
ALTER TABLE api_key ADD COLUMN updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) AFTER created_at;

-- 5. request에 project_id 추가
ALTER TABLE request ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER client_id;
UPDATE request SET project_id = 1 WHERE project_id IS NULL;
ALTER TABLE request MODIFY COLUMN project_id BIGINT UNSIGNED NOT NULL;
ALTER TABLE request ADD CONSTRAINT fk_request_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE RESTRICT;

-- 6. consultation 계열 제거 (develop은 request 사용)
DROP TABLE IF EXISTS consultation_summary;
DROP TABLE IF EXISTS consultation_log;
DROP TABLE IF EXISTS consultation;
