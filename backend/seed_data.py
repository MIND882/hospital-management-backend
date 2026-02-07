# backend/seed_data.py
from database.connection import SessionLocal
from database.models import *
from datetime import datetime, date, time, timedelta
import random

db = SessionLocal()

def seed_data():
    print("🌱 Starting database seeding...")
    
    try:
        # Check if data already exists
        existing_users = db.query(User).count()
        if existing_users > 0:
            print(f"⚠️ Database already has {existing_users} users. Skipping seeding.")
            response = input("Do you want to clear and re-seed? (yes/no): ")
            if response.lower() != 'yes':
                return
            
            # Clear all data
            print("🗑️ Clearing existing data...")
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
            print("✅ All existing data cleared!")
        
        # ==================== USERS ====================
        print("\n👤 Creating users...")
        
        users_data = [
            {
                "phone": "+919876543210",
                "name": "Rahul Kumar",
                "age": 28,
                "gender": "male",
                "blood_group": "O+",
                "location_lat": 19.1136,
                "location_lng": 72.8697,
                "insurance_provider": "ICICI Lombard",
                "is_verified": True
            },
            {
                "phone": "+919876543211",
                "name": "Priya Sharma",
                "age": 32,
                "gender": "female",
                "blood_group": "A+",
                "location_lat": 19.0760,
                "location_lng": 72.8777,
                "insurance_provider": "Star Health",
                "is_verified": True
            },
            {
                "phone": "+919876543212",
                "name": "Ankit Patel",
                "age": 45,
                "gender": "male",
                "blood_group": "B+",
                "location_lat": 19.1197,
                "location_lng": 72.9081,
                "insurance_provider": "Max Bupa",
                "is_verified": True
            }
        ]
        
        for user_data in users_data:
            user = User(**user_data)
            db.add(user)
        
        db.commit()
        print(f"✅ Created {len(users_data)} users")
        
        # ==================== CLINICS ====================
        print("\n🏥 Creating clinics...")
        
        clinics_data = [
            {
                "id": "CLI001",
                "name": "Apollo Hospital",
                "address": "123 Main Road, Andheri West, Mumbai - 400058",
                "location_lat": 19.1197,
                "location_lng": 72.8464,
                "phone": "+91-22-26735000",
                "email": "info@apollo.com",
                "emergency_available": True,
                "ambulance_available": True,
                "insurance_accepted": ["ICICI Lombard", "Star Health", "Max Bupa"],
                "rating": 4.5,
                "total_reviews": 230,
                "working_hours": {
                    "monday": "09:00-21:00",
                    "tuesday": "09:00-21:00",
                    "wednesday": "09:00-21:00",
                    "thursday": "09:00-21:00",
                    "friday": "09:00-21:00",
                    "saturday": "09:00-18:00",
                    "sunday": "10:00-16:00"
                }
            },
            {
                "id": "CLI002",
                "name": "Fortis Hospital",
                "address": "Mulund-Goregaon Link Road, Bandra, Mumbai - 400050",
                "location_lat": 19.0596,
                "location_lng": 72.8295,
                "phone": "+91-22-66754444",
                "email": "contact@fortis.com",
                "emergency_available": True,
                "ambulance_available": True,
                "insurance_accepted": ["Max Bupa", "Cigna", "HDFC Ergo"],
                "rating": 4.6,
                "total_reviews": 180,
                "working_hours": {
                    "monday": "08:00-20:00",
                    "tuesday": "08:00-20:00",
                    "wednesday": "08:00-20:00",
                    "thursday": "08:00-20:00",
                    "friday": "08:00-20:00",
                    "saturday": "08:00-18:00",
                    "sunday": "09:00-17:00"
                }
            }
        ]
        
        for clinic_data in clinics_data:
            clinic = Clinic(**clinic_data)
            db.add(clinic)
        
        db.commit()
        print(f"✅ Created {len(clinics_data)} clinics")
        
        # ==================== DOCTORS ====================
        print("\n👨‍⚕️ Creating doctors...")
        
        doctors_data = [
            {
                "clinic_id": "CLI001",
                "name": "Dr. Rajesh Sharma",
                "specialties": ["Orthopedic", "Sports Medicine"],
                "qualification": "MBBS, MS (Ortho)",
                "experience_years": 15,
                "consultation_fee": 800,
                "rating": 4.8,
                "total_consultations": 230,
                "is_available": True,
                "next_available_slot": datetime.now() + timedelta(hours=2)
            },
            {
                "clinic_id": "CLI001",
                "name": "Dr. Meera Reddy",
                "specialties": ["Cardiologist"],
                "qualification": "MBBS, MD (Cardio)",
                "experience_years": 20,
                "consultation_fee": 1200,
                "rating": 4.9,
                "total_consultations": 340,
                "is_available": True,
                "next_available_slot": datetime.now() + timedelta(hours=3)
            },
            {
                "clinic_id": "CLI002",
                "name": "Dr. Amit Desai",
                "specialties": ["General Physician"],
                "qualification": "MBBS, MD",
                "experience_years": 10,
                "consultation_fee": 500,
                "rating": 4.5,
                "total_consultations": 180,
                "is_available": True,
                "next_available_slot": datetime.now() + timedelta(hours=1)
            }
        ]
        
        created_doctors = []
        for doc_data in doctors_data:
            doctor = Doctor(**doc_data)
            db.add(doctor)
            db.flush()
            created_doctors.append(doctor)
        
        db.commit()
        print(f"✅ Created {len(doctors_data)} doctors")
        
        # ==================== DOCTOR SLOTS ====================
        print("\n📅 Creating doctor slots...")
        
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
        print(f"✅ Created {slots_created} doctor slots")
        
        # ==================== LAB TESTS ====================
        print("\n🔬 Creating lab tests...")
        
        lab_tests_data = [
            {
                "name": "Complete Blood Count (CBC)",
                "description": "Measures different components of blood",
                "price": 300,
                "result_time_hours": 6,
                "home_collection_available": True,
                "fasting_required": False
            },
            {
                "name": "Lipid Profile",
                "description": "Checks cholesterol levels",
                "price": 600,
                "result_time_hours": 12,
                "home_collection_available": True,
                "fasting_required": True
            },
            {
                "name": "Thyroid Panel (T3, T4, TSH)",
                "description": "Checks thyroid function",
                "price": 500,
                "result_time_hours": 24,
                "home_collection_available": True,
                "fasting_required": False
            },
            {
                "name": "Vitamin D Test",
                "description": "Measures Vitamin D levels",
                "price": 800,
                "result_time_hours": 48,
                "home_collection_available": True,
                "fasting_required": False
            },
            {
                "name": "HbA1c (Diabetes)",
                "description": "3-month average blood sugar",
                "price": 400,
                "result_time_hours": 12,
                "home_collection_available": True,
                "fasting_required": True
            }
        ]
        
        for test_data in lab_tests_data:
            lab_test = LabTest(**test_data)
            db.add(lab_test)
        
        db.commit()
        print(f"✅ Created {len(lab_tests_data)} lab tests")
        
        # ==================== MEDICINES ====================
        print("\n💊 Creating medicines...")
        
        medicines_data = [
            {
                "name": "Paracetamol 500mg",
                "generic_name": "Acetaminophen",
                "category": "Pain Relief",
                "dosage": "500mg",
                "manufacturer": "Cipla",
                "price": 20,
                "stock_quantity": 500,
                "requires_prescription": False,
                "alternatives": []
            },
            {
                "name": "Amoxicillin 250mg",
                "generic_name": "Amoxicillin",
                "category": "Antibiotic",
                "dosage": "250mg",
                "manufacturer": "Sun Pharma",
                "price": 120,
                "stock_quantity": 200,
                "requires_prescription": True,
                "alternatives": []
            },
            {
                "name": "Cetirizine 10mg",
                "generic_name": "Cetirizine",
                "category": "Allergy",
                "dosage": "10mg",
                "manufacturer": "Dr. Reddy's",
                "price": 40,
                "stock_quantity": 300,
                "requires_prescription": False,
                "alternatives": []
            }
        ]
        
        for med_data in medicines_data:
            medicine = Medicine(**med_data)
            db.add(medicine)
        
        db.commit()
        print(f"✅ Created {len(medicines_data)} medicines")
        
        print("\n" + "="*50)
        print("🎉 Database seeding completed successfully!")
        print("="*50)
        print(f"\n📊 Summary:")
        print(f"   Users: {len(users_data)}")
        print(f"   Clinics: {len(clinics_data)}")
        print(f"   Doctors: {len(doctors_data)}")
        print(f"   Doctor Slots: {slots_created}")
        print(f"   Lab Tests: {len(lab_tests_data)}")
        print(f"   Medicines: {len(medicines_data)}")
        
    except Exception as e:
        print(f"\n❌ Error during seeding: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    seed_data()