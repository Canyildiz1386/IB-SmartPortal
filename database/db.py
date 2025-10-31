import sqlite3,hashlib,csv,io,json
DATABASE='smart_study.db'

def _run_query(query,params=None,fetch_one=False,fetch_all=False):
	db=sqlite3.connect(DATABASE)
	cur=db.cursor()
	if params:
		cur.execute(query,params)
	else:
		cur.execute(query)
	if fetch_one:
		row=cur.fetchone()
		db.close()
		return row
	elif fetch_all:
		rows=cur.fetchall()
		db.close()
		return rows
	else:
		db.commit()
		db.close()

def _execute_update(query,params):
	db=sqlite3.connect(DATABASE)
	cur=db.cursor()
	cur.execute(query,params)
	new_id=cur.lastrowid
	db.commit()
	db.close()
	return new_id

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

def get_db_connection():
	return sqlite3.connect(DATABASE)

def _get_conn():
	return sqlite3.connect(DATABASE)

def verify_user(username,password):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		h=hashlib.sha256(password.encode()).hexdigest()
		c.execute('SELECT id, username, role FROM users WHERE username = ? AND password_hash = ?',(username,h))
		u=c.fetchone()
		conn.close()
		if u:
			return {'id':u[0],'username':u[1],'role':u[2]}
		return None
	except Exception:
		return None

def add_user(username,password,role,face_image=None,grade=None):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		h=hashlib.sha256(password.encode()).hexdigest()
		c.execute('INSERT INTO users (username, password_hash, role, face_image, grade) VALUES (?, ?, ?, ?, ?)',(username,h,role,face_image,grade))
		id=c.lastrowid
		conn.commit()
		conn.close()
		return id
	except Exception:
		return None

def get_user_face_image(user_id):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('SELECT face_image FROM users WHERE id = ?',(user_id,))
		r=c.fetchone()
		conn.close()
		if r and r[0]:
			return r[0]
		return None
	except Exception:
		return None

def get_user_grade(user_id):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('SELECT grade FROM users WHERE id = ?',(user_id,))
		r=c.fetchone()
		conn.close()
		if r and r[0]:
			return r[0]
		return None
	except Exception:
		return None

def get_all_users_with_faces():
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('SELECT id, username, role, face_image FROM users WHERE face_image IS NOT NULL AND face_image != ""')
		rows=c.fetchall()
		conn.close()
		users=[]
		for r in rows:
			users.append({'id':r[0],'username':r[1],'role':r[2],'face_image':r[3]})
		return users
	except Exception:
		return []

def update_user_face_image(user_id,face_image_path):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('UPDATE users SET face_image = ? WHERE id = ?',(face_image_path,user_id))
		conn.commit()
		conn.close()
	except Exception:
		pass

def add_mood_tracking(user_id,mood,age=None,gender=None,race=None):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		from datetime import date
		d=date.today().strftime("%Y-%m-%d")
		c.execute('INSERT OR REPLACE INTO mood_tracking (user_id, date, mood, age, gender, race) VALUES (?, ?, ?, ?, ?, ?)',(user_id,d,mood,age,gender,race))
		conn.commit()
		conn.close()
	except Exception:
		pass

def get_user_mood_today(user_id):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		from datetime import date
		d=date.today().strftime("%Y-%m-%d")
		c.execute('SELECT mood FROM mood_tracking WHERE user_id = ? AND date = ?',(user_id,d))
		r=c.fetchone()
		conn.close()
		if r:
			return r[0]
		return None
	except Exception:
		return None

def get_user_mood_history(user_id,limit=30):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT date, mood FROM mood_tracking WHERE user_id = ? ORDER BY date DESC LIMIT ?',(user_id,limit))
		rows=cursor.fetchall()
		conn.close()
		history=[]
		for r in rows:
			history.append({'date':r[0],'mood':r[1]})
		return history
	except Exception:
		return []

def get_all_student_moods():
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('''SELECT u.id, u.username, mt.date, mt.mood, mt.login_time 
			FROM users u 
			LEFT JOIN mood_tracking mt ON u.id = mt.user_id 
			WHERE u.role = 'student' 
			ORDER BY mt.login_time DESC''')
		rows=cursor.fetchall()
		conn.close()
		moods=[]
		for r in rows:
			if r[2]:
				moods.append({'user_id':r[0],'username':r[1],'date':r[2],'mood':r[3],'login_time':r[4]})
		return moods
	except Exception:
		return []

def get_student_moods_by_teacher(teacher_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('''SELECT DISTINCT u.id, u.username, mt.date, mt.mood, mt.login_time 
			FROM users u 
			JOIN user_subjects us1 ON u.id = us1.user_id 
			JOIN user_subjects us2 ON us1.subject_id = us2.subject_id 
			LEFT JOIN mood_tracking mt ON u.id = mt.user_id 
			WHERE u.role = 'student' AND us2.user_id = ? 
			ORDER BY mt.login_time DESC''',(teacher_id,))
		rows=cursor.fetchall()
		conn.close()
		moods=[]
		for r in rows:
			if r[2]:
				moods.append({'user_id':r[0],'username':r[1],'date':r[2],'mood':r[3],'login_time':r[4]})
		return moods
	except Exception:
		return []

def delete_user(user_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('DELETE FROM users WHERE id = ?',(user_id,))
		conn.commit()
		conn.close()
	except Exception:
		pass

def get_all_users():
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('SELECT id, username, role, grade FROM users ORDER BY username')
		rows=c.fetchall()
		conn.close()
		users=[]
		for r in rows:
			users.append({'id':r[0],'username':r[1],'role':r[2],'grade':r[3]})
		return users
	except Exception:
		return []

def add_material(filename,content,subject_id,indexed=0):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		h=hashlib.sha256(content.encode()).hexdigest()
		c.execute('INSERT INTO materials (filename, sha, content, subject_id, indexed) VALUES (?, ?, ?, ?, ?)',(filename,h,content,subject_id,indexed))
		id=c.lastrowid
		conn.commit()
		conn.close()
		return id
	except Exception:
		return None

def get_materials():
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('SELECT * FROM materials ORDER BY upload_time DESC')
		rows=c.fetchall()
		conn.close()
		materials=[]
		for r in rows:
			idx=r[6] if len(r)>6 else 0
			materials.append({'id':r[0],'filename':r[1],'sha':r[2],'content':r[3],'subject_id':r[4],'upload_time':r[5],'indexed':idx})
		return materials
	except Exception:
		return []

def log_qa(user_id,question,answer):
	try:
		conn=get_db_connection()
		c=conn.cursor()
		c.execute('INSERT INTO qa_logs (user_id, question, answer) VALUES (?, ?, ?)',(user_id,question,answer))
		conn.commit()
		conn.close()
	except Exception:
		pass

def get_qa_logs(user_id=None):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		if user_id:
			cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa JOIN users u ON qa.user_id = u.id WHERE qa.user_id = ? ORDER BY qa.timestamp DESC''',(user_id,))
		else:
			cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa JOIN users u ON qa.user_id = u.id ORDER BY qa.timestamp DESC''')
		rows=cursor.fetchall()
		conn.close()
		logs=[]
		for r in rows:
			logs.append({'question':r[0],'answer':r[1],'timestamp':r[2],'username':r[3]})
		return logs
	except Exception:
		return []

def log_quiz_result(user_id,score,answers,quiz_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		answers_json_str=json.dumps(answers)
		cursor.execute('INSERT INTO quiz_results (user_id, quiz_id, score, answers) VALUES (?, ?, ?, ?)',(user_id,quiz_id,score,answers_json_str))
		result_id=cursor.lastrowid
		conn.commit()
		conn.close()
		return result_id
	except Exception:
		return None

def get_quiz_results(user_id=None):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		if user_id:
			cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.user_id = ? ORDER BY qr.time DESC''',(user_id,))
		else:
			cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id ORDER BY qr.time DESC''')
		rows=cursor.fetchall()
		conn.close()
		results=[]
		for r in rows:
			answers=json.loads(r[2])
			results.append({'score':r[0],'time':r[1],'answers':answers,'username':r[3],'quiz_title':r[4]})
		return results
	except Exception:
		return []

def export_quiz_csv(quiz_data):
	try:
		buf=io.StringIO()
		writer=csv.writer(buf)
		writer.writerow(['Question','Option A','Option B','Option C','Option D','Correct Answer'])
		for q in quiz_data:
			writer.writerow([q['question'],q['options'][0],q['options'][1],q['options'][2],q['options'][3],q['correct']])
		return buf.getvalue()
	except Exception:
		return ""

def get_subjects():
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT * FROM subjects ORDER BY name')
		rows=cursor.fetchall()
		conn.close()
		subjects=[]
		for r in rows:
			subjects.append({'id':r[0],'name':r[1]})
		return subjects
	except Exception:
		return []

def get_user_subjects(user_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('''SELECT s.id, s.name FROM subjects s JOIN user_subjects us ON s.id = us.subject_id WHERE us.user_id = ? ORDER BY s.name''',(user_id,))
		rows=cursor.fetchall()
		conn.close()
		subjects=[]
		for r in rows:
			subjects.append({'id':r[0],'name':r[1]})
		return subjects
	except Exception:
		return []

def assign_user_subject(user_id,subject_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('INSERT OR IGNORE INTO user_subjects (user_id, subject_id) VALUES (?, ?)',(user_id,subject_id))
		conn.commit()
		conn.close()
	except Exception:
		pass

def remove_user_subject(user_id,subject_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('DELETE FROM user_subjects WHERE user_id = ? AND subject_id = ?',(user_id,subject_id))
		conn.commit()
		conn.close()
	except Exception:
		pass

def create_quiz(title,subject_id,teacher_id,questions,difficulty='medium'):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		questions_json_str=json.dumps(questions)
		try:
			cursor.execute('INSERT INTO quizzes (title, subject_id, teacher_id, questions, difficulty) VALUES (?, ?, ?, ?, ?)',(title,subject_id,teacher_id,questions_json_str,difficulty))
		except sqlite3.OperationalError:
			cursor.execute('INSERT INTO quizzes (title, subject_id, teacher_id, questions) VALUES (?, ?, ?, ?)',(title,subject_id,teacher_id,questions_json_str))
		quiz_id=cursor.lastrowid
		conn.commit()
		conn.close()
		return quiz_id
	except Exception:
		return None

def assign_quiz_to_students(quiz_id,student_ids):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		for student_id in student_ids:
			cursor.execute('INSERT OR IGNORE INTO quiz_assignments (quiz_id, student_id) VALUES (?, ?)',(quiz_id,student_id))
		conn.commit()
		conn.close()
	except Exception:
		pass

def _parse_quiz_row(row):
	quiz_dict={'id':row[0],'title':row[1],'subject_id':row[2],'teacher_id':row[3],'questions':json.loads(row[4]),'created_at':row[5]}
	if len(row)>6 and row[6]:
		quiz_dict['difficulty']=row[6]
	else:
		quiz_dict['difficulty']='medium'
	return quiz_dict

def get_teacher_quizzes(teacher_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT * FROM quizzes WHERE teacher_id = ? ORDER BY created_at DESC',(teacher_id,))
		rows=cursor.fetchall()
		conn.close()
		quizzes=[]
		for r in rows:
			quizzes.append(_parse_quiz_row(r))
		return quizzes
	except Exception:
		return []

def get_student_quizzes(student_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('''SELECT q.* FROM quizzes q JOIN quiz_assignments qa ON q.id = qa.quiz_id WHERE qa.student_id = ? ORDER BY q.created_at DESC''',(student_id,))
		rows=cursor.fetchall()
		conn.close()
		quizzes=[]
		for r in rows:
			quizzes.append(_parse_quiz_row(r))
		return quizzes
	except Exception:
		return []

def get_quiz_by_id(quiz_id):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT * FROM quizzes WHERE id = ?',(quiz_id,))
		quiz_row=cursor.fetchone()
		conn.close()
		if quiz_row:
			return _parse_quiz_row(quiz_row)
		return None
	except Exception:
		return None

def update_quiz_score(quiz_id,user_id,score):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('UPDATE quiz_results SET score = ? WHERE quiz_id = ? AND user_id = ?',(score,quiz_id,user_id))
		conn.commit()
		conn.close()
	except Exception:
		pass

def get_subjects_with_counts():
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('''SELECT s.id, s.name, COUNT(us.user_id) as user_count FROM subjects s LEFT JOIN user_subjects us ON s.id = us.subject_id GROUP BY s.id, s.name ORDER BY s.name''')
		rows=cursor.fetchall()
		conn.close()
		subjects=[]
		for r in rows:
			subjects.append({'id':r[0],'name':r[1],'user_count':r[2]})
		return subjects
	except Exception:
		return []

def get_non_indexed_materials():
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT * FROM materials WHERE indexed = 0 ORDER BY upload_time DESC')
		rows=cursor.fetchall()
		conn.close()
		materials=[]
		for r in rows:
			indexed=r[6] if len(r)>6 else 0
			materials.append({'id':r[0],'filename':r[1],'sha':r[2],'content':r[3],'subject_id':r[4],'upload_time':r[5],'indexed':indexed})
		return materials
	except Exception:
		return []

def update_material_indexed_status(material_id,indexed=1):
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('UPDATE materials SET indexed = ? WHERE id = ?',(indexed,material_id))
		conn.commit()
		conn.close()
	except Exception:
		pass
