from database.db import get_db_connection
import json

def get_admin_stats():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT COUNT(*) FROM users')
		user_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM users WHERE role = "student"')
		student_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM users WHERE role = "teacher"')
		teacher_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM materials')
		material_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM quizzes')
		quiz_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT AVG(score) FROM quiz_results')
		avg_score_row = db_cursor.fetchone()[0]
		avg_score_val = avg_score_row if avg_score_row else 0
		db_conn.close()
		return {'total_users': user_count, 'total_students': student_count, 'total_teachers': teacher_count, 'total_materials': material_count, 'total_quizzes': quiz_count, 'avg_score': round(avg_score_val, 1)}
	except Exception:
		return {'total_users': 0, 'total_students': 0, 'total_teachers': 0, 'total_materials': 0, 'total_quizzes': 0, 'avg_score': 0}

def get_teacher_stats(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT COUNT(*) FROM quizzes WHERE teacher_id = ?', (teacher_id,))
		quiz_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(DISTINCT qa.student_id) FROM quiz_assignments qa JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?', (teacher_id,))
		active_student_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT AVG(qr.score) FROM quiz_results qr JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?', (teacher_id,))
		avg_score_row = db_cursor.fetchone()[0]
		avg_score_val = avg_score_row if avg_score_row else 0
		db_cursor.execute('SELECT COUNT(*) FROM quiz_results qr JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?', (teacher_id,))
		attempt_count = db_cursor.fetchone()[0]
		db_conn.close()
		return {'total_quizzes': quiz_count, 'active_students': active_student_count, 'avg_score': round(avg_score_val, 1), 'total_attempts': attempt_count}
	except Exception:
		return {'total_quizzes': 0, 'active_students': 0, 'avg_score': 0, 'total_attempts': 0}

def get_recent_activities():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT u.username, qr.score, qr.time, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id ORDER BY qr.time DESC LIMIT 10''')
		rows = db_cursor.fetchall()
		db_conn.close()
		activities = []
		for r in rows:
			activities.append({'username': r[0], 'score': r[1], 'time': r[2], 'quiz_title': r[3]})
		return activities
	except Exception:
		return []

def get_teacher_recent_activities(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT u.username, qr.score, qr.time, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ? ORDER BY qr.time DESC LIMIT 10''', (teacher_id,))
		rows = db_cursor.fetchall()
		db_conn.close()
		activities = []
		for r in rows:
			activities.append({'username': r[0], 'score': r[1], 'time': r[2], 'quiz_title': r[3]})
		return activities
	except Exception:
		return []

def get_user_distribution():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT role, COUNT(*) FROM users GROUP BY role')
		rows = db_cursor.fetchall()
		db_conn.close()
		labels = []
		values = []
		for role, count in rows:
			labels.append(role.title())
			values.append(count)
		return {'labels': labels, 'values': values}
	except Exception:
		return {'labels': [], 'values': []}

def get_performance_data():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT AVG(score) FROM quiz_results')
		avg_score_row = db_cursor.fetchone()[0]
		avg_score_val = avg_score_row if avg_score_row else 0
		db_cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score >= 80')
		high_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score >= 60 AND score < 80')
		medium_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score < 60')
		low_count = db_cursor.fetchone()[0]
		db_cursor.execute('SELECT COUNT(*) FROM quiz_results')
		attempt_count = db_cursor.fetchone()[0]
		db_conn.close()
		return {'labels': ['High (80%+)', 'Medium (60-79%)', 'Low (<60%)'], 'values': [high_count, medium_count, low_count], 'average_score': round(avg_score_val, 1), 'total_attempts': attempt_count}
	except Exception:
		return {'labels': [], 'values': [], 'average_score': 0, 'total_attempts': 0}

def get_subject_activity():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT s.name, COUNT(q.id) as quiz_count FROM subjects s LEFT JOIN quizzes q ON s.id = q.subject_id GROUP BY s.id, s.name ORDER BY quiz_count DESC''')
		rows = db_cursor.fetchall()
		db_conn.close()
		labels = []
		values = []
		for name, count in rows:
			labels.append(name)
			values.append(count)
		return {'labels': labels, 'values': values}
	except Exception:
		return {'labels': [], 'values': []}

def get_time_series_data():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT DATE(time) as date, COUNT(*) as attempts FROM quiz_results WHERE time >= date('now', '-7 days') GROUP BY DATE(time) ORDER BY date''')
		rows = db_cursor.fetchall()
		db_conn.close()
		labels = []
		values = []
		for date, count in rows:
			labels.append(date)
			values.append(count)
		return {'labels': labels, 'values': values}
	except Exception:
		return {'labels': [], 'values': []}

def get_score_distribution():
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT CASE WHEN score >= 90 THEN '90-100%' WHEN score >= 80 THEN '80-89%' WHEN score >= 70 THEN '70-79%' WHEN score >= 60 THEN '60-69%' ELSE 'Below 60%' END as range, COUNT(*) as count FROM quiz_results GROUP BY CASE WHEN score >= 90 THEN '90-100%' WHEN score >= 80 THEN '80-89%' WHEN score >= 70 THEN '70-79%' WHEN score >= 60 THEN '60-69%' ELSE 'Below 60%' END ORDER BY CASE WHEN score >= 90 THEN 1 WHEN score >= 80 THEN 2 WHEN score >= 70 THEN 3 WHEN score >= 60 THEN 4 ELSE 5 END''')
		rows = db_cursor.fetchall()
		db_conn.close()
		labels = []
		values = []
		for rname, count in rows:
			labels.append(rname)
			values.append(count)
		return {'labels': labels, 'values': values}
	except Exception:
		return {'labels': [], 'values': []}

def get_teacher_qa_logs(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa 
			JOIN users u ON qa.user_id = u.id 
			WHERE u.id IN (SELECT DISTINCT qa2.student_id FROM quiz_assignments qa2 JOIN quizzes q ON qa2.quiz_id = q.id WHERE q.teacher_id = ?)
			ORDER BY qa.timestamp DESC LIMIT 100''', (teacher_id,))
		rows = db_cursor.fetchall()
		db_conn.close()
		logs = []
		for r in rows:
			logs.append({'question': r[0], 'answer': r[1], 'timestamp': r[2], 'username': r[3]})
		return logs
	except Exception:
		return []

def get_teacher_quiz_results(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr 
			JOIN users u ON qr.user_id = u.id 
			JOIN quizzes q ON qr.quiz_id = q.id 
			WHERE q.teacher_id = ? ORDER BY qr.time DESC LIMIT 100''', (teacher_id,))
		rows = db_cursor.fetchall()
		db_conn.close()
		results = []
		for r in rows:
			try:
				answers = json.loads(r[2])
			except Exception:
				answers = r[2]
			results.append({'score': r[0], 'time': r[1], 'answers': answers, 'username': r[3], 'quiz_title': r[4]})
		return results
	except Exception:
		return []

def get_teacher_performance_data(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT AVG(qr.score) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
		avg_score_row = db_cursor.fetchone()[0]
		avg_score_val = avg_score_row if avg_score_row else 0
		db_cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score >= 80''', (teacher_id,))
		high_count = db_cursor.fetchone()[0]
		db_cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score >= 60 AND qr.score < 80''', (teacher_id,))
		medium_count = db_cursor.fetchone()[0]
		db_cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score < 60''', (teacher_id,))
		low_count = db_cursor.fetchone()[0]
		db_cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
		attempt_count = db_cursor.fetchone()[0]
		db_conn.close()
		return {'labels': ['High (80%+)', 'Medium (60-79%)', 'Low (<60%)'], 'values': [high_count, medium_count, low_count], 'average_score': round(avg_score_val, 1), 'total_attempts': attempt_count}
	except Exception:
		return {'labels': [], 'values': [], 'average_score': 0, 'total_attempts': 0}

def get_teacher_student_stats(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT COUNT(DISTINCT qa.student_id) FROM quiz_assignments qa JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
		total_student_count = db_cursor.fetchone()[0]
		db_cursor.execute('''SELECT COUNT(DISTINCT qr.user_id) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
		active_student_count = db_cursor.fetchone()[0]
		db_conn.close()
		return {'total_students': total_student_count, 'active_students': active_student_count}
	except Exception:
		return {'total_students': 0, 'active_students': 0}

def get_teacher_quiz_stats(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT COUNT(*) FROM quizzes WHERE teacher_id = ?', (teacher_id,))
		quiz_count = db_cursor.fetchone()[0]
		db_cursor.execute('''SELECT COUNT(DISTINCT qr.quiz_id) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''', (teacher_id,))
		completed_count = db_cursor.fetchone()[0]
		db_conn.close()
		return {'total_quizzes': quiz_count, 'completed_quizzes': completed_count}
	except Exception:
		return {'total_quizzes': 0, 'completed_quizzes': 0}

def get_teacher_time_series(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT DATE(qr.time) as date, COUNT(*) as attempts FROM quiz_results qr 
			JOIN quizzes q ON qr.quiz_id = q.id 
			WHERE q.teacher_id = ? AND qr.time >= date('now', '-7 days') 
			GROUP BY DATE(qr.time) ORDER BY date''', (teacher_id,))
		rows = db_cursor.fetchall()
		db_conn.close()
		labels = []
		values = []
		for date, count in rows:
			labels.append(date)
			values.append(count)
		return {'labels': labels, 'values': values}
	except Exception:
		return {'labels': [], 'values': []}

def get_teacher_subject_performance(teacher_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('''SELECT s.name, AVG(qr.score) as avg_score FROM quiz_results qr 
			JOIN quizzes q ON qr.quiz_id = q.id 
			JOIN subjects s ON q.subject_id = s.id 
			WHERE q.teacher_id = ? 
			GROUP BY s.id, s.name 
			ORDER BY avg_score DESC LIMIT 10''', (teacher_id,))
		rows = db_cursor.fetchall()
		db_conn.close()
		labels = []
		values = []
		for name, score in rows:
			labels.append(name)
			values.append(round(score, 1))
		return {'labels': labels, 'values': values}
	except Exception:
		return {'labels': [], 'values': []}
