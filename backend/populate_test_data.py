#!/usr/bin/env python3
"""
Comprehensive test data population script for SmartHandoff.
Connects to localhost via Cloud SQL proxy and populates all tables with realistic test data.
"""

import asyncio
import sys
import uuid
import random
from datetime import datetime, timedelta
from typing import List
import logging

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Add backend to path
sys.path.insert(0, str(__file__).rsplit("\\", 1)[0])

from app.models import (
    Patient, Encounter, EncounterStatus, RiskTier,
    AppUser, Bed, Medication, Document, AgentTask,
    Appointment, AppointmentStatus, AppointmentType,
    ScheduledNotification, NotificationType, NotificationChannel, DeliveryStatus,
    CareEscalation, CareEscalationStatus,
    AuditLog, AuditAction,
    ChatbotTranscript,
    PharmacistAlert,
    AdtEvent
)
from app.db.base import Base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database URL for localhost with Cloud SQL proxy (password @ encoded as %40)
DATABASE_URL = "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"

class TestDataPopulator:
    """Handles database connection and test data population."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.engine = None
        self.async_session = None
    
    async def connect(self) -> bool:
        """Establish database connection."""
        try:
            logger.info(f"🔌 Connecting to database: {self.db_url}")
            self.engine = create_async_engine(
                self.db_url,
                echo=False,
                pool_size=10,
                max_overflow=20,
            )
            
            # Test connection
            async with self.engine.begin() as conn:
                result = await conn.execute(text("SELECT 1"))
                logger.info("✅ Database connection successful!")
            
            self.async_session = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            return True
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
    
    async def check_tables(self) -> dict:
        """Check which tables exist in the database."""
        try:
            async with self.engine.begin() as conn:
                result = await conn.execute(
                    text("""
                    SELECT tablename FROM pg_tables 
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                    """)
                )
                tables = [row[0] for row in result.fetchall()]
            
            logger.info(f"\n📊 Found {len(tables)} tables:")
            for table in sorted(tables):
                logger.info(f"   • {table}")
            
            return {table: True for table in tables}
        except Exception as e:
            logger.error(f"❌ Error checking tables: {e}")
            return {}
    
    async def clear_all_data(self):
        """Clear all data from tables (for fresh start)."""
        async with self.async_session() as session:
            try:
                tables = [
                    'audit_log', 'pharmacist_alert', 'chatbot_transcript',
                    'care_escalation', 'scheduled_notification',
                    'appointment', 'agent_task', 'document', 'medication',
                    'adt_event', 'bed', 'encounter', 'app_user', 'patient'
                ]
                
                for table in tables:
                    try:
                        await session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                        logger.info(f"   ✓ Cleared {table}")
                    except Exception as e:
                        logger.warning(f"   ⚠ Could not clear {table}: {e}")
                
                await session.commit()
                logger.info("✅ All tables cleared")
            except Exception as e:
                logger.error(f"❌ Error clearing data: {e}")
                await session.rollback()
    
    async def populate_users(self) -> List[AppUser]:
        """Create test users."""
        async with self.async_session() as session:
            try:
                users = [
                    AppUser(
                        id=uuid.uuid4(),
                        email="nurse@smarthandoff.local",
                        name="Jane Nurse",
                        role="RN",
                        unit="ICU",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    AppUser(
                        id=uuid.uuid4(),
                        email="doctor@smarthandoff.local",
                        name="Dr. John Smith",
                        role="MD",
                        unit="ICU",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    AppUser(
                        id=uuid.uuid4(),
                        email="pharmacist@smarthandoff.local",
                        name="Bob Pharmacist",
                        role="RPh",
                        unit="Pharmacy",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    AppUser(
                        id=uuid.uuid4(),
                        email="admin@smarthandoff.local",
                        name="Alice Admin",
                        role="ADMIN",
                        unit="Administration",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                ]
                
                session.add_all(users)
                await session.commit()
                logger.info(f"✅ Created {len(users)} users")
                return users
            except Exception as e:
                logger.error(f"❌ Error creating users: {e}")
                await session.rollback()
                return []
    
    async def populate_patients(self) -> List[Patient]:
        """Create 100+ realistic test patients with diverse demographics."""
        async with self.async_session() as session:
            try:
                first_names = [
                    "John", "Jane", "Robert", "Mary", "Michael", "Patricia", "James", "Linda",
                    "William", "Barbara", "David", "Elizabeth", "Richard", "Jennifer", "Joseph", "Maria",
                    "Thomas", "Susan", "Charles", "Jessica", "Christopher", "Sarah", "Daniel", "Karen",
                    "Matthew", "Nancy", "Anthony", "Lisa", "Donald", "Betty", "Steven", "Margaret",
                    "Paul", "Sandra", "Andrew", "Ashley", "Joshua", "Kimberly", "Kenneth", "Emily",
                    "Kevin", "Donna", "Brian", "Michelle", "George", "Dorothy", "Edward", "Carol",
                    "Ronald", "Amanda", "Timothy", "Melissa", "Jason", "Deborah", "Jeffrey", "Stephanie",
                    "Ryan", "Rebecca", "Jacob", "Sharon", "Gary", "Laura", "Nicholas", "Cynthia",
                    "Eric", "Kathleen", "Jonathan", "Amy", "Stephen", "Angela", "Larry", "Shirley",
                    "Justin", "Angela", "Scott", "Helen", "Brandon", "Anna", "Benjamin", "Brenda",
                    "Samuel", "Pamela", "Frank", "Nicole", "Gregory", "Emma", "Alexander", "Helen",
                    "Raymond", "Diane", "Patrick", "Julie", "Jack", "Joyce", "Dennis", "Victoria",
                    "Jerry", "Olivia", "Tyler", "Kelly", "Aaron", "Christina", "Jose", "Lauren",
                ]
                last_names = [
                    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
                    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
                    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Young",
                    "Allen", "King", "Wright", "Scott", "Torres", "Peterson", "Phillips", "Campbell",
                    "Parker", "Evans", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
                    "Kennedy", "Murphy", "Rogers", "Morgan", "Peterson", "Cooper", "Reed", "Bell",
                    "Gomez", "Munoz", "Medina", "Aguilar", "Vega", "Guerrero", "Soto", "Pena",
                    "Beck", "Newman", "Haynes", "McDaniel", "Mendoza", "Bush", "Vaughn", "Parks",
                    "Dawson", "Santiago", "Norris", "Hardy", "Love", "Steele", "Curry", "Powers",
                ]
                
                patients = []
                for i in range(100):
                    mrn_number = str(1000 + i).zfill(5)
                    patient = Patient(
                        id=uuid.uuid4(),
                        mrn_encrypted=mrn_number,
                        first_name=first_names[i % len(first_names)],
                        last_name=last_names[i % len(last_names)],
                        date_of_birth=(datetime.now() - timedelta(days=365*random.randint(25, 85))).strftime("%Y-%m-%d"),
                        created_at=datetime.now() - timedelta(days=random.randint(1, 365)),
                        updated_at=datetime.now(),
                    )
                    patients.append(patient)
                
                session.add_all(patients)
                await session.commit()
                logger.info(f"✅ Created {len(patients)} patients with realistic demographics")
                return patients
            except Exception as e:
                logger.error(f"❌ Error creating patients: {e}")
                await session.rollback()
                return []
    
    async def populate_beds(self) -> List[Bed]:
        """Create test beds."""
        async with self.async_session() as session:
            try:
                beds = [
                    Bed(
                        id=uuid.uuid4(),
                        bed_number="ICU-101",
                        unit="ICU",
                        status="AVAILABLE",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    Bed(
                        id=uuid.uuid4(),
                        bed_number="ICU-102",
                        unit="ICU",
                        status="OCCUPIED",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    Bed(
                        id=uuid.uuid4(),
                        bed_number="ICU-103",
                        unit="ICU",
                        status="MAINTENANCE",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    Bed(
                        id=uuid.uuid4(),
                        bed_number="WARD-201",
                        unit="General",
                        status="AVAILABLE",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                    Bed(
                        id=uuid.uuid4(),
                        bed_number="WARD-202",
                        unit="General",
                        status="OCCUPIED",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    ),
                ]
                
                session.add_all(beds)
                await session.commit()
                logger.info(f"✅ Created {len(beds)} beds")
                return beds
            except Exception as e:
                logger.error(f"❌ Error creating beds: {e}")
                await session.rollback()
                return []
    
    async def populate_encounters(self, patients: List[Patient]) -> List[Encounter]:
        """Create encounters for patients (50-75% of patients get 1-3 encounters)."""
        async with self.async_session() as session:
            try:
                encounters = []
                statuses = [EncounterStatus.ADMITTED, EncounterStatus.TRANSFERRED, EncounterStatus.DISCHARGED]
                units = ["ICU", "CCU", "MED", "SURG", "PEDS", "OB", "ED"]
                risks = [RiskTier.HIGH, RiskTier.MEDIUM, RiskTier.LOW]
                
                # Create 1-3 encounters for ~70% of patients
                for patient in patients:
                    if random.random() < 0.7:  # 70% chance this patient has an encounter
                        num_encounters = random.randint(1, 3)
                        for enc_idx in range(num_encounters):
                            encounter = Encounter(
                                id=uuid.uuid4(),
                                patient_id=patient.id,
                                status=random.choice(statuses),
                                unit=random.choice(units),
                                risk_tier=random.choice(risks),
                                created_at=datetime.now() - timedelta(days=random.randint(1, 365), hours=random.randint(0, 23)),
                                updated_at=datetime.now(),
                            )
                            encounters.append(encounter)
                
                session.add_all(encounters)
                await session.commit()
                logger.info(f"✅ Created {len(encounters)} encounters across {len(patients)} patients")
                return encounters
            except Exception as e:
                logger.error(f"❌ Error creating encounters: {e}")
                await session.rollback()
                return []
    
    async def populate_medications(self, encounters: List[Encounter]) -> List[Medication]:
        """Create test medications."""
        async with self.async_session() as session:
            try:
                med_names = ["Lisinopril", "Metformin", "Aspirin", "Levothyroxine", "Atorvastatin"]
                medications = []
                
                for i, encounter in enumerate(encounters):
                    med = Medication(
                        id=uuid.uuid4(),
                        encounter_id=encounter.id,
                        medication_code=f"MED{str(uuid.uuid4())[:6]}",
                        medication_name=med_names[i % len(med_names)],
                        dose="500mg",
                        frequency="Twice daily",
                        route="Oral",
                        reconciliation_flag="REVIEWED",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    medications.append(med)
                
                session.add_all(medications)
                await session.commit()
                logger.info(f"✅ Created {len(medications)} medications")
                return medications
            except Exception as e:
                logger.error(f"❌ Error creating medications: {e}")
                await session.rollback()
                return []
    
    async def populate_documents(self, encounters: List[Encounter]) -> List[Document]:
        """Create test documents."""
        async with self.async_session() as session:
            try:
                doc_types = ["Discharge Summary", "Progress Notes", "Lab Results", "Imaging Report"]
                documents = []
                
                for i, encounter in enumerate(encounters):
                    doc = Document(
                        id=uuid.uuid4(),
                        encounter_id=encounter.id,
                        document_type=doc_types[i % len(doc_types)],
                        content="Sample clinical document content...",
                        created_by="System",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    documents.append(doc)
                
                session.add_all(documents)
                await session.commit()
                logger.info(f"✅ Created {len(documents)} documents")
                return documents
            except Exception as e:
                logger.error(f"❌ Error creating documents: {e}")
                await session.rollback()
                return []
    
    async def populate_agent_tasks(self, encounters: List[Encounter], users: List[AppUser]) -> List[AgentTask]:
        """Create test agent tasks."""
        async with self.async_session() as session:
            try:
                task_types = ["MEDICATION_RECONCILIATION", "DISCHARGE_SUMMARY", "FOLLOW_UP_CARE"]
                agent_tasks = []
                
                for i, encounter in enumerate(encounters):
                    task = AgentTask(
                        id=uuid.uuid4(),
                        encounter_id=encounter.id,
                        assigned_to=users[i % len(users)].id if users else None,
                        task_type=task_types[i % len(task_types)],
                        status="IN_PROGRESS" if i % 2 == 0 else "COMPLETED",
                        priority="HIGH",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    agent_tasks.append(task)
                
                session.add_all(agent_tasks)
                await session.commit()
                logger.info(f"✅ Created {len(agent_tasks)} agent tasks")
                return agent_tasks
            except Exception as e:
                logger.error(f"❌ Error creating agent tasks: {e}")
                await session.rollback()
                return []
    
    async def populate_appointments(self, patients: List[Patient]) -> List[Appointment]:
        """Create test appointments."""
        async with self.async_session() as session:
            try:
                appointments = []
                
                for i, patient in enumerate(patients[:2]):
                    appt = Appointment(
                        id=uuid.uuid4(),
                        patient_id=patient.id,
                        appointment_date=datetime.now() + timedelta(days=7+i),
                        appointment_type=AppointmentType.FOLLOW_UP,
                        status=AppointmentStatus.SCHEDULED,
                        location="Clinic A",
                        provider="Dr. Smith",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    appointments.append(appt)
                
                session.add_all(appointments)
                await session.commit()
                logger.info(f"✅ Created {len(appointments)} appointments")
                return appointments
            except Exception as e:
                logger.error(f"❌ Error creating appointments: {e}")
                await session.rollback()
                return []
    
    async def populate_notifications(self, patients: List[Patient]) -> List[ScheduledNotification]:
        """Create test notifications."""
        async with self.async_session() as session:
            try:
                notifications = []
                
                for i, patient in enumerate(patients[:2]):
                    notif = ScheduledNotification(
                        id=uuid.uuid4(),
                        patient_id=patient.id,
                        notification_type=NotificationType.APPOINTMENT_REMINDER,
                        channel=NotificationChannel.EMAIL,
                        scheduled_for=datetime.now() + timedelta(hours=24),
                        delivery_status=DeliveryStatus.SCHEDULED,
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    notifications.append(notif)
                
                session.add_all(notifications)
                await session.commit()
                logger.info(f"✅ Created {len(notifications)} notifications")
                return notifications
            except Exception as e:
                logger.error(f"❌ Error creating notifications: {e}")
                await session.rollback()
                return []
    
    async def populate_care_escalations(self, encounters: List[Encounter]) -> List[CareEscalation]:
        """Create test care escalations."""
        async with self.async_session() as session:
            try:
                escalations = []
                
                for i, encounter in enumerate(encounters):
                    esc = CareEscalation(
                        id=uuid.uuid4(),
                        encounter_id=encounter.id,
                        escalation_reason="High risk patient requiring additional monitoring",
                        escalation_level="LEVEL_2",
                        status=CareEscalationStatus.OPEN,
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    escalations.append(esc)
                
                session.add_all(escalations)
                await session.commit()
                logger.info(f"✅ Created {len(escalations)} care escalations")
                return escalations
            except Exception as e:
                logger.error(f"❌ Error creating care escalations: {e}")
                await session.rollback()
                return []
    
    async def populate_audit_logs(self, users: List[AppUser]) -> List[AuditLog]:
        """Create test audit logs."""
        async with self.async_session() as session:
            try:
                audit_logs = []
                
                for i in range(5):
                    log = AuditLog(
                        id=uuid.uuid4(),
                        actor_id=users[i % len(users)].id if users else None,
                        action=AuditAction.READ,
                        resource_type="Encounter",
                        resource_id=str(uuid.uuid4()),
                        details=f"Sample audit log entry {i+1}",
                        created_at=datetime.now() - timedelta(minutes=i*10),
                        updated_at=datetime.now(),
                    )
                    audit_logs.append(log)
                
                session.add_all(audit_logs)
                await session.commit()
                logger.info(f"✅ Created {len(audit_logs)} audit logs")
                return audit_logs
            except Exception as e:
                logger.error(f"❌ Error creating audit logs: {e}")
                await session.rollback()
                return []
    
    async def populate_chatbot_transcripts(self, patients: List[Patient]) -> List[ChatbotTranscript]:
        """Create test chatbot transcripts."""
        async with self.async_session() as session:
            try:
                transcripts = []
                
                for i, patient in enumerate(patients[:2]):
                    transcript = ChatbotTranscript(
                        id=uuid.uuid4(),
                        patient_id=patient.id,
                        messages=[
                            {"role": "bot", "content": "Hello, how can I assist you today?"},
                            {"role": "patient", "content": "I have a question about my medications."}
                        ],
                        session_duration=300,
                        created_at=datetime.now() - timedelta(hours=i),
                        updated_at=datetime.now(),
                    )
                    transcripts.append(transcript)
                
                session.add_all(transcripts)
                await session.commit()
                logger.info(f"✅ Created {len(transcripts)} chatbot transcripts")
                return transcripts
            except Exception as e:
                logger.error(f"❌ Error creating chatbot transcripts: {e}")
                await session.rollback()
                return []
    
    async def populate_pharmacist_alerts(self, encounters: List[Encounter]) -> List[PharmacistAlert]:
        """Create test pharmacist alerts."""
        async with self.async_session() as session:
            try:
                alerts = []
                
                for i, encounter in enumerate(encounters):
                    alert = PharmacistAlert(
                        id=uuid.uuid4(),
                        encounter_id=encounter.id,
                        alert_type="DRUG_INTERACTION",
                        severity="HIGH",
                        message="Potential drug interaction detected",
                        is_resolved=False,
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    alerts.append(alert)
                
                session.add_all(alerts)
                await session.commit()
                logger.info(f"✅ Created {len(alerts)} pharmacist alerts")
                return alerts
            except Exception as e:
                logger.error(f"❌ Error creating pharmacist alerts: {e}")
                await session.rollback()
                return []
    
    async def populate_adt_events(self, encounters: List[Encounter]) -> List[AdtEvent]:
        """Create test ADT events."""
        async with self.async_session() as session:
            try:
                events = []
                event_types = ["A01", "A02", "A03"]
                
                for i, encounter in enumerate(encounters):
                    event = AdtEvent(
                        id=uuid.uuid4(),
                        encounter_id=encounter.id,
                        event_type=event_types[i % len(event_types)],
                        event_timestamp=datetime.now() - timedelta(hours=i),
                        message_id=f"MSG{str(uuid.uuid4())[:8]}",
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    events.append(event)
                
                session.add_all(events)
                await session.commit()
                logger.info(f"✅ Created {len(events)} ADT events")
                return events
            except Exception as e:
                logger.error(f"❌ Error creating ADT events: {e}")
                await session.rollback()
                return []
    
    async def count_records(self) -> dict:
        """Count records in all tables."""
        try:
            counts = {}
            models = [
                ("patient", Patient),
                ("encounter", Encounter),
                ("app_user", AppUser),
                ("bed", Bed),
                ("medication", Medication),
                ("document", Document),
                ("agent_task", AgentTask),
                ("appointment", Appointment),
                ("scheduled_notification", ScheduledNotification),
                ("care_escalation", CareEscalation),
                ("audit_log", AuditLog),
                ("chatbot_transcript", ChatbotTranscript),
                ("pharmacist_alert", PharmacistAlert),
                ("adt_event", AdtEvent),
            ]
            
            async with self.async_session() as session:
                for name, model in models:
                    try:
                        result = await session.execute(text(f"SELECT COUNT(*) FROM {name}"))
                        count = result.scalar()
                        counts[name] = count
                    except:
                        counts[name] = 0
            
            return counts
        except Exception as e:
            logger.error(f"❌ Error counting records: {e}")
            return {}
    
    async def disconnect(self):
        """Close database connection."""
        if self.engine:
            await self.engine.dispose()
            logger.info("🔌 Database connection closed")

async def main():
    """Main entry point."""
    logger.info("\n" + "="*80)
    logger.info("🚀 SmartHandoff Test Data Population Script")
    logger.info("="*80 + "\n")
    
    populator = TestDataPopulator(DATABASE_URL)
    
    # Step 1: Connect
    if not await populator.connect():
        logger.error("❌ Failed to connect to database. Exiting.")
        sys.exit(1)
    
    # Step 2: Check tables
    logger.info("\n📋 Checking database tables...")
    tables = await populator.check_tables()
    
    if not tables:
        logger.error("❌ No tables found in database. Please run migrations first.")
        await populator.disconnect()
        sys.exit(1)
    
    # Step 3: Populate data
    logger.info("\n📝 Populating test data...")
    logger.info("-" * 80)
    
    try:
        # Populate in order (respecting foreign key dependencies)
        users = await populator.populate_users()
        patients = await populator.populate_patients()
        beds = await populator.populate_beds()
        encounters = await populator.populate_encounters(patients)
        
        # Dependent on encounters
        medications = await populator.populate_medications(encounters)
        documents = await populator.populate_documents(encounters)
        agent_tasks = await populator.populate_agent_tasks(encounters, users)
        care_escalations = await populator.populate_care_escalations(encounters)
        pharmacist_alerts = await populator.populate_pharmacist_alerts(encounters)
        adt_events = await populator.populate_adt_events(encounters)
        
        # Dependent on patients
        appointments = await populator.populate_appointments(patients)
        notifications = await populator.populate_notifications(patients)
        chatbot_transcripts = await populator.populate_chatbot_transcripts(patients)
        
        # Audit logs (general)
        audit_logs = await populator.populate_audit_logs(users)
        
    except Exception as e:
        logger.error(f"❌ Error during population: {e}")
        await populator.disconnect()
        sys.exit(1)
    
    # Step 4: Verify data
    logger.info("\n" + "-" * 80)
    logger.info("📊 Verifying data population...")
    logger.info("-" * 80 + "\n")
    
    counts = await populator.count_records()
    
    total_records = 0
    for table, count in sorted(counts.items()):
        emoji = "✅" if count > 0 else "⚠️ "
        logger.info(f"{emoji} {table:30s}: {count:5d} records")
        total_records += count
    
    # Step 5: Disconnect
    await populator.disconnect()
    
    # Final summary
    logger.info("\n" + "="*80)
    logger.info(f"✅ SUCCESS! Total {total_records} test records created")
    logger.info("="*80 + "\n")
    logger.info("🎯 Next steps:")
    logger.info("   1. Start the backend server:")
    logger.info("      cd backend")
    logger.info("      python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
    logger.info("")
    logger.info("   2. Test API endpoints:")
    logger.info("      curl http://localhost:8000/api/v1/patients")
    logger.info("      curl http://localhost:8000/api/v1/encounters")
    logger.info("")
    logger.info("   3. View database directly:")
    logger.info("      psql -h 127.0.0.1 -p 9432 -U postgres -d smarthandoff")
    logger.info("="*80 + "\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Script interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(1)
