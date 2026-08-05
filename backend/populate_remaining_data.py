#!/usr/bin/env python3
"""Populate remaining tables with test data."""

import psycopg2
from psycopg2.extras import register_uuid
import uuid
from datetime import datetime, timedelta
import random

# Register UUID support
register_uuid()

def connect_db():
    return psycopg2.connect(
        'dbname=smarthandoff user=postgres password=SmartHandoff@123 host=127.0.0.1 port=9432'
    )

def populate_app_users():
    """Create app users."""
    conn = connect_db()
    cursor = conn.cursor()
    
    users = [
        ('google-oauth2|111111111111111111111', 'jane@smarthandoff.local', 'Nurse Jane', 'RN'),
        ('google-oauth2|222222222222222222222', 'smith@smarthandoff.local', 'Dr. Smith', 'MD'),
        ('google-oauth2|333333333333333333333', 'bob@smarthandoff.local', 'Pharmacist Bob', 'RPh'),
        ('google-oauth2|444444444444444444444', 'alice@smarthandoff.local', 'Admin Alice', 'ADMIN'),
        ('google-oauth2|555555555555555555555', 'mike@smarthandoff.local', 'Nurse Mike', 'RN'),
        ('google-oauth2|666666666666666666666', 'johnson@smarthandoff.local', 'Dr. Johnson', 'MD'),
    ]
    
    for idp_subject, email, full_name, role in users:
        user_id = uuid.uuid4()
        try:
            cursor.execute(
                '''INSERT INTO app_user (id, idp_subject, email, full_name, role, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (user_id, idp_subject, email, full_name, role, datetime.now(), datetime.now())
            )
        except psycopg2.Error as e:
            print(f'  ⚠️  Skipped {email}: {str(e)[:60]}')
    
    conn.commit()
    cursor.execute('SELECT COUNT(*) FROM app_user')
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count

def populate_medications():
    """Create medications."""
    conn = connect_db()
    cursor = conn.cursor()
    
    # Get some encounters
    cursor.execute('SELECT id FROM encounter LIMIT 50')
    encounters = [row[0] for row in cursor.fetchall()]
    
    medications_list = [
        ('Lisinopril', 'ACE Inhibitor', '10mg'),
        ('Metformin', 'Diabetes', '500mg'),
        ('Atorvastatin', 'Statin', '20mg'),
        ('Amoxicillin', 'Antibiotic', '500mg'),
        ('Ibuprofen', 'Pain Relief', '400mg'),
        ('Aspirin', 'Antiplatelet', '81mg'),
        ('Metoprolol', 'Beta Blocker', '25mg'),
        ('Omeprazole', 'Proton Pump Inhibitor', '20mg'),
    ]
    
    count = 0
    for encounter_id in encounters:
        med_name, med_type, med_dose = random.choice(medications_list)
        try:
            cursor.execute(
                '''INSERT INTO medication 
                   (id, encounter_id, name, dose, route, frequency, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
                (uuid.uuid4(), encounter_id, med_name, med_dose, 'oral', 'daily', 
                 datetime.now(), datetime.now())
            )
            count += 1
        except psycopg2.Error:
            pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def populate_documents():
    """Create discharge summaries."""
    conn = connect_db()
    cursor = conn.cursor()
    
    # Get discharged encounters
    cursor.execute('SELECT id FROM encounter WHERE status = %s LIMIT 30', ('DISCHARGED',))
    encounters = [row[0] for row in cursor.fetchall()]
    
    count = 0
    for encounter_id in encounters:
        try:
            cursor.execute(
                '''INSERT INTO document 
                   (id, encounter_id, document_type, title, content, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (uuid.uuid4(), encounter_id, 'DISCHARGE_SUMMARY', 
                 f'Discharge Summary - {datetime.now().strftime("%Y-%m-%d")}',
                 'Patient discharged in stable condition. Follow up with primary care recommended.',
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
    
    # Get patients
    cursor.execute('SELECT id FROM patient LIMIT 30')
    patients = [row[0] for row in cursor.fetchall()]
    
    notification_types = ['APPOINTMENT', 'MEDICATION', 'DISCHARGE', 'FOLLOWUP']
    count = 0
    
    for patient_id in patients:
        for _ in range(random.randint(1, 3)):
            try:
                cursor.execute(
                    '''INSERT INTO notification 
                       (id, patient_id, notification_type, message, is_read, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (uuid.uuid4(), patient_id, random.choice(notification_types),
                     'Important health update', False, datetime.now(), datetime.now())
                )
                count += 1
            except psycopg2.Error:
                pass
    
    conn.commit()
    cursor.close()
    conn.close()
    return count

def populate_agent_tasks():
    """Create agent tasks."""
    conn = connect_db()
    cursor = conn.cursor()
    
    # Get encounters and users
    cursor.execute('SELECT id FROM encounter LIMIT 40')
    encounters = [row[0] for row in cursor.fetchall()]
    
    cursor.execute('SELECT id FROM app_user LIMIT 5')
    users = [row[0] for row in cursor.fetchall()]
    
    statuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED']
    count = 0
    
    for encounter_id in encounters:
        if users:
            try:
                cursor.execute(
                    '''INSERT INTO agent_task 
                       (id, encounter_id, assigned_to, task_type, status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (uuid.uuid4(), encounter_id, random.choice(users), 
                     'MEDICATION_REVIEW', random.choice(statuses), 
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
    
    # Get users
    cursor.execute('SELECT id FROM app_user LIMIT 5')
    users = [row[0] for row in cursor.fetchall()]
    
    actions = ['READ', 'CREATE', 'UPDATE', 'DELETE']
    resources = ['Patient', 'Encounter', 'Medication', 'Document']
    count = 0
    
    for i in range(30):
        if users:
            try:
                cursor.execute(
                    '''INSERT INTO audit_log 
                       (id, resource_type, resource_id, action, details, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (uuid.uuid4(), random.choice(resources), str(uuid.uuid4()),
                     random.choice(actions), f'Audit log entry #{i}',
                     datetime.now() - timedelta(hours=i), datetime.now())
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
    print('📝 Populating Remaining SmartHandoff Tables')
    print('='*70 + '\n')
    
    totals = {}
    
    print('👤 Creating app_users...')
    totals['app_user'] = populate_app_users()
    print(f'   ✅ {totals["app_user"]} users created\n')
    
    print('💊 Creating medications...')
    totals['medication'] = populate_medications()
    print(f'   ✅ {totals["medication"]} medications created\n')
    
    print('📄 Creating documents...')
    totals['document'] = populate_documents()
    print(f'   ✅ {totals["document"]} documents created\n')
    
    print('🔔 Creating notifications...')
    totals['notification'] = populate_notifications()
    print(f'   ✅ {totals["notification"]} notifications created\n')
    
    print('📋 Creating agent tasks...')
    totals['agent_task'] = populate_agent_tasks()
    print(f'   ✅ {totals["agent_task"]} agent tasks created\n')
    
    print('📊 Creating audit logs...')
    totals['audit_log'] = populate_audit_logs()
    print(f'   ✅ {totals["audit_log"]} audit logs created\n')
    
    print('='*70)
    print(f'✅ SUCCESS! Added {sum(totals.values())} new records')
    print('='*70 + '\n')
    
    # Final verification
    conn = connect_db()
    cursor = conn.cursor()
    
    print('📊 Database Summary:')
    tables = ['patient', 'encounter', 'bed', 'app_user', 'medication', 'document', 'notification', 'agent_task', 'audit_log']
    total = 0
    for table in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        count = cursor.fetchone()[0]
        total += count
        print(f'   ✅ {table:20s}: {count:6d}')
    
    print(f'\n   🎉 TOTAL: {total} records in database\n')
    cursor.close()
    conn.close()

if __name__ == '__main__':
    main()
