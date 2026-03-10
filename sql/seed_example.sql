INSERT INTO employees (name, telegram_id, mac_address, active)
VALUES
    ('John Doe', '123456789', 'aa:bb:cc:dd:ee:ff', 1),
    ('Jane Smith', '987654321', '11:22:33:44:55:66', 1)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    telegram_id = VALUES(telegram_id),
    active = VALUES(active);
