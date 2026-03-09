-- 008: 문의(CS) 테이블: inquiry, inquiry_reply

CREATE TABLE IF NOT EXISTS inquiry (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    author_id BIGINT UNSIGNED NOT NULL,
    project_id BIGINT UNSIGNED NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_inquiry_author FOREIGN KEY (author_id) REFERENCES admin_user (id) ON DELETE RESTRICT,
    CONSTRAINT fk_inquiry_project FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE SET NULL,
    INDEX idx_inquiry_status (status),
    INDEX idx_inquiry_created (created_at),
    INDEX idx_inquiry_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS inquiry_reply (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    inquiry_id BIGINT UNSIGNED NOT NULL,
    body TEXT NOT NULL,
    author_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_reply_inquiry FOREIGN KEY (inquiry_id) REFERENCES inquiry (id) ON DELETE CASCADE,
    CONSTRAINT fk_reply_author FOREIGN KEY (author_id) REFERENCES admin_user (id) ON DELETE RESTRICT,
    INDEX idx_reply_inquiry (inquiry_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
