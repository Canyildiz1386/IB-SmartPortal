import sqlite3,hashlib,csv,io,json
DATABASE='smart_study.db'

def init_db():
	conn=sqlite3.connect(DATABASE)
	cursor=conn.cursor()
	cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'student',face_image TEXT,grade TEXT)''')
	try:cursor.execute('ALTER TABLE users ADD COLUMN face_image TEXT')
	except sqlite3.OperationalError:pass
	try:cursor.execute('ALTER TABLE users ADD COLUMN grade TEXT')
	except sqlite3.OperationalError:pass
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS subjects (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL)''')
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS user_subjects (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,subject_id INTEGER,FOREIGN KEY (user_id) REFERENCES users (id),FOREIGN KEY (subject_id) REFERENCES subjects (id))''')
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY AUTOINCREMENT,filename TEXT NOT NULL,sha TEXT NOT NULL,content TEXT,subject_id INTEGER,upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (subject_id) REFERENCES subjects (id))''')
    
	try:cursor.execute('ALTER TABLE materials ADD COLUMN content TEXT')
	except sqlite3.OperationalError:pass
	try:cursor.execute('ALTER TABLE materials ADD COLUMN indexed INTEGER DEFAULT 0')
	except sqlite3.OperationalError:pass
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS qa_logs (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,question TEXT NOT NULL,answer TEXT NOT NULL,timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users (id))''')
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS quizzes (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,subject_id INTEGER,teacher_id INTEGER,questions TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (subject_id) REFERENCES subjects (id),FOREIGN KEY (teacher_id) REFERENCES users (id))''')
	try:cursor.execute('ALTER TABLE quizzes ADD COLUMN difficulty TEXT DEFAULT "medium"')
	except sqlite3.OperationalError:pass
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS quiz_assignments (id INTEGER PRIMARY KEY AUTOINCREMENT,quiz_id INTEGER,student_id INTEGER,assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (quiz_id) REFERENCES quizzes (id),FOREIGN KEY (student_id) REFERENCES users (id))''')
    
	cursor.execute('''CREATE TABLE IF NOT EXISTS quiz_results (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,quiz_id INTEGER,score REAL NOT NULL,answers TEXT NOT NULL,time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users (id),FOREIGN KEY (quiz_id) REFERENCES quizzes (id))''')
	
	cursor.execute('''CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,title TEXT NOT NULL,content TEXT NOT NULL,subject_id INTEGER,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users (id),FOREIGN KEY (subject_id) REFERENCES subjects (id))''')
    
	try:cursor.execute('ALTER TABLE quiz_results ADD COLUMN quiz_id INTEGER')
	except:pass
	try:cursor.execute('ALTER TABLE quiz_results ADD COLUMN score REAL')
	except:pass
	
	cursor.execute('''CREATE TABLE IF NOT EXISTS mood_tracking (id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,date DATE NOT NULL,mood TEXT NOT NULL,age INTEGER,gender TEXT,race TEXT,login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (user_id) REFERENCES users (id),UNIQUE(user_id, date))''')
	
	cursor.execute('''CREATE TABLE IF NOT EXISTS study_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,host_id INTEGER NOT NULL,title TEXT NOT NULL,subject_id INTEGER,description TEXT,max_participants INTEGER DEFAULT 10,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,is_active INTEGER DEFAULT 1,FOREIGN KEY (host_id) REFERENCES users (id),FOREIGN KEY (subject_id) REFERENCES subjects (id))''')
	
	cursor.execute('''CREATE TABLE IF NOT EXISTS session_participants (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER NOT NULL,user_id INTEGER NOT NULL,joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (session_id) REFERENCES study_sessions (id),FOREIGN KEY (user_id) REFERENCES users (id),UNIQUE(session_id, user_id))''')
	
	cursor.execute('''CREATE TABLE IF NOT EXISTS session_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,session_id INTEGER NOT NULL,user_id INTEGER NOT NULL,message TEXT NOT NULL,timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY (session_id) REFERENCES study_sessions (id),FOREIGN KEY (user_id) REFERENCES users (id))''')
    
	cursor.execute('SELECT COUNT(*) FROM subjects')
	if cursor.fetchone()[0]==0:
		default_subjects=['Mathematics','Physics','Chemistry','Biology','English','History','Geography','Economics','Computer Science','Art']
		for subject in default_subjects:cursor.execute('INSERT INTO subjects (name) VALUES (?)',(subject,))
    
	cursor.execute('DELETE FROM users WHERE username IN (?, ?, ?)',('admin','teacher','student'))
	cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?',('canyildiz1386',))
	if cursor.fetchone()[0]==0:
		admin_password=hashlib.sha256('root'.encode()).hexdigest()
		cursor.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',('canyildiz1386',admin_password,'admin'))
	conn.commit()
	conn.close()

def get_db_connection():return sqlite3.connect(DATABASE)

def verify_user(username,password):
	conn=get_db_connection()
	cursor=conn.cursor()
	password_hash=hashlib.sha256(password.encode()).hexdigest()
	cursor.execute('SELECT id, username, role FROM users WHERE username = ? AND password_hash = ?',(username,password_hash))
	user=cursor.fetchone()
	conn.close()
	if user:return {'id':user[0],'username':user[1],'role':user[2]}
	return None

def add_user(username,password,role,face_image=None,grade=None):
	conn=get_db_connection()
	cursor=conn.cursor()
	password_hash=hashlib.sha256(password.encode()).hexdigest()
	cursor.execute('INSERT INTO users (username, password_hash, role, face_image, grade) VALUES (?, ?, ?, ?, ?)',(username,password_hash,role,face_image,grade))
	user_id=cursor.lastrowid
	conn.commit()
	conn.close()
	return user_id

def get_user_face_image(user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT face_image FROM users WHERE id = ?',(user_id,))
	result=cursor.fetchone()
	conn.close()
	return result[0] if result and result[0] else None

def get_user_grade(user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT grade FROM users WHERE id = ?',(user_id,))
	result=cursor.fetchone()
	conn.close()
	return result[0] if result and result[0] else None

def get_all_users_with_faces():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, username, role, face_image FROM users WHERE face_image IS NOT NULL AND face_image != ""')
	users=[{'id':row[0],'username':row[1],'role':row[2],'face_image':row[3]} for row in cursor.fetchall()]
	conn.close()
	return users

def update_user_face_image(user_id,face_image_path):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('UPDATE users SET face_image = ? WHERE id = ?',(face_image_path,user_id))
	conn.commit()
	conn.close()

def add_mood_tracking(user_id,mood,age=None,gender=None,race=None):
	conn=get_db_connection()
	cursor=conn.cursor()
	from datetime import date
	today=date.today().strftime("%Y-%m-%d")
	cursor.execute('INSERT OR REPLACE INTO mood_tracking (user_id, date, mood, age, gender, race) VALUES (?, ?, ?, ?, ?, ?)',(user_id,today,mood,age,gender,race))
	conn.commit()
	conn.close()

def get_user_mood_today(user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	from datetime import date
	today=date.today().strftime("%Y-%m-%d")
	cursor.execute('SELECT mood FROM mood_tracking WHERE user_id = ? AND date = ?',(user_id,today))
	result=cursor.fetchone()
	conn.close()
	return result[0] if result else None

def get_user_mood_history(user_id,limit=30):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT date, mood FROM mood_tracking WHERE user_id = ? ORDER BY date DESC LIMIT ?',(user_id,limit))
	results=cursor.fetchall()
	conn.close()
	return [{'date':row[0],'mood':row[1]} for row in results]

def get_all_student_moods():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT u.id, u.username, mt.date, mt.mood, mt.login_time 
		FROM users u 
		LEFT JOIN mood_tracking mt ON u.id = mt.user_id 
		WHERE u.role = 'student' 
		ORDER BY mt.login_time DESC''')
	results=cursor.fetchall()
	conn.close()
	return [{'user_id':row[0],'username':row[1],'date':row[2],'mood':row[3],'login_time':row[4]} for row in results if row[2]]

def get_student_moods_by_teacher(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT DISTINCT u.id, u.username, mt.date, mt.mood, mt.login_time 
		FROM users u 
		JOIN user_subjects us1 ON u.id = us1.user_id 
		JOIN user_subjects us2 ON us1.subject_id = us2.subject_id 
		LEFT JOIN mood_tracking mt ON u.id = mt.user_id 
		WHERE u.role = 'student' AND us2.user_id = ? 
		ORDER BY mt.login_time DESC''',(teacher_id,))
	results=cursor.fetchall()
	conn.close()
	return [{'user_id':row[0],'username':row[1],'date':row[2],'mood':row[3],'login_time':row[4]} for row in results if row[2]]

def delete_user(user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('DELETE FROM users WHERE id = ?',(user_id,))
	conn.commit()
	conn.close()

def get_all_users():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, username, role, grade FROM users ORDER BY username')
	users=[{'id':row[0],'username':row[1],'role':row[2],'grade':row[3]} for row in cursor.fetchall()]
	conn.close()
	return users

def add_material(filename,content,subject_id,indexed=0):
	conn=get_db_connection()
	cursor=conn.cursor()
	sha=hashlib.sha256(content.encode()).hexdigest()
	cursor.execute('INSERT INTO materials (filename, sha, content, subject_id, indexed) VALUES (?, ?, ?, ?, ?)',(filename,sha,content,subject_id,indexed))
	material_id=cursor.lastrowid
	conn.commit()
	conn.close()
	return material_id

def get_materials():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM materials ORDER BY upload_time DESC')
	rows=cursor.fetchall()
	materials=[{'id':row[0],'filename':row[1],'sha':row[2],'content':row[3],'subject_id':row[4],'upload_time':row[5],'indexed':row[6] if len(row)>6 else 0} for row in rows]
	conn.close()
	return materials

def log_qa(user_id,question,answer):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('INSERT INTO qa_logs (user_id, question, answer) VALUES (?, ?, ?)',(user_id,question,answer))
	conn.commit()
	conn.close()

def get_qa_logs(user_id=None):
	conn=get_db_connection()
	cursor=conn.cursor()
	if user_id:
		cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa JOIN users u ON qa.user_id = u.id WHERE qa.user_id = ? ORDER BY qa.timestamp DESC''',(user_id,))
	else:
		cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa JOIN users u ON qa.user_id = u.id ORDER BY qa.timestamp DESC''')
	logs=[{'question':row[0],'answer':row[1],'timestamp':row[2],'username':row[3]} for row in cursor.fetchall()]
	conn.close()
	return logs

def log_quiz_result(user_id,score,answers,quiz_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	answers_json=json.dumps(answers)
	cursor.execute('INSERT INTO quiz_results (user_id, quiz_id, score, answers) VALUES (?, ?, ?, ?)',(user_id,quiz_id,score,answers_json))
	result_id=cursor.lastrowid
	conn.commit()
	conn.close()
	return result_id

def get_quiz_results(user_id=None):
	conn=get_db_connection()
	cursor=conn.cursor()
	if user_id:
		cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.user_id = ? ORDER BY qr.time DESC''',(user_id,))
	else:
		cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id ORDER BY qr.time DESC''')
	results=[{'score':row[0],'time':row[1],'answers':json.loads(row[2]),'username':row[3],'quiz_title':row[4]} for row in cursor.fetchall()]
	conn.close()
	return results

def export_quiz_csv(quiz_data):
	output=io.StringIO()
	writer=csv.writer(output)
	writer.writerow(['Question','Option A','Option B','Option C','Option D','Correct Answer'])
	for question in quiz_data:
		writer.writerow([question['question'],question['options'][0],question['options'][1],question['options'][2],question['options'][3],question['correct']])
	return output.getvalue()

def get_subjects():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM subjects ORDER BY name')
	subjects=[{'id':row[0],'name':row[1]} for row in cursor.fetchall()]
	conn.close()
	return subjects

def get_user_subjects(user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT s.id, s.name FROM subjects s JOIN user_subjects us ON s.id = us.subject_id WHERE us.user_id = ? ORDER BY s.name''',(user_id,))
	subjects=[{'id':row[0],'name':row[1]} for row in cursor.fetchall()]
	conn.close()
	return subjects

def assign_user_subject(user_id,subject_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('INSERT OR IGNORE INTO user_subjects (user_id, subject_id) VALUES (?, ?)',(user_id,subject_id))
	conn.commit()
	conn.close()

def remove_user_subject(user_id,subject_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('DELETE FROM user_subjects WHERE user_id = ? AND subject_id = ?',(user_id,subject_id))
	conn.commit()
	conn.close()

def create_quiz(title,subject_id,teacher_id,questions,difficulty='medium'):
	conn=get_db_connection()
	cursor=conn.cursor()
	questions_json=json.dumps(questions)
	try:
		cursor.execute('INSERT INTO quizzes (title, subject_id, teacher_id, questions, difficulty) VALUES (?, ?, ?, ?, ?)',(title,subject_id,teacher_id,questions_json,difficulty))
	except sqlite3.OperationalError:
		cursor.execute('INSERT INTO quizzes (title, subject_id, teacher_id, questions) VALUES (?, ?, ?, ?)',(title,subject_id,teacher_id,questions_json))
	quiz_id=cursor.lastrowid
	conn.commit()
	conn.close()
	return quiz_id

def assign_quiz_to_students(quiz_id,student_ids):
	conn=get_db_connection()
	cursor=conn.cursor()
	for student_id in student_ids:cursor.execute('INSERT OR IGNORE INTO quiz_assignments (quiz_id, student_id) VALUES (?, ?)',(quiz_id,student_id))
	conn.commit()
	conn.close()

def get_teacher_quizzes(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM quizzes WHERE teacher_id = ? ORDER BY created_at DESC',(teacher_id,))
	quizzes=[]
	for row in cursor.fetchall():
		quiz={'id':row[0],'title':row[1],'subject_id':row[2],'teacher_id':row[3],'questions':json.loads(row[4]),'created_at':row[5]}
		if len(row)>6:
			quiz['difficulty']=row[6] if row[6] else 'medium'
		else:
			quiz['difficulty']='medium'
		quizzes.append(quiz)
	conn.close()
	return quizzes

def get_student_quizzes(student_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT q.* FROM quizzes q JOIN quiz_assignments qa ON q.id = qa.quiz_id WHERE qa.student_id = ? ORDER BY q.created_at DESC''',(student_id,))
	quizzes=[]
	for row in cursor.fetchall():
		quiz={'id':row[0],'title':row[1],'subject_id':row[2],'teacher_id':row[3],'questions':json.loads(row[4]),'created_at':row[5]}
		if len(row)>6:
			quiz['difficulty']=row[6] if row[6] else 'medium'
		else:
			quiz['difficulty']='medium'
		quizzes.append(quiz)
	conn.close()
	return quizzes

def get_quiz_by_id(quiz_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM quizzes WHERE id = ?',(quiz_id,))
	row=cursor.fetchone()
	conn.close()
	if row:
		quiz={'id':row[0],'title':row[1],'subject_id':row[2],'teacher_id':row[3],'questions':json.loads(row[4]),'created_at':row[5]}
		if len(row)>6:
			quiz['difficulty']=row[6] if row[6] else 'medium'
		else:
			quiz['difficulty']='medium'
		return quiz
	return None

def update_quiz_score(quiz_id,user_id,score):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('UPDATE quiz_results SET score = ? WHERE quiz_id = ? AND user_id = ?',(score,quiz_id,user_id))
	conn.commit()
	conn.close()

def get_subjects_with_counts():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT s.id, s.name, COUNT(us.user_id) as user_count FROM subjects s LEFT JOIN user_subjects us ON s.id = us.subject_id GROUP BY s.id, s.name ORDER BY s.name''')
	subjects=[{'id':row[0],'name':row[1],'user_count':row[2]} for row in cursor.fetchall()]
	return subjects

def get_non_indexed_materials():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM materials WHERE indexed = 0 ORDER BY upload_time DESC')
	rows=cursor.fetchall()
	materials=[{'id':row[0],'filename':row[1],'sha':row[2],'content':row[3],'subject_id':row[4],'upload_time':row[5],'indexed':row[6] if len(row)>6 else 0} for row in rows]
	conn.close()
	return materials

def update_material_indexed_status(material_id,indexed=1):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('UPDATE materials SET indexed = ? WHERE id = ?',(indexed,material_id))
	conn.commit()
	conn.close()

