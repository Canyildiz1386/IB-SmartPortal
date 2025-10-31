from database.db import get_db_connection

def get_user_notes(user_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
		note_rows = db_cursor.fetchall()
		db_conn.close()
		notes_list = []
		for row in note_rows:
			notes_list.append({'id': row[0], 'title': row[2], 'content': row[3], 'subject_id': row[4], 'created_at': row[5]})
		return notes_list
	except Exception:
		return []

def create_note(user_id, title, content, subject_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('INSERT INTO notes (user_id, title, content, subject_id) VALUES (?, ?, ?, ?)', (user_id, title, content, subject_id))
		db_conn.commit()
		db_conn.close()
	except Exception:
		pass

def get_note(note_id, user_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT id, user_id, title, content, subject_id FROM notes WHERE id = ? AND user_id = ?', (note_id, user_id))
		note_row = db_cursor.fetchone()
		db_conn.close()
		if not note_row:
			return None
		return {'id': note_row[0], 'title': note_row[2], 'content': note_row[3], 'subject_id': note_row[4]}
	except Exception:
		return None

def update_note(note_id, user_id, title, content, subject_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT user_id FROM notes WHERE id = ?', (note_id,))
		owner_row = db_cursor.fetchone()
		if not owner_row or owner_row[0] != user_id:
			db_conn.close()
			return False
		db_cursor.execute('UPDATE notes SET title = ?, content = ?, subject_id = ? WHERE id = ?', (title, content, subject_id, note_id))
		db_conn.commit()
		db_conn.close()
		return True
	except Exception:
		return False

def delete_note(note_id, user_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT user_id FROM notes WHERE id = ?', (note_id,))
		owner_row = db_cursor.fetchone()
		if not owner_row or owner_row[0] != user_id:
			db_conn.close()
			return False
		db_cursor.execute('DELETE FROM notes WHERE id = ?', (note_id,))
		db_conn.commit()
		db_conn.close()
		return True
	except Exception:
		return False
