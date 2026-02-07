-- ==================== UPLOADED FILES TABLE MIGRATION ====================
-- Date: 2026-01-31
-- Purpose: Add file upload tracking

CREATE TABLE IF NOT EXISTS uploaded_files (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_url VARCHAR(500) NOT NULL,
    thumbnail_url VARCHAR(500),
    file_size BIGINT NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    file_type VARCHAR(10),
    category VARCHAR(50) NOT NULL,
    description TEXT,
    appointment_id VARCHAR(50) REFERENCES appointments(id) ON DELETE SET NULL,
    is_active BOOLEAN DEFAULT TRUE,
    deleted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_uploaded_files_user ON uploaded_files(user_id);
CREATE INDEX idx_uploaded_files_category ON uploaded_files(category);
CREATE INDEX idx_uploaded_files_hash ON uploaded_files(file_hash);
CREATE INDEX idx_uploaded_files_appointment ON uploaded_files(appointment_id);
CREATE INDEX idx_uploaded_files_active ON uploaded_files(is_active);

-- Add insurance_proof_url to users table (if not exists)
ALTER TABLE users ADD COLUMN IF NOT EXISTS insurance_proof_url VARCHAR(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture_url VARCHAR(500);

-- Success message
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '================================================';
    RAISE NOTICE '✅ UPLOADED FILES TABLE CREATED!';
    RAISE NOTICE '================================================';
    RAISE NOTICE '📊 Table: uploaded_files';
    RAISE NOTICE '🔧 Indexes created for performance';
    RAISE NOTICE '🔗 Foreign keys: user_id, appointment_id';
    RAISE NOTICE '================================================';
END $$;