-- consultation에 S3 저장 오디오 URL 컬럼 추가
ALTER TABLE consultation
ADD COLUMN stored_audio_url VARCHAR(2048) NULL AFTER file_url;
