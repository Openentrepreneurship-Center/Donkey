-- 007: request_log에 summary_eval 컬럼 추가

ALTER TABLE request_log ADD COLUMN summary_eval JSON NULL AFTER error;
