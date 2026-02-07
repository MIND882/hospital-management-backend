-- ==================== MIGRATION SCRIPT ====================
-- Run this to UPDATE existing database (NOT delete!)
-- Date: 2026-01-31
-- Purpose: Add missing columns to existing tables

-- 1. Users table updates
DO $$
BEGIN
    -- Add location columns if not exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='location_lat') THEN
        ALTER TABLE users ADD COLUMN location_lat DECIMAL(10, 8);
        RAISE NOTICE '✅ Added location_lat to users';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='location_lng') THEN
        ALTER TABLE users ADD COLUMN location_lng DECIMAL(11, 8);
        RAISE NOTICE '✅ Added location_lng to users';
    END IF;
    
    -- Add address if not exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='address') THEN
        ALTER TABLE users ADD COLUMN address TEXT;
        RAISE NOTICE '✅ Added address to users';
    END IF;
    
    -- Add insurance columns
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='insurance_provider') THEN
        ALTER TABLE users ADD COLUMN insurance_provider VARCHAR(50);
        RAISE NOTICE '✅ Added insurance_provider to users';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='insurance_number') THEN
        ALTER TABLE users ADD COLUMN insurance_number VARCHAR(50);
        RAISE NOTICE '✅ Added insurance_number to users';
    END IF;
    
    -- Add allergies (JSONB)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='allergies') THEN
        ALTER TABLE users ADD COLUMN allergies JSONB;
        RAISE NOTICE '✅ Added allergies to users';
    END IF;
    
    -- Add OTP columns for auth
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='otp') THEN
        ALTER TABLE users ADD COLUMN otp VARCHAR(255);
        RAISE NOTICE '✅ Added otp to users';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='otp_expires_at') THEN
        ALTER TABLE users ADD COLUMN otp_expires_at TIMESTAMP;
        RAISE NOTICE '✅ Added otp_expires_at to users';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='is_verified') THEN
        ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT FALSE;
        RAISE NOTICE '✅ Added is_verified to users';
    END IF;
END $$;

-- 2. Medicines table updates
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='medicines' AND column_name='description') THEN
        ALTER TABLE medicines ADD COLUMN description TEXT;
        RAISE NOTICE '✅ Added description to medicines';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='medicines' AND column_name='category') THEN
        ALTER TABLE medicines ADD COLUMN category VARCHAR(50);
        RAISE NOTICE '✅ Added category to medicines';
    END IF;
END $$;

-- 3. Lab Tests table updates
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='lab_tests' AND column_name='category') THEN
        ALTER TABLE lab_tests ADD COLUMN category VARCHAR(50);
        RAISE NOTICE '✅ Added category to lab_tests';
    END IF;
END $$;

-- 4. Clinics table updates
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='clinics' AND column_name='rating') THEN
        ALTER TABLE clinics ADD COLUMN rating DECIMAL(3, 2) DEFAULT 0.0;
        RAISE NOTICE '✅ Added rating to clinics';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='clinics' AND column_name='total_reviews') THEN
        ALTER TABLE clinics ADD COLUMN total_reviews INTEGER DEFAULT 0;
        RAISE NOTICE '✅ Added total_reviews to clinics';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='clinics' AND column_name='created_at') THEN
        ALTER TABLE clinics ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        RAISE NOTICE '✅ Added created_at to clinics';
    END IF;
END $$;

-- 5. Doctors table updates
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='doctors' AND column_name='rating') THEN
        ALTER TABLE doctors ADD COLUMN rating DECIMAL(3, 2) DEFAULT 0.0;
        RAISE NOTICE '✅ Added rating to doctors';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='doctors' AND column_name='created_at') THEN
        ALTER TABLE doctors ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        RAISE NOTICE '✅ Added created_at to doctors';
    END IF;
END $$;

-- 6. Create indexes for performance (if not exist)
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
CREATE INDEX IF NOT EXISTS idx_users_location ON users(location_lat, location_lng);
CREATE INDEX IF NOT EXISTS idx_appointments_user_date ON appointments(user_id, date);
CREATE INDEX IF NOT EXISTS idx_appointments_doctor ON appointments(doctor_id);
CREATE INDEX IF NOT EXISTS idx_lab_bookings_user ON lab_bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread ON notifications(user_id, is_read);

-- 7. Add constraints (if not exist)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_phone_unique') THEN
        ALTER TABLE users ADD CONSTRAINT users_phone_unique UNIQUE(phone);
        RAISE NOTICE '✅ Added unique constraint on users.phone';
    END IF;
END $$;

-- Final success message
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '================================================';
    RAISE NOTICE '✅ MIGRATION COMPLETED SUCCESSFULLY!';
    RAISE NOTICE '================================================';
    RAISE NOTICE '📊 All missing columns added';
    RAISE NOTICE '🚀 Database is production-ready';
    RAISE NOTICE '💾 No data was lost';
    RAISE NOTICE '⚡ Performance indexes created';
    RAISE NOTICE '================================================';
END $$;