from database.db import get_db_connection

def get_user_notes(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    notes = [{'id': row[0], 'title': row[2], 'content': row[3], 'subject_id': row[4], 'created_at': row[5]} for row in cursor.fetchall()]
    conn.close()
    return notes

def create_note(user_id, title, content, subject_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO notes (user_id, title, content, subject_id) VALUES (?, ?, ?, ?)', (user_id, title, content, subject_id))
    conn.commit()
    conn.close()

def get_note(note_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, user_id, title, content, subject_id FROM notes WHERE id = ? AND user_id = ?', (note_id, user_id))
    note_row = cursor.fetchone()
    conn.close()
    if not note_row:
        return None
    return {'id': note_row[0], 'title': note_row[2], 'content': note_row[3], 'subject_id': note_row[4]}

def update_note(note_id, user_id, title, content, subject_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM notes WHERE id = ?', (note_id,))
    note = cursor.fetchone()
    if not note or note[0] != user_id:
        conn.close()
        return False
    cursor.execute('UPDATE notes SET title = ?, content = ?, subject_id = ? WHERE id = ?', (title, content, subject_id, note_id))
    conn.commit()
    conn.close()
    return True

def delete_note(note_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM notes WHERE id = ?', (note_id,))
    note = cursor.fetchone()
    if not note or note[0] != user_id:
        conn.close()
        return False
    cursor.execute('DELETE FROM notes WHERE id = ?', (note_id,))
    conn.commit()
    conn.close()
    return True

