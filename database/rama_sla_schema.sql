-- ==============================================================================
-- RAMA Computer and Network Solution - MySQL 8 SLA Database Schema
-- Location: Addis Ababa, Ethiopia
-- Description: Database structure for SLA Maintenance Packages (Bronze, Silver, Gold)
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS rama_sla
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE rama_sla;

-- ------------------------------------------------------------------------------
-- 1. SLA TIERS CATALOG TABLE (Reference table for SLA packages & pricing benchmarks)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_tiers (
    tier_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    tier_code VARCHAR(20) UNIQUE NOT NULL,          -- BRONZE, SILVER, GOLD, CUSTOM
    tier_name VARCHAR(50) NOT NULL,                 -- e.g., 'Silver SLA'
    description TEXT NOT NULL,                      -- Summary of tier focus
    response_time_p1 VARCHAR(50) NOT NULL,          -- e.g., '< 4 Hours'
    response_time_p2 VARCHAR(50) NOT NULL,          -- e.g., '< 8 Hours'
    preventive_audit_freq VARCHAR(50) NOT NULL,     -- e.g., 'Monthly'
    noc_monitoring_type VARCHAR(50) NOT NULL,       -- e.g., '12/5 Business Hours'
    spare_swap_access BOOLEAN DEFAULT 1,            -- Local spare hardware pool access
    monthly_rate_base_usd DECIMAL(10, 2) NOT NULL,  -- Base rate USD benchmark
    monthly_rate_base_etb DECIMAL(12, 2) NOT NULL,  -- Base rate ETB benchmark
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tier_id)
) ENGINE=InnoDB;

-- Seed initial SLA Tiers Catalog
INSERT INTO sla_tiers (tier_code, tier_name, description, response_time_p1, response_time_p2, preventive_audit_freq, noc_monitoring_type, spare_swap_access, monthly_rate_base_usd, monthly_rate_base_etb)
VALUES 
('BRONZE', 'Bronze SLA', 'Standard support for SMEs and non-critical office networks.', 'Next Business Day', '< 24 Hours', 'Quarterly', 'Helpdesk Ticketing', 0, 650.00, 81250.00),
('SILVER', 'Silver SLA', 'Business critical care for commercial hubs, hotels, and retail centers.', '< 4 Hours', '< 8 Hours', 'Monthly', '12/5 Business NOC', 1, 1200.00, 150000.00),
('GOLD', 'Gold SLA', 'Mission-critical priority support for banks, hospitals, and high-uptime facilities.', '< 2 Hours', '< 4 Hours', 'Bi-Weekly', '24/7/365 Continuous', 1, 2200.00, 275000.00),
('CUSTOM', 'Custom SLA', 'Custom multi-branch SLA support tailored to client requirements.', 'Negotiated', 'Negotiated', 'As Agreed', 'As Agreed', 1, 0.00, 0.00)
ON DUPLICATE KEY UPDATE
    tier_name = VALUES(tier_name),
    description = VALUES(description),
    response_time_p1 = VALUES(response_time_p1),
    response_time_p2 = VALUES(response_time_p2),
    preventive_audit_freq = VALUES(preventive_audit_freq),
    noc_monitoring_type = VALUES(noc_monitoring_type),
    spare_swap_access = VALUES(spare_swap_access),
    monthly_rate_base_usd = VALUES(monthly_rate_base_usd),
    monthly_rate_base_etb = VALUES(monthly_rate_base_etb);


-- ------------------------------------------------------------------------------
-- 2. CLIENT ORGANIZATION TYPES / SECTORS
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS client_sectors (
    sector_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    sector_code VARCHAR(30) UNIQUE NOT NULL,        -- SME, BANK, HOSPITAL, HOTEL, REAL_ESTATE, GOVT
    sector_name VARCHAR(100) NOT NULL,
    PRIMARY KEY (sector_id)
) ENGINE=InnoDB;

INSERT INTO client_sectors (sector_code, sector_name) VALUES
('SME', 'Small & Medium Enterprise'),
('BANK', 'Banking & Financial Institution'),
('HOSPITAL', 'Hospital & Healthcare Hub'),
('HOTEL', 'Hotel & Hospitality'),
('REAL_ESTATE', 'Commercial Real Estate / Building'),
('EDUCATION', 'Educational Institution'),
('GOVT', 'Government / Public Sector')
ON DUPLICATE KEY UPDATE sector_name = VALUES(sector_name);


-- ------------------------------------------------------------------------------
-- 3. SLA INQUIRY & ENROLLMENT FORM SUBMISSIONS TABLE
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_inquiries (
    inquiry_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    inquiry_ref VARCHAR(30) UNIQUE NOT NULL,        -- e.g., 'RAMA-SLA-2026-0001'
    company_name VARCHAR(150) NOT NULL,
    contact_person VARCHAR(100) NOT NULL,
    contact_title VARCHAR(100),
    phone_number VARCHAR(30) NOT NULL,
    email_address VARCHAR(100),
    sub_city VARCHAR(50) NOT NULL,                  -- e.g., 'Bole', 'Kazanchis', 'Kirkos'
    woreda VARCHAR(20),
    specific_address TEXT,                          -- e.g., 'Near Atlas Hotel, Building 4'
    
    sector_code VARCHAR(30) NOT NULL,               -- Foreign key to client_sectors
    preferred_tier_code VARCHAR(20) NOT NULL,       -- Foreign key to sla_tiers
    
    estimated_switches INTEGER DEFAULT 0,
    estimated_routers INTEGER DEFAULT 0,
    estimated_firewalls INTEGER DEFAULT 0,
    estimated_access_points INTEGER DEFAULT 0,
    total_estimated_devices INTEGER DEFAULT 0,
    
    additional_requirements TEXT,                   -- Specific client notes / cable drops
    inquiry_status VARCHAR(30) NOT NULL DEFAULT 'Pending', -- Active, Pending, Postponed, Done
    
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (inquiry_id),
    KEY idx_inquiries_status (inquiry_status),
    KEY idx_inquiries_tier (preferred_tier_code),
    KEY idx_inquiries_subcity (sub_city),
    FOREIGN KEY (sector_code) REFERENCES client_sectors(sector_code),
    FOREIGN KEY (preferred_tier_code) REFERENCES sla_tiers(tier_code)
) ENGINE=InnoDB;

ALTER TABLE sla_inquiries
    MODIFY inquiry_status VARCHAR(30) NOT NULL DEFAULT 'Pending';


-- ------------------------------------------------------------------------------
-- 4. ON-SITE AUDIT & DISPATCH SCHEDULE TABLE
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_schedules (
    audit_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    inquiry_id INT UNSIGNED NOT NULL,
    assigned_engineer_name VARCHAR(100) NOT NULL,
    audit_date DATE NOT NULL,
    audit_time TIME NOT NULL,
    audit_status VARCHAR(30) DEFAULT 'SCHEDULED',   -- SCHEDULED, COMPLETED, RESCHEDULED
    findings_summary TEXT,
    fluke_test_passed BOOLEAN DEFAULT NULL,
    ups_health_check_passed BOOLEAN DEFAULT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (audit_id),
    KEY idx_audits_date (audit_date),
    FOREIGN KEY (inquiry_id) REFERENCES sla_inquiries(inquiry_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------------------------
-- 5. NOC DASHBOARD ACCOUNTS
-- Passwords are stored as salted PBKDF2 hashes by the Python backend.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS noc_users (
    user_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(80) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    user_role ENUM('worker', 'manager') NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id),
    UNIQUE KEY uq_noc_users_username (username),
    KEY idx_noc_users_role (user_role)
) ENGINE=InnoDB;
