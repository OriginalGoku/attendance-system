CREATE TABLE IF NOT EXISTS employees (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    telegram_id VARCHAR(64) NOT NULL,
    mac_address CHAR(17) NOT NULL,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_employees_mac_address (mac_address),
    KEY idx_employees_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS attendance_sessions (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT UNSIGNED NOT NULL,
    mac_address CHAR(17) NOT NULL,
    ip_address VARCHAR(45) NULL,
    hostname VARCHAR(255) NULL,
    entry_time DATETIME(6) NOT NULL,
    last_seen DATETIME(6) NOT NULL,
    exit_time DATETIME(6) NULL,
    status ENUM('open', 'closed') NOT NULL DEFAULT 'open',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_attendance_sessions_employee
        FOREIGN KEY (employee_id) REFERENCES employees(id),
    KEY idx_attendance_sessions_employee_id (employee_id),
    KEY idx_attendance_sessions_mac_status (mac_address, status),
    KEY idx_attendance_sessions_status_last_seen (status, last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS raw_presence_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    employee_id BIGINT UNSIGNED NULL,
    mac_address CHAR(17) NOT NULL,
    ip_address VARCHAR(45) NULL,
    hostname VARCHAR(255) NULL,
    event_type VARCHAR(32) NOT NULL,
    event_time DATETIME(6) NOT NULL,
    metadata JSON NULL,
    CONSTRAINT fk_raw_presence_events_employee
        FOREIGN KEY (employee_id) REFERENCES employees(id),
    KEY idx_raw_presence_events_mac_time (mac_address, event_time),
    KEY idx_raw_presence_events_employee_time (employee_id, event_time),
    KEY idx_raw_presence_events_type_time (event_type, event_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
