-- ==================== PROFILE IMPROVEMENTS MIGRATION ====================
-- Date: 2026-01-31
-- Purpose: Add family members, addresses, notification preferences tables

-- 1. FAMILY MEMBERS TABLE
CREATE TABLE IF NOT EXISTS family_members (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    relation VARCHAR(20) NOT NULL,  -- father/mother/spouse/child/sibling/other
    age INTEGER,
    gender VARCHAR(10),
    blood_group VARCHAR(5),
    phone VARCHAR(15),
    allergies JSONB,
    medical_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_family_members_user ON family_members(user_id);

-- 2. ADDRESSES TABLE
CREATE TABLE IF NOT EXISTS addresses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label VARCHAR(50) NOT NULL,  -- Home/Office/Other
    address_line1 VARCHAR(200) NOT NULL,
    address_line2 VARCHAR(200),
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    pincode VARCHAR(10) NOT NULL,
    location_lat DECIMAL(10, 8),
    location_lng DECIMAL(11, 8),
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_addresses_user ON addresses(user_id);
CREATE INDEX idx_addresses_default ON addresses(user_id, is_default);

-- 3. NOTIFICATION PREFERENCES TABLE
CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    sms_enabled BOOLEAN DEFAULT TRUE,
    email_enabled BOOLEAN DEFAULT TRUE,
    push_enabled BOOLEAN DEFAULT TRUE,
    appointment_reminders BOOLEAN DEFAULT TRUE,
    lab_test_reminders BOOLEAN DEFAULT TRUE,
    order_updates BOOLEAN DEFAULT TRUE,
    promotional BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. ADD MISSING COLUMNS TO USERS TABLE
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_photo_url VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS scheduled_deletion_date DATE;

-- 5. CREATE DEFAULT NOTIFICATION PREFERENCES FOR EXISTING USERS
INSERT INTO notification_preferences (user_id)
SELECT id FROM users
ON CONFLICT (user_id) DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '================================================';
    RAISE NOTICE '✅ PROFILE TABLES MIGRATION COMPLETED!';
    RAISE NOTICE '================================================';
    RAISE NOTICE '📊 Tables created:';
    RAISE NOTICE '   - family_members';
    RAISE NOTICE '   - addresses';
    RAISE NOTICE '   - notification_preferences';
    RAISE NOTICE '🔧 Columns added to users:';
    RAISE NOTICE '   - profile_photo_url';
    RAISE NOTICE '   - deletion_requested_at';
    RAISE NOTICE '   - scheduled_deletion_date';
    RAISE NOTICE '================================================';
END $$;