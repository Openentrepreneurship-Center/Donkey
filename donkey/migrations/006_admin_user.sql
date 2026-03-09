-- 006: admin_user 테이블 + 기본 계정 (005 11단계 미실행분)

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
