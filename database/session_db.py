from db import get_db_connection

def create_study_session(host_id, title, subject_id=None, description='', max_participants=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO study_sessions (host_id, title, subject_id, description, max_participants) VALUES (?, ?, ?, ?, ?)',
                   (host_id, title, subject_id, description, max_participants))
    session_id = cursor.lastrowid
    cursor.execute('INSERT INTO session_participants (session_id, user_id) VALUES (?, ?)', (session_id, host_id))
    conn.commit()
    conn.close()
    return session_id

def get_study_sessions(user_id=None, subject_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''SELECT s.*, u.username as host_name, sub.name as subject_name,
        (SELECT COUNT(*) FROM session_participants WHERE session_id = s.id) as participant_count
        FROM study_sessions s
        JOIN users u ON s.host_id = u.id
        LEFT JOIN subjects sub ON s.subject_id = sub.id
        WHERE s.is_active = 1'''
    params = []
    if subject_id:
        query += ' AND s.subject_id = ?'
        params.append(subject_id)
    query += ' ORDER BY s.created_at DESC'
    cursor.execute(query, tuple(params))
    results = cursor.fetchall()
    sessions = []
    for row in results:
        sessions.append({
            'id': row[0], 'host_id': row[1], 'title': row[2], 'subject_id': row[3],
            'description': row[4], 'max_participants': row[5], 'created_at': row[6],
            'is_active': row[7], 'host_name': row[8], 'subject_name': row[9], 'participant_count': row[10]
        })
    conn.close()
    return sessions

def get_session_participants(session_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT u.id, u.username, u.role, sp.joined_at
        FROM session_participants sp
        JOIN users u ON sp.user_id = u.id
        WHERE sp.session_id = ?
        ORDER BY sp.joined_at''', (session_id,))
    participants = [{'id': row[0], 'username': row[1], 'role': row[2], 'joined_at': row[3]} for row in cursor.fetchall()]
    conn.close()
    return participants

def join_session(session_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO session_participants (session_id, user_id) VALUES (?, ?)', (session_id, user_id))
    conn.commit()
    conn.close()

def leave_session(session_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM session_participants WHERE session_id = ? AND user_id = ?', (session_id, user_id))
    conn.commit()
    conn.close()

def add_session_message(session_id, user_id, message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO session_messages (session_id, user_id, message) VALUES (?, ?, ?)', (session_id, user_id, message))
    conn.commit()
    conn.close()

def get_session_messages(session_id, limit=50):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT sm.*, u.username, u.role
        FROM session_messages sm
        JOIN users u ON sm.user_id = u.id
        WHERE sm.session_id = ?
        ORDER BY sm.timestamp DESC
        LIMIT ?''', (session_id, limit))
    messages = []
    for row in cursor.fetchall():
        messages.append({
            'id': row[0], 'session_id': row[1], 'user_id': row[2], 'message': row[3],
            'timestamp': row[4], 'username': row[5], 'role': row[6]
        })
    conn.close()
    return list(reversed(messages))

