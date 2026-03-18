-- Migration 001: allow attendance_sessions.employee_id to be NULL
-- This enables session tracking for all devices, not just registered employees.
-- The remote server is responsible for resolving MAC addresses to staff.

ALTER TABLE attendance_sessions
    MODIFY employee_id BIGINT UNSIGNED NULL;
