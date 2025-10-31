from db import get_db_connection
import json

def get_admin_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE role = "student"')
    total_students = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE role = "teacher"')
    total_teachers = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM materials')
    total_materials = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM quizzes')
    total_quizzes = cursor.fetchone()[0]
    cursor.execute('SELECT AVG(score) FROM quiz_results')
    avg_score = cursor.fetchone()[0] or 0
    conn.close()
    return {'total_users': total_users, 'total_students': total_students, 'total_teachers': total_teachers, 'total_materials': total_materials, 'total_quizzes': total_quizzes, 'avg_score': round(avg_score, 1)}

def get_teacher_stats(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM quizzes WHERE teacher_id = ?', (teacher_id,))
    total_quizzes = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(DISTINCT qa.student_id) FROM quiz_assignments qa JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?', (teacher_id,))
    active_students = cursor.fetchone()[0]
    cursor.execute('SELECT AVG(qr.score) FROM quiz_results qr JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?', (teacher_id,))
    avg_score = cursor.fetchone()[0] or 0
    cursor.execute('SELECT COUNT(*) FROM quiz_results qr JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?', (teacher_id,))
    total_attempts = cursor.fetchone()[0]
    conn.close()
    return {'total_quizzes': total_quizzes, 'active_students': active_students, 'avg_score': round(avg_score, 1), 'total_attempts': total_attempts}

def get_recent_activities():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT u.username, qr.score, qr.time, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id ORDER BY qr.time DESC LIMIT 10''')
    activities = [{'username': row[0], 'score': row[1], 'time': row[2], 'quiz_title': row[3]} for row in cursor.fetchall()]
    conn.close()
    return activities

def get_teacher_recent_activities(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT u.username, qr.score, qr.time, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ? ORDER BY qr.time DESC LIMIT 10''', (teacher_id,))
    activities = [{'username': row[0], 'score': row[1], 'time': row[2], 'quiz_title': row[3]} for row in cursor.fetchall()]
    conn.close()
    return activities

def get_user_distribution():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role, COUNT(*) FROM users GROUP BY role')
    roles = cursor.fetchall()
    labels = [role.title() for role, count in roles]
    values = [count for role, count in roles]
    conn.close()
    return {'labels': labels, 'values': values}

def get_performance_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT AVG(score) FROM quiz_results')
    avg_score = cursor.fetchone()[0] or 0
    cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score >= 80')
    high_scores = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score >= 60 AND score < 80')
    medium_scores = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score < 60')
    low_scores = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM quiz_results')
    total_attempts = cursor.fetchone()[0]
    return {'labels': ['High (80%+)', 'Medium (60-79%)', 'Low (<60%)'], 'values': [high_scores, medium_scores, low_scores], 'average_score': round(avg_score, 1), 'total_attempts': total_attempts}

def get_subject_activity():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT s.name, COUNT(q.id) as quiz_count FROM subjects s LEFT JOIN quizzes q ON s.id = q.subject_id GROUP BY s.id, s.name ORDER BY quiz_count DESC''')
    results = cursor.fetchall()
    labels = [name for name, count in results]
    values = [count for name, count in results]
    conn.close()
    return {'labels': labels, 'values': values}

def get_time_series_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT DATE(time) as date, COUNT(*) as attempts FROM quiz_results WHERE time >= date('now', '-7 days') GROUP BY DATE(time) ORDER BY date''')
    results = cursor.fetchall()
    labels = [date for date, attempts in results]
    values = [attempts for date, attempts in results]
    conn.close()
    return {'labels': labels, 'values': values}

def get_score_distribution():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT CASE WHEN score >= 90 THEN '90-100%' WHEN score >= 80 THEN '80-89%' WHEN score >= 70 THEN '70-79%' WHEN score >= 60 THEN '60-69%' ELSE 'Below 60%' END as range, COUNT(*) as count FROM quiz_results GROUP BY CASE WHEN score >= 90 THEN '90-100%' WHEN score >= 80 THEN '80-89%' WHEN score >= 70 THEN '70-79%' WHEN score >= 60 THEN '60-69%' ELSE 'Below 60%' END ORDER BY CASE WHEN score >= 90 THEN 1 WHEN score >= 80 THEN 2 WHEN score >= 70 THEN 3 WHEN score >= 60 THEN 4 ELSE 5 END''')
    results = cursor.fetchall()
    labels = [range_name for range_name, count in results]
    values = [count for range_name, count in results]
    conn.close()
    return {'labels': labels, 'values': values}

def get_teacher_qa_logs(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa 
        JOIN users u ON qa.user_id = u.id 
        WHERE u.id IN (SELECT DISTINCT qa2.student_id FROM quiz_assignments qa2 JOIN quizzes q ON qa2.quiz_id = q.id WHERE q.teacher_id = ?)
        ORDER BY qa.timestamp DESC LIMIT 100''', (teacher_id,))
    logs = [{'question': row[0], 'answer': row[1], 'timestamp': row[2], 'username': row[3]} for row in cursor.fetchall()]
    conn.close()
    return logs

def get_teacher_quiz_results(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr 
        JOIN users u ON qr.user_id = u.id 
        JOIN quizzes q ON qr.quiz_id = q.id 
        WHERE q.teacher_id = ? ORDER BY qr.time DESC LIMIT 100''', (teacher_id,))
    results = [{'score': row[0], 'time': row[1], 'answers': json.loads(row[2]), 'username': row[3], 'quiz_title': row[4]} for row in cursor.fetchall()]
    conn.close()
    return results

def get_teacher_performance_data(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT AVG(qr.score) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
    avg_score = cursor.fetchone()[0] or 0
    cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score >= 80''', (teacher_id,))
    high_scores = cursor.fetchone()[0]
    cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score >= 60 AND qr.score < 80''', (teacher_id,))
    medium_scores = cursor.fetchone()[0]
    cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score < 60''', (teacher_id,))
    low_scores = cursor.fetchone()[0]
    cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
    total_attempts = cursor.fetchone()[0]
    conn.close()
    return {'labels': ['High (80%+)', 'Medium (60-79%)', 'Low (<60%)'], 'values': [high_scores, medium_scores, low_scores], 'average_score': round(avg_score, 1), 'total_attempts': total_attempts}

def get_teacher_student_stats(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT COUNT(DISTINCT qa.student_id) FROM quiz_assignments qa JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
    total_students = cursor.fetchone()[0]
    cursor.execute('''SELECT COUNT(DISTINCT qr.user_id) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
    active_students = cursor.fetchone()[0]
    conn.close()
    return {'total_students': total_students, 'active_students': active_students}

def get_teacher_quiz_stats(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM quizzes WHERE teacher_id = ?', (teacher_id,))
    total_quizzes = cursor.fetchone()[0]
    cursor.execute('''SELECT COUNT(DISTINCT qr.quiz_id) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
    completed_quizzes = cursor.fetchone()[0]
    conn.close()
    return {'total_quizzes': total_quizzes, 'completed_quizzes': completed_quizzes}

def get_teacher_time_series(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT DATE(qr.time) as date, COUNT(*) as attempts FROM quiz_results qr 
        JOIN quizzes q ON qr.quiz_id = q.id 
        WHERE q.teacher_id = ? AND qr.time >= date('now', '-7 days') 
        GROUP BY DATE(qr.time) ORDER BY date''', (teacher_id,))
    results = cursor.fetchall()
    labels = [date for date, attempts in results]
    values = [attempts for date, attempts in results]
    conn.close()
    return {'labels': labels, 'values': values}

def get_teacher_subject_performance(teacher_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''SELECT s.name, AVG(qr.score) as avg_score FROM quiz_results qr 
        JOIN quizzes q ON qr.quiz_id = q.id 
        JOIN subjects s ON q.subject_id = s.id 
        WHERE q.teacher_id = ? 
        GROUP BY s.id, s.name 
        ORDER BY avg_score DESC LIMIT 10''', (teacher_id,))
    results = cursor.fetchall()
    labels = [name for name, avg_score in results]
    values = [round(avg_score, 1) for name, avg_score in results]
    conn.close()
    return {'labels': labels, 'values': values}

