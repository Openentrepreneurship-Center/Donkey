-- 005 실패 후 재실행: consultation_log, consultation_summary 리네이밍 (실제 FK 이름 사용)

-- 9. consultation_log → request_log (FK: consultation_log_ibfk_1)
ALTER TABLE consultation_log
DROP FOREIGN KEY consultation_log_ibfk_1,
CHANGE COLUMN consultation_id request_id BIGINT NOT NULL,
ADD CONSTRAINT fk_log_request FOREIGN KEY (request_id) REFERENCES request (id) ON DELETE CASCADE,
DROP INDEX consultation_id,
ADD UNIQUE KEY uk_request_id (request_id);
RENAME TABLE consultation_log TO request_log;

-- 10. consultation_summary → request_summary (실제 FK 이름 확인 필요)
-- 먼저 확인: SHOW CREATE TABLE consultation_summary\G
-- 아래는 consultation_summary_ibfk_1 가정 (다르면 수정)
ALTER TABLE consultation_summary
DROP FOREIGN KEY consultation_summary_ibfk_1,
CHANGE COLUMN consultation_id request_id BIGINT NOT NULL,
ADD CONSTRAINT fk_summary_request FOREIGN KEY (request_id) REFERENCES request (id) ON DELETE CASCADE,
DROP INDEX consultation_id,
ADD UNIQUE KEY uk_request_id (request_id);
RENAME TABLE consultation_summary TO request_summary;
