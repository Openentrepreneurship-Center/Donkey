-- 009: inquiry에 project_id 추가 (008 이미 적용된 경우)

ALTER TABLE inquiry ADD COLUMN project_id BIGINT UNSIGNED NULL AFTER author_id;
ALTER TABLE inquiry ADD CONSTRAINT fk_inquiry_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE SET NULL;
ALTER TABLE inquiry ADD INDEX idx_inquiry_project (project_id);
