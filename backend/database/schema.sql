-- ==================== USERS ====================

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    phone VARCHAR(15) UNIQUE NOT NULL,
    name VARCHAR(100),
    email VARCHAR(100),
    age INTEGER,
    gender VARCHAR(10), -- 'male', 'female', 'other'
    blood_group VARCHAR(5), -- 'A+', 'B-', etc.
    address TEXT,
    location_lat DECIMAL(10, 8),
    location_lng DECIMAL(11, 8),
    insurance_provider VARCHAR(50), -- 'ICICI', 'Star Health', etc.
    insurance_number VARCHAR(50),
    allergies JSONB, -- ["Penicillin", "Peanuts"]
    otp VARCHAR(6),
    otp_expires_at TIMESTAMP,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_phone ON users(phone);

-- ==================== CLINICS & DOCTORS ====================

CREATE TABLE clinics (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    address TEXT NOT NULL,
    location_lat DECIMAL(10, 8) NOT NULL,
    location_lng DECIMAL(11, 8) NOT NULL,
    phone VARCHAR(15),
    email VARCHAR(100),
    working_hours JSONB, -- {"monday": "09:00-17:00", ...}
    emergency_available BOOLEAN DEFAULT FALSE,
    ambulance_available BOOLEAN DEFAULT FALSE,
    insurance_accepted JSONB, -- ["ICICI", "Star Health", "Max Bupa"]
    rating DECIMAL(3, 2) DEFAULT 0.0,
    total_reviews INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_clinics_location ON clinics(location_lat, location_lng);

CREATE TABLE doctors (
    id SERIAL PRIMARY KEY,
    clinic_id VARCHAR(50) REFERENCES clinics(id),
    name VARCHAR(100) NOT NULL,
    specialties JSONB NOT NULL, -- ["Orthopedic", "Sports Medicine"]
    qualification VARCHAR(100), -- "MBBS, MD"
    experience_years INTEGER,
    consultation_fee FLOAT NOT NULL,
    rating DECIMAL(3, 2) DEFAULT 0.0,
    total_consultations INTEGER DEFAULT 0,
    is_available BOOLEAN DEFAULT TRUE,
    next_available_slot TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_doctors_specialty ON doctors USING GIN(specialties);
CREATE INDEX idx_doctors_clinic ON doctors(clinic_id);

CREATE TABLE doctor_slots (
    id SERIAL PRIMARY KEY,
    doctor_id INTEGER REFERENCES doctors(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    is_booked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doctor_id, date, start_time)
);

CREATE INDEX idx_slots_doctor_date ON doctor_slots(doctor_id, date, is_booked);

-- ==================== APPOINTMENTS ====================

CREATE TABLE appointments (
    id VARCHAR(20) PRIMARY KEY, -- APT123456
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES doctors(id),
    slot_id INTEGER REFERENCES doctor_slots(id),
    
    date DATE NOT NULL,
    time TIME NOT NULL,
    reason TEXT,
    symptoms JSONB, -- ["Pain", "Fever", "Swelling"]
    
    status VARCHAR(20) DEFAULT 'confirmed', -- 'pending', 'confirmed', 'completed', 'cancelled'
    is_emergency BOOLEAN DEFAULT FALSE,
    consultation_type VARCHAR(20) DEFAULT 'in-person', -- 'in-person', 'video', 'phone'
    
    cancellation_reason VARCHAR(100),
    cancelled_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_appointments_user ON appointments(user_id);
CREATE INDEX idx_appointments_doctor ON appointments(doctor_id);
CREATE INDEX idx_appointments_date ON appointments(date, status);

-- ==================== EMERGENCY ====================

CREATE TABLE emergency_requests (
    id VARCHAR(20) PRIMARY KEY, -- EMG123456
    user_id INTEGER REFERENCES users(id),
    
    location_lat DECIMAL(10, 8) NOT NULL,
    location_lng DECIMAL(11, 8) NOT NULL,
    address TEXT,
    
    emergency_type VARCHAR(20) NOT NULL, -- 'ambulance', 'hospital'
    description TEXT,
    
    assigned_clinic_id VARCHAR(50) REFERENCES clinics(id),
    ambulance_eta INTEGER, -- minutes
    
    status VARCHAR(20) DEFAULT 'requested', -- 'requested', 'dispatched', 'arrived', 'completed'
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_emergency_status ON emergency_requests(status, created_at);

-- ==================== PHARMACY ====================

CREATE TABLE medicines (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    generic_name VARCHAR(200),
    category VARCHAR(50), -- 'Pain Relief', 'Antibiotic', 'Allergy'
    dosage VARCHAR(50), -- '500mg', '10mg'
    manufacturer VARCHAR(100),
    price INTEGER NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    requires_prescription BOOLEAN DEFAULT FALSE,
    alternatives JSONB, -- [{"id": 123, "name": "Alternative Med"}]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_medicines_name ON medicines(name);
CREATE INDEX idx_medicines_category ON medicines(category);

CREATE TABLE prescriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    appointment_id VARCHAR(20) REFERENCES appointments(id)UNIQUE,
    doctor_id INTEGER REFERENCES doctors(id),
    
    medicines JSONB, -- [{"name": "Paracetamol", "dosage": "500mg", "frequency": "3 times/day", "duration": "5 days"}]
    instructions TEXT,
    valid_until DATE,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_prescriptions_user ON prescriptions(user_id);

CREATE TABLE orders (
    id VARCHAR(20) PRIMARY KEY, -- ORD123456
    user_id INTEGER REFERENCES users(id),
    
    total_amount INTEGER NOT NULL,
    delivery_address TEXT NOT NULL,
    delivery_type VARCHAR(20) DEFAULT '2-hour', -- '2-hour', 'standard'
    payment_status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'paid', 'failed'
    order_status VARCHAR(20) DEFAULT 'processing', -- 'processing', 'shipped', 'delivered', 'cancelled'
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP
);

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(20) REFERENCES orders(id) ON DELETE CASCADE,
    medicine_id INTEGER REFERENCES medicines(id),
    
    quantity INTEGER NOT NULL,
    price INTEGER NOT NULL
);

-- ==================== LAB TESTS ====================

CREATE TABLE lab_tests (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    price INTEGER NOT NULL,
    result_time_hours INTEGER NOT NULL, -- 6, 12, 24, 48
    home_collection_available BOOLEAN DEFAULT TRUE,
    fasting_required BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE lab_bookings (
    id VARCHAR(20) PRIMARY KEY, -- LAB123456
    user_id INTEGER REFERENCES users(id),
    test_id INTEGER REFERENCES lab_tests(id),
    
    collection_type VARCHAR(20) DEFAULT 'home', -- 'home', 'lab'
    collection_date DATE NOT NULL,
    collection_time TIME NOT NULL,
    address TEXT,
    
    status VARCHAR(20) DEFAULT 'scheduled', -- 'scheduled', 'collected', 'processing', 'completed'
    result_pdf_url TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- ==================== NOTIFICATIONS ====================

CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    type VARCHAR(50), -- 'appointment_reminder', 'appointment_confirmed', etc.
    title VARCHAR(200),
    message TEXT,
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notifications_user ON notifications(user_id, is_read);

-- ==================== AUDIT LOG ====================

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    action VARCHAR(100), -- 'APPOINTMENT_BOOKED', 'APPOINTMENT_CANCELLED', etc.
    entity_type VARCHAR(50), -- 'appointment', 'order', 'emergency'
    entity_id VARCHAR(50),
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, created_at);