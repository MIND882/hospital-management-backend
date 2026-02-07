
"""
Smart database setup - clears old data automatically
"""

from database.connection import engine, Base, SessionLocal
from database.models import *
from datetime import datetime, date, time, timedelta

def clear_all_data(db):
    """Clear all existing data"""
    print("🗑️ Clearing existing data...")
    
    try:
        # Delete in order
        db.query(LabBooking).delete()
        db.query(OrderItem).delete()
        db.query(Order).delete()
        db.query(Appointment).delete()
        db.query(DoctorSlot).delete()
        db.query(EmergencyRequest).delete()
        db.query(Prescription).delete()
        db.query(Notification).delete()
        db.query(AuditLog).delete()
        db.query(Medicine).delete()
        db.query(LabTest).delete()
        db.query(Doctor).delete()
        db.query(Clinic).delete()
        db.query(User).delete()
        
        db.commit()
        print("✅ All data cleared!")
        
    except Exception as e:
        print(f"⚠️ Error clearing data: {e}")
        db.rollback()

def setup_complete_database():
    print("🚀 Starting complete database setup...")
    print("="*60)
    
    # Step 1: Create tables
    print("\n📦 STEP 1: Creating tables...")
    try:
        Base.metadata.create_all(bind=engine)
        
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        print(f"✅ {len(tables)} tables ready")
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False
    
    # Step 2: Clear old data
    db = SessionLocal()
    
    # Check if data exists
    existing_clinics = db.query(Clinic).count()
    if existing_clinics > 0:
        print(f"\n⚠️ Found {existing_clinics} existing clinics")
        clear_all_data(db)
    
    # Step 3: Seed fresh data
    print("\n🌱 STEP 2: Inserting fresh data...")
    
    try:
        # ==================== USERS ====================
        print("   → Creating users...")
        users = [
            User(
                phone="+919876543210",
                name="Rahul Kumar",
                age=28,
                gender="male",
                blood_group="O+",
                location_lat=19.1136,
                location_lng=72.8697,
                insurance_provider="ICICI Lombard",
                is_verified=True
            ),
            User(
                phone="+919876543211",
                name="Priya Sharma",
                age=32,
                gender="female",
                blood_group="A+",
                location_lat=19.0760,
                location_lng=72.8777,
                insurance_provider="Star Health",
                is_verified=True
            ),
            User(
                phone="+919876543212",
                name="Ankit Patel",
                age=45,
                gender="male",
                blood_group="B+",
                is_verified=True
            )
        ]
        
        for user in users:
            db.add(user)
        db.commit()
        print(f"      ✓ {len(users)} users created")
        
        # ==================== CLINICS ====================
        print("   → Creating clinics...")
        clinics = [
            Clinic(
                id="CLI001",
                name="Apollo Hospital",
                address="123 Main Road, Andheri West, Mumbai - 400058",
                location_lat=19.1197,
                location_lng=72.8464,
                phone="+91-22-26735000",
                emergency_available=True,
                ambulance_available=True,
                insurance_accepted=["ICICI Lombard", "Star Health", "Max Bupa"],
                rating=4.5,
                total_reviews=230
            ),
            Clinic(
                id="CLI002",
                name="Fortis Hospital",
                address="Bandra, Mumbai - 400050",
                location_lat=19.0596,
                location_lng=72.8295,
                phone="+91-22-66754444",
                emergency_available=True,
                ambulance_available=True,
                insurance_accepted=["Max Bupa", "Cigna"],
                rating=4.6,
                total_reviews=180
            ),
            Clinic(
                id="CLI003",
                name="Lilavati Hospital",
                address="Bandra West, Mumbai - 400050",
                location_lat=19.0544,
                location_lng=72.8185,
                phone="+91-22-26567891",
                emergency_available=True,
                ambulance_available=True,
                insurance_accepted=["ICICI Lombard", "Star Health"],
                rating=4.7,
                total_reviews=340
            )
        ]
        
        for clinic in clinics:
            db.add(clinic)
        db.commit()
        print(f"      ✓ {len(clinics)} clinics created")
        
        # ==================== DOCTORS ====================
        print("   → Creating doctors...")
        doctors = [
            Doctor(
                clinic_id="CLI001",
                name="Dr. Rajesh Sharma",
                specialties=["Orthopedic", "Sports Medicine"],
                qualification="MBBS, MS (Ortho)",
                experience_years=15,
                consultation_fee=800,
                rating=4.8,
                total_consultations=230,
                is_available=True,
                next_available_slot=datetime.now() + timedelta(hours=2)
            ),
            Doctor(
                clinic_id="CLI001",
                name="Dr. Meera Reddy",
                specialties=["Cardiologist"],
                qualification="MBBS, MD (Cardio)",
                experience_years=20,
                consultation_fee=1200,
                rating=4.9,
                total_consultations=340,
                is_available=True,
                next_available_slot=datetime.now() + timedelta(hours=3)
            ),
            Doctor(
                clinic_id="CLI002",
                name="Dr. Amit Desai",
                specialties=["General Physician"],
                qualification="MBBS, MD",
                experience_years=10,
                consultation_fee=500,
                rating=4.5,
                total_consultations=180,
                is_available=True,
                next_available_slot=datetime.now() + timedelta(hours=1)
            ),
            Doctor(
                clinic_id="CLI002",
                name="Dr. Priya Mehta",
                specialties=["Orthopedic"],
                qualification="MBBS, MS (Ortho)",
                experience_years=12,
                consultation_fee=700,
                rating=4.6,
                total_consultations=200,
                is_available=True,
                next_available_slot=datetime.now() + timedelta(hours=4)
            ),
            Doctor(
                clinic_id="CLI003",
                name="Dr. Vikram Singh",
                specialties=["Cardiologist"],
                qualification="MBBS, DM (Cardio)",
                experience_years=25,
                consultation_fee=1500,
                rating=4.9,
                total_consultations=450,
                is_available=True,
                next_available_slot=datetime.now() + timedelta(hours=2)
            )
        ]
        
        created_doctors = []
        for doctor in doctors:
            db.add(doctor)
            db.flush()
            created_doctors.append(doctor)
        db.commit()
        print(f"      ✓ {len(doctors)} doctors created")
        
        # ==================== DOCTOR SLOTS ====================
        print("   → Creating doctor slots...")
        slots_created = 0
        today = date.today()
        
        for doctor in created_doctors:
            # Create slots for next 7 days
            for day_offset in range(7):
                slot_date = today + timedelta(days=day_offset)
                
                # Morning slots (9 AM - 12 PM)
                for hour in range(9, 12):
                    for minute in [0, 30]:
                        slot = DoctorSlot(
                            doctor_id=doctor.id,
                            date=slot_date,
                            start_time=time(hour, minute),
                            end_time=time(hour, minute + 30) if minute == 0 else time(hour + 1, 0),
                            is_booked=False
                        )
                        db.add(slot)
                        slots_created += 1
                
                # Afternoon slots (2 PM - 5 PM)
                for hour in range(14, 17):
                    for minute in [0, 30]:
                        slot = DoctorSlot(
                            doctor_id=doctor.id,
                            date=slot_date,
                            start_time=time(hour, minute),
                            end_time=time(hour, minute + 30) if minute == 0 else time(hour + 1, 0),
                            is_booked=False
                        )
                        db.add(slot)
                        slots_created += 1
        
        db.commit()
        print(f"      ✓ {slots_created} doctor slots created")
        
        # ==================== LAB TESTS ====================
        print("   → Creating lab tests...")
        lab_tests = [
            LabTest(
                name="Complete Blood Count (CBC)",
                description="Measures different components of blood",
                price=300,
                result_time_hours=6,
                home_collection_available=True,
                fasting_required=False
            ),
            LabTest(
                name="Lipid Profile",
                description="Checks cholesterol levels",
                price=600,
                result_time_hours=12,
                home_collection_available=True,
                fasting_required=True
            ),
            LabTest(
                name="Thyroid Panel (T3, T4, TSH)",
                description="Checks thyroid function",
                price=500,
                result_time_hours=24,
                home_collection_available=True,
                fasting_required=False
            ),
            LabTest(
                name="Vitamin D Test",
                description="Measures Vitamin D levels",
                price=800,
                result_time_hours=48,
                home_collection_available=True,
                fasting_required=False
            ),
            LabTest(
                name="HbA1c (Diabetes)",
                description="3-month average blood sugar",
                price=400,
                result_time_hours=12,
                home_collection_available=True,
                fasting_required=True
            )
        ]
        
        for test in lab_tests:
            db.add(test)
        db.commit()
        print(f"      ✓ {len(lab_tests)} lab tests created")
        
        # ==================== MEDICINES ====================
        print("   → Creating medicines...")
        medicines = [
            Medicine(
                name="Paracetamol 500mg",
                generic_name="Acetaminophen",
                category="Pain Relief",
                dosage="500mg",
                manufacturer="Cipla",
                price=20,
                stock_quantity=500,
                requires_prescription=False
            ),
            Medicine(
                name="Amoxicillin 250mg",
                generic_name="Amoxicillin",
                category="Antibiotic",
                dosage="250mg",
                manufacturer="Sun Pharma",
                price=120,
                stock_quantity=200,
                requires_prescription=True
            ),
            Medicine(
                name="Cetirizine 10mg",
                generic_name="Cetirizine",
                category="Allergy",
                dosage="10mg",
                manufacturer="Dr. Reddy's",
                price=40,
                stock_quantity=300,
                requires_prescription=False
            ),
            Medicine(
                name="Omeprazole 20mg",
                generic_name="Omeprazole",
                category="Antacid",
                dosage="20mg",
                manufacturer="Lupin",
                price=80,
                stock_quantity=150,
                requires_prescription=False
            )
        ]
        
        for medicine in medicines:
            db.add(medicine)
        db.commit()
        print(f"      ✓ {len(medicines)} medicines created")
        
        # ==================== SUMMARY ====================
        print("\n" + "="*60)
        print("✅ DATABASE SETUP COMPLETE!")
        print("="*60)
        print(f"\n📊 Summary:")
        print(f"   👤 Users: {db.query(User).count()}")
        print(f"   🏥 Clinics: {db.query(Clinic).count()}")
        print(f"   👨‍⚕️ Doctors: {db.query(Doctor).count()}")
        print(f"   📅 Doctor Slots: {db.query(DoctorSlot).count()}")
        print(f"   🔬 Lab Tests: {db.query(LabTest).count()}")
        print(f"   💊 Medicines: {db.query(Medicine).count()}")
        
        print("\n🎉 You can now start using the API!")
        print("\n📝 Next steps:")
        print("   1. Start server: python main.py")
        print("   2. Test auth: curl -X POST http://localhost:8000/api/auth/send-otp ...")
        print("   3. API docs: http://localhost:8000/docs")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = setup_complete_database()
    if not success:
        print("\n❌ Setup failed. Check errors above.")