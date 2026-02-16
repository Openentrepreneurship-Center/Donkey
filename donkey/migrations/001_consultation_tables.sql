-- consultation (부모)
CREATE TABLE IF NOT EXISTS consultation (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    file_url VARCHAR(2048) NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    UNIQUE KEY uk_job_id (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- consultation_log (1:1)
CREATE TABLE IF NOT EXISTS consultation_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    consultation_id BIGINT UNSIGNED NOT NULL,
    request_timestamp DATETIME(6) NOT NULL,
    completed_at DATETIME(6) NULL,
    processing_time_ms INT UNSIGNED NULL,
    audio_duration_sec DOUBLE NULL,
    stages JSON NULL,
    quality JSON NULL,
    model_usage JSON NULL,
    error JSON NULL,
    UNIQUE KEY uk_consultation_id (consultation_id),
    CONSTRAINT fk_log_consultation FOREIGN KEY (consultation_id) REFERENCES consultation (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- consultation_summary (1:1)
CREATE TABLE IF NOT EXISTS consultation_summary (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    consultation_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(512) NULL,
    simple_summary TEXT NULL,
    doctor_notes JSON NULL,
    test_results JSON NULL,
    symptom_record JSON NULL,
    prescription_and_care JSON NULL,
    conversation_content JSON NULL,
    UNIQUE KEY uk_consultation_id (consultation_id),
    CONSTRAINT fk_summary_consultation FOREIGN KEY (consultation_id) REFERENCES consultation (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
