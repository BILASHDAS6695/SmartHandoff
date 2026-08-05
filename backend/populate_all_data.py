#!/usr/bin/env python3
"""Populate SmartHandoff database with complete test data."""

import psycopg2
from psycopg2.extras import register_uuid
import uuid
from datetime import datetime, timedelta
import json
import random

register_uuid()

def connect_db():
    return psycopg2.connect(
        'dbname=smarthandoff user=postgres password=SmartHandoff@123 host=127.0.0.1 port=9432'
    )

def populate_medications():
    """Create medications with proper schema."""
    conn = connect_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM encounter LIMIT 50')
    encounters = [row[0] for row in cursor.fetchall()]
    
    medications = [
        ('Lisinopril', '42731', '10mg', 'oral', 'daily'),
        ('Metformin', '6809', '500mg', 'oral', 'twice daily'),
        ('Atorvastatin', '1551', '20mg', 'oral', 'daily'),
        ('Amoxicillin', '1742', '500mg', 'oral', 'three times daily'),
        ('Ibuprofen', '5640', '400mg', 'oral', 'as needed'),
        ('Aspirin', '40471', '81mg', 'oral', 'daily'),
        ('Metoprolol', '6749', '25mg', 'oral', 'daily'),
        ('Omeprazole', '7646', '20mg', 'oral', 'daily'),
    ]
    
    count = 0
    for encounter_id in encounters:
        drug_name, rxcui, dose, route, frequency = random.choice(medications)
        try:
            cursor.execute(
                '''INSERT INTO medication 
                   (id, encounter_id, drug_name, rxcui, dose, route, frequency, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (uuid.uuid4(), encounter_id, drug_name, rxcui, dose, route, frequency, 
                 datetime.now(), datetime.now())
            )
            count += 1
        except psycopg2.Error as e:
            pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def populate_documents():
    """Create discharge summaries."""
    conn = connect_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM encounter WHERE status = %s LIMIT 30', ('DISCHARGED',))
    encounters = [row[0] for row in cursor.fetchall()]
    
    count = 0
    for encounter_id in encounters:
        try:
            cursor.execute(
                '''INSERT INTO document 
                   (id, encounter_id, document_type, content, language_code, status, generation_type, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (uuid.uuid4(), encounter_id, 'DISCHARGE_SUMMARY', 
                 'Patient discharged in stable condition. Follow-up appointment scheduled for 1 week. Continue current medications as prescribed.',
                 'en', 'COMPLETED', 'SYSTEM_GENERATED',
                 datetime.now(), datetime.now())
            )
            count += 1
        except psycopg2.Error:
            pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def populate_notifications():
    """Create notifications."""
    conn = connect_db()
    cursor = conn.cursor()
    
    # Get app users as recipients
    cursor.execute('SELECT id FROM app_user LIMIT 10')
    users = [row[0] for row in cursor.fetchall()]
    
    notification_types = ['APPOINTMENT_REMINDER', 'MEDICATION_ALERT', 'DISCHARGE_SUMMARY', 'FOLLOWUP_NEEDED']
    templates = ['appointment_reminder', 'med_due', 'discharge_ready', 'follow_up']
    count = 0
    
    for i in range(30):
        if users:
            try:
                recipient = random.choice(users)
                notif_type = random.choice(notification_types)
                template = random.choice(templates)
                subs = json.dumps({"patient_name": "John Doe", "date": "2026-08-10"})
                
                cursor.execute(
                    '''INSERT INTO notification 
                       (id, idempotency_key, type, recipient_id, template, substitutions, delivery_status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (uuid.uuid4(), f'notif-{i}-{datetime.now().timestamp()}', notif_type, recipient, 
                     template, subs, 'PENDING', datetime.now(), datetime.now())
                )
                count += 1
            except psycopg2.Error as e:
                pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def populate_agent_tasks():
    """Create agent tasks."""
    conn = connect_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM encounter LIMIT 40')
    encounters = [row[0] for row in cursor.fetchall()]
    
    agent_types = ['MEDICATION_RECONCILIATION', 'DISCHARGE_SUMMARY_GENERATION', 'RISK_ASSESSMENT', 'FOLLOW_UP_SCHEDULER']
    statuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED']
    count = 0
    
    for encounter_id in encounters:
        try:
            agent_type = random.choice(agent_types)
            status = random.choice(statuses)
            started = datetime.now() - timedelta(hours=random.randint(1, 24))
            completed = started + timedelta(hours=random.randint(1, 8)) if status == 'COMPLETED' else None
            
            cursor.execute(
                '''INSERT INTO agent_task 
                   (id, encounter_id, agent_type, status, started_at, completed_at, retry_count, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (uuid.uuid4(), encounter_id, agent_type, status, started, completed, 0,
                 datetime.now(), datetime.now())
            )
            count += 1
        except psycopg2.Error:
            pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def populate_audit_logs():
    """Create audit logs."""
    conn = connect_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id FROM app_user LIMIT 5')
    users = [row[0] for row in cursor.fetchall()]
    
    actions = ['READ', 'CREATE', 'UPDATE', 'DELETE', 'VIEW_RECORD']
    resources = ['Patient', 'Encounter', 'Medication', 'Document', 'Notification']
    outcomes = ['SUCCESS', 'AUTHORIZED', 'DENIED']
    count = 0
    
    for i in range(50):
        if users:
            try:
                user_id = random.choice(users)
                cursor.execute(
                    '''INSERT INTO audit_log 
                       (id, user_id, resource_type, resource_id, action, outcome, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (uuid.uuid4(), user_id, random.choice(resources), str(uuid.uuid4()),
                     random.choice(actions), random.choice(outcomes),
                     datetime.now() - timedelta(hours=i))
                )
                count += 1
            except psycopg2.Error:
                pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def main():
    print('\n' + '='*70)
    print('📝 Populating SmartHandoff Database - Complete Test Data')
    print('='*70 + '\n')
    
    totals = {}
    
    print('💊 Creating medications...')
    totals['medication'] = populate_medications()
    print(f'   ✅ {totals["medication"]} medications\n')
    
    print('📄 Creating discharge documents...')
    totals['document'] = populate_documents()
    print(f'   ✅ {totals["document"]} documents\n')
    
    print('🔔 Creating notifications...')
    totals['notification'] = populate_notifications()
    print(f'   ✅ {totals["notification"]} notifications\n')
    
    print('⚙️  Creating agent tasks...')
    totals['agent_task'] = populate_agent_tasks()
    print(f'   ✅ {totals["agent_task"]} agent tasks\n')
    
    print('📊 Creating audit logs...')
    totals['audit_log'] = populate_audit_logs()
    print(f'   ✅ {totals["audit_log"]} audit logs\n')
    
    # Final summary
    conn = connect_db()
    cursor = conn.cursor()
    
    print('='*70)
    print('📊 SMARTHANDOFF DATABASE - FINAL SUMMARY')
    print('='*70)
    
    tables = ['patient', 'encounter', 'bed', 'app_user', 'medication', 'document', 'notification', 'agent_task', 'audit_log']
    total = 0
    
    for table in tables:
        try:
            cursor.execute(f'SELECT COUNT(*) FROM {table}')
            count = cursor.fetchone()[0]
            total += count
            emoji = '✅' if count > 0 else '⚠️ '
            print(f'{emoji} {table:25s}: {count:6d} records')
        except:
            pass
    
    print('='*70)
    print(f'\n🎉 SUCCESS! Total {total} records in database\n')
    print('📝 You can now:')
    print('   1. Start the backend: cd backend && python -m uvicorn app.main:app --reload')
    print('   2. Query the API: curl http://localhost:8000/api/v1/patients')
    print('   3. Access the frontend: http://localhost:4200\n')
    
    cursor.close()
    conn.close()

if __name__ == '__main__':
    main()
