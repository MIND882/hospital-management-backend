-- ==================== PHARMACY VENDOR SCHEMA ====================
-- Date: 2026-01-31
-- Complete schema for pharmacy vendor system

-- Users table (if not exists)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    phone VARCHAR(15),
    full_name VARCHAR(100),
    role VARCHAR(50) DEFAULT 'customer',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Pharmacies table
CREATE TABLE IF NOT EXISTS pharmacies (
    id SERIAL PRIMARY KEY,
    display_id VARCHAR(50) UNIQUE NOT NULL,
    owner_user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    license_number VARCHAR(50) UNIQUE NOT NULL,
    drug_license_number VARCHAR(50) NOT NULL,
    phone VARCHAR(15) NOT NULL,
    email VARCHAR(255) NOT NULL,
    address VARCHAR(200) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    pincode VARCHAR(6) NOT NULL,
    location_lat DECIMAL(10, 8),
    location_lng DECIMAL(11, 8),
    owner_name VARCHAR(100) NOT NULL,
    gstin VARCHAR(15) UNIQUE,
    operating_hours JSONB NOT NULL,
    home_delivery_available BOOLEAN DEFAULT TRUE,
    minimum_order_amount FLOAT DEFAULT 0.0,
    is_verified BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    rating FLOAT DEFAULT 0.0,
    total_orders INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pharmacies_owner ON pharmacies(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_pharmacies_city ON pharmacies(city);
CREATE INDEX IF NOT EXISTS idx_pharmacies_verified ON pharmacies(is_verified);

-- Medicines table
CREATE TABLE IF NOT EXISTS medicines (
    id SERIAL PRIMARY KEY,
    pharmacy_id INTEGER NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    generic_name VARCHAR(200),
    category VARCHAR(100) NOT NULL,
    dosage VARCHAR(100),
    manufacturer VARCHAR(100) NOT NULL,
    composition VARCHAR(300),
    description TEXT,
    mrp FLOAT NOT NULL,
    selling_price FLOAT NOT NULL,
    discount_percentage FLOAT DEFAULT 0.0,
    stock_quantity INTEGER DEFAULT 0 NOT NULL,
    reorder_level INTEGER DEFAULT 10 NOT NULL,
    requires_prescription BOOLEAN NOT NULL,
    is_controlled_substance BOOLEAN DEFAULT FALSE,
    schedule_type VARCHAR(50),
    storage_conditions VARCHAR(200),
    expiry_date DATE NOT NULL,
    batch_number VARCHAR(100) NOT NULL,
    medicine_image_url VARCHAR(500),
    is_available BOOLEAN DEFAULT TRUE,
    alternative_medicines_ids JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_medicines_pharmacy ON medicines(pharmacy_id);
CREATE INDEX IF NOT EXISTS idx_medicines_name ON medicines(name);
CREATE INDEX IF NOT EXISTS idx_medicines_category ON medicines(category);
CREATE INDEX IF NOT EXISTS idx_medicines_stock ON medicines(stock_quantity);
CREATE INDEX IF NOT EXISTS idx_medicines_expiry ON medicines(expiry_date);

-- Stock entries table
CREATE TABLE IF NOT EXISTS stock_entries (
    id SERIAL PRIMARY KEY,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE CASCADE,
    pharmacy_id INTEGER NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    entry_type VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    reference_id VARCHAR(50),
    batch_number VARCHAR(100),
    expiry_date DATE,
    supplier_name VARCHAR(100),
    purchase_price_per_unit FLOAT,
    invoice_number VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_entries_medicine ON stock_entries(medicine_id);
CREATE INDEX IF NOT EXISTS idx_stock_entries_pharmacy ON stock_entries(pharmacy_id);
CREATE INDEX IF NOT EXISTS idx_stock_entries_type ON stock_entries(entry_type);

-- Prescriptions table
CREATE TABLE IF NOT EXISTS prescriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    doctor_name VARCHAR(100),
    issue_date DATE,
    image_url VARCHAR(500) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_prescriptions_user ON prescriptions(user_id);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pharmacy_id INTEGER NOT NULL REFERENCES pharmacies(id) ON DELETE CASCADE,
    total_amount FLOAT NOT NULL,
    order_status VARCHAR(50) DEFAULT 'Pending' NOT NULL,
    payment_status VARCHAR(50) DEFAULT 'Pending',
    delivery_address TEXT NOT NULL,
    contact_number VARCHAR(15) NOT NULL,
    prescription_id INTEGER REFERENCES prescriptions(id) ON DELETE SET NULL,
    tracking_number VARCHAR(100),
    estimated_delivery TIMESTAMP WITH TIME ZONE,
    delivered_at TIMESTAMP WITH TIME ZONE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_pharmacy ON orders(pharmacy_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);

-- Order items table
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL,
    price FLOAT NOT NULL,
    CONSTRAINT check_quantity_positive CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_medicine ON order_items(medicine_id);

-- Audit logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50),
    entity_id VARCHAR(50),
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);

-- Notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(is_read);

-- Success message
DO $$
BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '================================================';
    RAISE NOTICE '✅ PHARMACY VENDOR SCHEMA CREATED!';
    RAISE NOTICE '================================================';
    RAISE NOTICE '📊 Tables created:';
    RAISE NOTICE '   - users';
    RAISE NOTICE '   - pharmacies';
    RAISE NOTICE '   - medicines';
    RAISE NOTICE '   - stock_entries';
    RAISE NOTICE '   - orders';
    RAISE NOTICE '   - order_items';
    RAISE NOTICE '   - prescriptions';
    RAISE NOTICE '   - audit_logs';
    RAISE NOTICE '   - notifications';
    RAISE NOTICE '🔧 Indexes created for performance';
    RAISE NOTICE '🔗 Foreign keys with CASCADE configured';
    RAISE NOTICE '================================================';
END $$;