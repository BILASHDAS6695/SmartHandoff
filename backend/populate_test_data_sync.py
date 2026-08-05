#!/usr/bin/env python3
"""
Synchronous test data population script for SmartHandoff (using psycopg2).
Connects to localhost via Cloud SQL proxy and populates all tables with realistic test data.
"""

import sys
import uuid
from datetime import datetime, timedelta
from typing import List
import logging

from sqlalchemy import create_engine, text, inspect
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database URL for localhost with Cloud SQL proxy
# Note: password contains @ which must be URL-encoded as %40
DATABASE_URL = "postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"

class TestDataPopulator:
    """Handles database connection and test data population."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.engine = None
        self.Session = None
    
    def connect(self) -> bool:
        """Establish database connection."""
        try:
            logger.info(f"🔌 Connecting to database: {self.db_url}")
            self.engine = create_engine(
                self.db_url,
                echo=False,
                pool_size=10,
                max_overflow=20,
                connect_args={"connect_timeout": 10}
            )
            
            # Test connection
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                logger.info("✅ Database connection successful!")
            
            self.Session = sessionmaker(bind=self.engine)
            return True
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
    
    def check_tables(self) -> dict:
        """Check which tables exist in the database."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
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
    
    def clear_all_data(self):
        """Clear all data from tables (for fresh start)."""
        session = self.Session()
        try:
            tables = [
                'audit_log', 'pharmacist_alert', 'chatbot_transcript',
                'care_escalation', 'scheduled_notification',
                'appointment', 'agent_task', 'document', 'medication',
                'adt_event', 'bed', 'encounter', 'app_user', 'patient'
            ]
            
            for table in tables:
                try:
                    session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                    logger.info(f"   ✓ Cleared {table}")
                except Exception as e:
                    logger.warning(f"   ⚠ Could not clear {table}: {e}")
            
            session.commit()
            logger.info("✅ All tables cleared")
        except Exception as e:
            logger.error(f"❌ Error clearing data: {e}")
            session.rollback()
        finally:
            session.close()
    
    def populate_users(self) -> List[AppUser]:
        """Create test users."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(users)} users")
            return users
        except Exception as e:
            logger.error(f"❌ Error creating users: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_patients(self) -> List[Patient]:
        """Create test patients."""
        session = self.Session()
        try:
            patients = [
                Patient(
                    id=uuid.uuid4(),
                    mrn_encrypted="00001234",
                    first_name_encrypted="John",
                    last_name_encrypted="Doe",
                    date_of_birth="1960-01-15",
                    gender="M",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                ),
                Patient(
                    id=uuid.uuid4(),
                    mrn_encrypted="00001235",
                    first_name_encrypted="Jane",
                    last_name_encrypted="Smith",
                    date_of_birth="1975-05-20",
                    gender="F",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                ),
                Patient(
                    id=uuid.uuid4(),
                    mrn_encrypted="00001236",
                    first_name_encrypted="Robert",
                    last_name_encrypted="Johnson",
                    date_of_birth="1945-12-10",
                    gender="M",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                ),
                Patient(
                    id=uuid.uuid4(),
                    mrn_encrypted="00001237",
                    first_name_encrypted="Mary",
                    last_name_encrypted="Williams",
                    date_of_birth="1985-03-25",
                    gender="F",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                ),
            ]
            
            session.add_all(patients)
            session.commit()
            logger.info(f"✅ Created {len(patients)} patients")
            return patients
        except Exception as e:
            logger.error(f"❌ Error creating patients: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_beds(self) -> List[Bed]:
        """Create test beds."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(beds)} beds")
            return beds
        except Exception as e:
            logger.error(f"❌ Error creating beds: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_encounters(self, patients: List[Patient]) -> List[Encounter]:
        """Create test encounters."""
        session = self.Session()
        try:
            encounters = []
            statuses = [EncounterStatus.ADMITTED, EncounterStatus.TRANSFERRED, EncounterStatus.DISCHARGED]
            
            for i, patient in enumerate(patients[:2]):
                encounter = Encounter(
                    id=uuid.uuid4(),
                    patient_id=patient.id,
                    visit_number=f"V{str(uuid.uuid4())[:8]}",
                    status=statuses[i % len(statuses)],
                    admission_time=datetime.now() - timedelta(hours=24*i),
                    bed_id=None,
                    discharge_time=datetime.now() if i % 2 == 0 else None,
                    risk_tier=RiskTier.HIGH if i % 2 == 0 else RiskTier.MEDIUM,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                encounters.append(encounter)
            
            session.add_all(encounters)
            session.commit()
            logger.info(f"✅ Created {len(encounters)} encounters")
            return encounters
        except Exception as e:
            logger.error(f"❌ Error creating encounters: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_medications(self, encounters: List[Encounter]) -> List[Medication]:
        """Create test medications."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(medications)} medications")
            return medications
        except Exception as e:
            logger.error(f"❌ Error creating medications: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_documents(self, encounters: List[Encounter]) -> List[Document]:
        """Create test documents."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(documents)} documents")
            return documents
        except Exception as e:
            logger.error(f"❌ Error creating documents: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_agent_tasks(self, encounters: List[Encounter], users: List[AppUser]) -> List[AgentTask]:
        """Create test agent tasks."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(agent_tasks)} agent tasks")
            return agent_tasks
        except Exception as e:
            logger.error(f"❌ Error creating agent tasks: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_appointments(self, patients: List[Patient]) -> List[Appointment]:
        """Create test appointments."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(appointments)} appointments")
            return appointments
        except Exception as e:
            logger.error(f"❌ Error creating appointments: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_notifications(self, patients: List[Patient]) -> List[ScheduledNotification]:
        """Create test notifications."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(notifications)} notifications")
            return notifications
        except Exception as e:
            logger.error(f"❌ Error creating notifications: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_care_escalations(self, encounters: List[Encounter]) -> List[CareEscalation]:
        """Create test care escalations."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(escalations)} care escalations")
            return escalations
        except Exception as e:
            logger.error(f"❌ Error creating care escalations: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_audit_logs(self, users: List[AppUser]) -> List[AuditLog]:
        """Create test audit logs."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(audit_logs)} audit logs")
            return audit_logs
        except Exception as e:
            logger.error(f"❌ Error creating audit logs: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_chatbot_transcripts(self, patients: List[Patient]) -> List[ChatbotTranscript]:
        """Create test chatbot transcripts."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(transcripts)} chatbot transcripts")
            return transcripts
        except Exception as e:
            logger.error(f"❌ Error creating chatbot transcripts: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_pharmacist_alerts(self, encounters: List[Encounter]) -> List[PharmacistAlert]:
        """Create test pharmacist alerts."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(alerts)} pharmacist alerts")
            return alerts
        except Exception as e:
            logger.error(f"❌ Error creating pharmacist alerts: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def populate_adt_events(self, encounters: List[Encounter]) -> List[AdtEvent]:
        """Create test ADT events."""
        session = self.Session()
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
            session.commit()
            logger.info(f"✅ Created {len(events)} ADT events")
            return events
        except Exception as e:
            logger.error(f"❌ Error creating ADT events: {e}")
            session.rollback()
            return []
        finally:
            session.close()
    
    def count_records(self) -> dict:
        """Count records in all tables."""
        try:
            counts = {}
            tables = [
                "patient", "encounter", "app_user", "bed", "medication", "document",
                "agent_task", "appointment", "scheduled_notification",
                "care_escalation", "audit_log", "chatbot_transcript",
                "pharmacist_alert", "adt_event"
            ]
            
            with self.engine.connect() as conn:
                for table in tables:
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = result.scalar()
                        counts[table] = count
                    except:
                        counts[table] = 0
            
            return counts
        except Exception as e:
            logger.error(f"❌ Error counting records: {e}")
            return {}
    
    def disconnect(self):
        """Close database connection."""
        if self.engine:
            self.engine.dispose()
            logger.info("🔌 Database connection closed")

def main():
    """Main entry point."""
    logger.info("\n" + "="*80)
    logger.info("🚀 SmartHandoff Test Data Population Script")
    logger.info("="*80 + "\n")
    
    populator = TestDataPopulator(DATABASE_URL)
    
    # Step 1: Connect
    if not populator.connect():
        logger.error("❌ Failed to connect to database. Exiting.")
        sys.exit(1)
    
    # Step 2: Check tables
    logger.info("\n📋 Checking database tables...")
    tables = populator.check_tables()
    
    if not tables:
        logger.error("❌ No tables found in database. Please run migrations first.")
        populator.disconnect()
        sys.exit(1)
    
    # Step 3: Populate data
    logger.info("\n📝 Populating test data...")
    logger.info("-" * 80)
    
    try:
        # Populate in order (respecting foreign key dependencies)
        users = populator.populate_users()
        patients = populator.populate_patients()
        beds = populator.populate_beds()
        encounters = populator.populate_encounters(patients)
        
        # Dependent on encounters
        medications = populator.populate_medications(encounters)
        documents = populator.populate_documents(encounters)
        agent_tasks = populator.populate_agent_tasks(encounters, users)
        care_escalations = populator.populate_care_escalations(encounters)
        pharmacist_alerts = populator.populate_pharmacist_alerts(encounters)
        adt_events = populator.populate_adt_events(encounters)
        
        # Dependent on patients
        appointments = populator.populate_appointments(patients)
        notifications = populator.populate_notifications(patients)
        chatbot_transcripts = populator.populate_chatbot_transcripts(patients)
        
        # Audit logs (general)
        audit_logs = populator.populate_audit_logs(users)
        
    except Exception as e:
        logger.error(f"❌ Error during population: {e}")
        populator.disconnect()
        sys.exit(1)
    
    # Step 4: Verify data
    logger.info("\n" + "-" * 80)
    logger.info("📊 Verifying data population...")
    logger.info("-" * 80 + "\n")
    
    counts = populator.count_records()
    
    total_records = 0
    for table, count in sorted(counts.items()):
        emoji = "✅" if count > 0 else "⚠️ "
        logger.info(f"{emoji} {table:30s}: {count:5d} records")
        total_records += count
    
    # Step 5: Disconnect
    populator.disconnect()
    
    # Final summary
    logger.info("\n" + "="*80)
    logger.info(f"✅ SUCCESS! Total {total_records} test records created")
    logger.info("="*80 + "\n")
    logger.info("🎯 Next steps:")
    logger.info("   1. Start the backend server in another terminal:")
    logger.info("      cd backend")
    logger.info("      python -m uvicorn app.main:app --host 0.0.0.0 --port 8000")
    logger.info("")
    logger.info("   2. Test API endpoints:")
    logger.info("      curl http://localhost:8000/api/v1/patients")
    logger.info("      curl http://localhost:8000/api/v1/encounters")
    logger.info("="*80 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Script interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(1)
