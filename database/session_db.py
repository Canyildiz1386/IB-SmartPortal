from database.db import get_db_connection

def create_study_session(host_id, title, subject_id=None, description='', max_participants=10):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('INSERT INTO study_sessions (host_id, title, subject_id, description, max_participants) VALUES (?, ?, ?, ?, ?)',
					   (host_id, title, subject_id, description, max_participants))
		new_session_id = db_cursor.lastrowid
		db_cursor.execute('INSERT INTO session_participants (session_id, user_id) VALUES (?, ?)', (new_session_id, host_id))
		db_conn.commit()
		db_conn.close()
		return new_session_id
	except Exception:
		return None

def get_study_sessions(user_id=None, subject_id=None):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		sql_query = '''SELECT s.*, u.username as host_name, sub.name as subject_name,
			(SELECT COUNT(*) FROM session_participants WHERE session_id = s.id) as participant_count
			FROM study_sessions s
			JOIN users u ON s.host_id = u.id
			LEFT JOIN subjects sub ON s.subject_id = sub.id
			WHERE s.is_active = 1'''
		query_params = []
		if subject_id:
			sql_query += ' AND s.subject_id = ?'
			query_params.append(subject_id)
		sql_query += ' ORDER BY s.created_at DESC'
		db_cursor.execute(sql_query, tuple(query_params))
		rows = db_cursor.fetchall()
		db_conn.close()
		sessions = []
		for r in rows:
			sessions.append({
				'id': r[0], 'host_id': r[1], 'title': r[2], 'subject_id': r[3],
				'description': r[4], 'max_participants': r[5], 'created_at': r[6],
				'is_active': r[7], 'host_name': r[8], 'subject_name': r[9], 'participant_count': r[10]
			})
		return sessions
	except Exception:
		return []

def get_session_participants(session_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT u.id, u.username, u.role, sp.joined_at
			FROM session_participants sp
			JOIN users u ON sp.user_id = u.id
			WHERE sp.session_id = ?
			ORDER BY sp.joined_at''', (session_id,))
		rows = db_cursor.fetchall()
		db_conn.close()
		participants = []
		for r in rows:
			participants.append({'id': r[0], 'username': r[1], 'role': r[2], 'joined_at': r[3]})
		return participants
	except Exception:
		return []

def join_session(session_id, user_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('INSERT OR IGNORE INTO session_participants (session_id, user_id) VALUES (?, ?)', (session_id, user_id))
		db_conn.commit()
		db_conn.close()
	except Exception:
		pass

def leave_session(session_id, user_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('DELETE FROM session_participants WHERE session_id = ? AND user_id = ?', (session_id, user_id))
		db_conn.commit()
		db_conn.close()
	except Exception:
		pass

def add_session_message(session_id, user_id, message):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('INSERT INTO session_messages (session_id, user_id, message) VALUES (?, ?, ?)', (session_id, user_id, message))
		db_conn.commit()
		db_conn.close()
	except Exception:
		pass

def get_session_messages(session_id, limit=50):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT sm.*, u.username, u.role
			FROM session_messages sm
			JOIN users u ON sm.user_id = u.id
			WHERE sm.session_id = ?
			ORDER BY sm.timestamp DESC
			LIMIT ?''', (session_id, limit))
		rows = db_cursor.fetchall()
		db_conn.close()
		messages = []
		for r in rows:
			messages.append({
				'id': r[0], 'session_id': r[1], 'user_id': r[2], 'message': r[3],
				'timestamp': r[4], 'username': r[5], 'role': r[6]
			})
		return list(reversed(messages))
	except Exception:
		return []
