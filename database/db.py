import sqlite3
import hashlib
import json

DATABASE = 'smart_study.db'

def get_db_connection():
    return sqlite3.connect(DATABASE)

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student'
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (subject_id) REFERENCES subjects (id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        sha TEXT NOT NULL,
        content TEXT,
        subject_id INTEGER,
        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        indexed INTEGER DEFAULT 0,
        FOREIGN KEY (subject_id) REFERENCES subjects (id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS qa_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        subject_id INTEGER,
        teacher_id INTEGER,
        questions TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (subject_id) REFERENCES subjects (id),
        FOREIGN KEY (teacher_id) REFERENCES users (id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS quiz_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER,
        student_id INTEGER,
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id),
        FOREIGN KEY (student_id) REFERENCES users (id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS quiz_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        quiz_id INTEGER,
        score REAL NOT NULL,
        answers TEXT NOT NULL,
        time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS teacher_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (from_id) REFERENCES users (id),
        FOREIGN KEY (to_id) REFERENCES users (id)
    )''')
    cursor.execute('SELECT COUNT(*) FROM subjects')
    if cursor.fetchone()[0] == 0:
        default_subjects = ['Math', 'Science', 'English', 'History']
        for subject in default_subjects:
            cursor.execute('INSERT INTO subjects (name) VALUES (?)', (subject,))
    cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?', ('admin',))
    if cursor.fetchone()[0] == 0:
        admin_password = hashlib.sha256('admin'.encode()).hexdigest()
        cursor.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', ('admin', admin_password, 'admin'))
    conn.commit()
    conn.close()

def verify_user(username, password):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        h = hashlib.sha256(password.encode()).hexdigest()
        c.execute('SELECT id, username, role FROM users WHERE username = ? AND password_hash = ?', (username, h))
        u = c.fetchone()
        conn.close()
        if u:
            return {'id': u[0], 'username': u[1], 'role': u[2]}
        return None
    except:
        return None

def add_user(username, password, role):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        h = hashlib.sha256(password.encode()).hexdigest()
        c.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', (username, h, role))
        id = c.lastrowid
        conn.commit()
        conn.close()
        return id
    except:
        return None

def get_all_users():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT id, username, role FROM users ORDER BY username')
        rows = c.fetchall()
        conn.close()
        users = []
        for r in rows:
            users.append({'id': r[0], 'username': r[1], 'role': r[2]})
        return users
    except:
        return []

def delete_user(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
    except:
        pass

def add_material(filename, content, subject_id, indexed=0):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        h = hashlib.sha256(content.encode()).hexdigest()
        c.execute('INSERT INTO materials (filename, sha, content, subject_id, indexed) VALUES (?, ?, ?, ?, ?)', (filename, h, content, subject_id, indexed))
        id = c.lastrowid
        conn.commit()
        conn.close()
        return id
    except:
        return None

def get_materials():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT * FROM materials ORDER BY upload_time DESC')
        rows = c.fetchall()
        conn.close()
        materials = []
        for r in rows:
            materials.append({'id': r[0], 'filename': r[1], 'sha': r[2], 'content': r[3], 'subject_id': r[4], 'upload_time': r[5], 'indexed': r[6]})
        return materials
    except:
        return []

def log_qa(user_id, question, answer):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('INSERT INTO qa_logs (user_id, question, answer) VALUES (?, ?, ?)', (user_id, question, answer))
        conn.commit()
        conn.close()
    except:
        pass

def get_qa_logs(user_id=None):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id:
            cursor.execute('SELECT question, answer, timestamp FROM qa_logs WHERE user_id = ? ORDER BY timestamp DESC', (user_id,))
        else:
            cursor.execute('SELECT question, answer, timestamp FROM qa_logs ORDER BY timestamp DESC')
        rows = cursor.fetchall()
        conn.close()
        logs = []
        for r in rows:
            logs.append({'question': r[0], 'answer': r[1], 'timestamp': r[2]})
        return logs
    except:
        return []

def get_subjects():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM subjects ORDER BY name')
        rows = cursor.fetchall()
        conn.close()
        subjects = []
        for r in rows:
            subjects.append({'id': r[0], 'name': r[1]})
        return subjects
    except:
        return []

def get_user_subjects(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT s.id, s.name FROM subjects s JOIN user_subjects us ON s.id = us.subject_id WHERE us.user_id = ? ORDER BY s.name', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        subjects = []
        for r in rows:
            subjects.append({'id': r[0], 'name': r[1]})
        return subjects
    except:
        return []

def assign_user_subject(user_id, subject_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO user_subjects (user_id, subject_id) VALUES (?, ?)', (user_id, subject_id))
        conn.commit()
        conn.close()
    except:
        pass

def create_quiz(title, subject_id, teacher_id, questions):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        questions_json = json.dumps(questions)
        cursor.execute('INSERT INTO quizzes (title, subject_id, teacher_id, questions) VALUES (?, ?, ?, ?)', (title, subject_id, teacher_id, questions_json))
        quiz_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return quiz_id
    except:
        return None

def assign_quiz_to_students(quiz_id, student_ids):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        for student_id in student_ids:
            cursor.execute('INSERT OR IGNORE INTO quiz_assignments (quiz_id, student_id) VALUES (?, ?)', (quiz_id, student_id))
        conn.commit()
        conn.close()
    except:
        pass

def get_teacher_quizzes(teacher_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM quizzes WHERE teacher_id = ? ORDER BY created_at DESC', (teacher_id,))
        rows = cursor.fetchall()
        conn.close()
        quizzes = []
        for r in rows:
            quizzes.append({'id': r[0], 'title': r[1], 'subject_id': r[2], 'teacher_id': r[3], 'questions': json.loads(r[4]), 'created_at': r[5]})
        return quizzes
    except:
        return []

def get_student_quizzes(student_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT q.* FROM quizzes q JOIN quiz_assignments qa ON q.id = qa.quiz_id WHERE qa.student_id = ? ORDER BY q.created_at DESC', (student_id,))
        rows = cursor.fetchall()
        conn.close()
        quizzes = []
        for r in rows:
            quizzes.append({'id': r[0], 'title': r[1], 'subject_id': r[2], 'teacher_id': r[3], 'questions': json.loads(r[4]), 'created_at': r[5]})
        return quizzes
    except:
        return []

def get_quiz_by_id(quiz_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM quizzes WHERE id = ?', (quiz_id,))
        quiz_row = cursor.fetchone()
        conn.close()
        if quiz_row:
            return {'id': quiz_row[0], 'title': quiz_row[1], 'subject_id': quiz_row[2], 'teacher_id': quiz_row[3], 'questions': json.loads(quiz_row[4]), 'created_at': quiz_row[5]}
        return None
    except:
        return None

def log_quiz_result(user_id, score, answers, quiz_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        answers_json = json.dumps(answers)
        cursor.execute('INSERT INTO quiz_results (user_id, quiz_id, score, answers) VALUES (?, ?, ?, ?)', (user_id, quiz_id, score, answers_json))
        result_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return result_id
    except:
        return None
