import os,uuid,json,hashlib,time
from flask import Flask,render_template,request,redirect,url_for,session,flash,jsonify,make_response
from werkzeug.utils import secure_filename
from db import init_db,verify_user,add_material,log_qa,get_materials,add_user,delete_user,get_all_users,log_quiz_result,get_qa_logs,get_quiz_results,export_quiz_csv,get_subjects,get_user_subjects,assign_user_subject,remove_user_subject,create_quiz,assign_quiz_to_students,get_teacher_quizzes,get_student_quizzes,get_quiz_by_id,update_quiz_score,get_db_connection,get_non_indexed_materials,update_material_indexed_status
from auth import login_required,admin_required,teacher_required,login_user,logout_user,get_current_user
from rag import SmartStudyRAG

app=Flask(__name__)
app.secret_key='IB-Smartportal'
UPLOAD_FOLDER='uploads'
ALLOWED_EXTENSIONS={'pdf','txt'}
MAX_FILE_SIZE=10*1024*1024
os.makedirs(UPLOAD_FOLDER,exist_ok=True)
rag_system=None

def allowed_file(filename):return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def init_rag_system():
	global rag_system
	if rag_system is None:
		api_key=os.getenv('COHERE_API_KEY')
		if not api_key:
			print("Warning: COHERE_API_KEY not set. RAG features will be limited.")
			api_key="dummy_key_for_development"
		rag_system=SmartStudyRAG(api_key)
	try:
		materials=get_materials()
		if materials:rag_system.rebuild_from_db(materials)
	except:pass
	return rag_system

@app.route('/')
def index():
	if 'user_id' in session:
		user=get_current_user()
		return redirect(url_for('student_quizzes') if user['role']=='student' else 'upload')
	return redirect(url_for('login'))

@app.route('/login',methods=['GET','POST'])
def login():
	if request.method=='POST':
		username,password=request.form['username'],request.form['password']
		user=verify_user(username,password)
		if user:
			login_user(user)
			return redirect(url_for('index'))
		else:flash('Invalid username or password.','error')
	return render_template('login.html')

@app.route('/logout')
def logout():
	logout_user()
	return redirect(url_for('login'))

@app.route('/upload',methods=['GET','POST'])
@login_required
def upload():
	user=get_current_user()
	if user['role']=='student':
		flash('Students cannot upload files. Only teachers and admins can upload materials.','error')
		return redirect(url_for('index'))
	global rag_system
	init_rag_system()
	if request.method=='POST':
		# Rate limiting: Check if user uploaded within last 2 minutes
		last_upload=session.get('last_upload_time',0)
		current_time=time.time()
		time_diff=current_time-last_upload
		if time_diff<120:  # 2 minutes = 120 seconds
			remaining_time=120-int(time_diff)
			flash(f'Upload rate limit: Please wait {remaining_time} seconds before uploading again.','error')
			return redirect(url_for('upload'))
		files,subject_id=request.files.getlist('files'),request.form.get('subject_id')
		if not files or all(file.filename=='' for file in files):
			flash('No files selected.','error')
			return redirect(url_for('upload'))
		if not subject_id:
			flash('Please select a subject.','error')
			return redirect(url_for('upload'))
		uploaded_files,file_contents=[],[]
		for file in files:
			if file and allowed_file(file.filename):
				file.seek(0,os.SEEK_END)
				file_size=file.tell()
				file.seek(0)
				if file_size>MAX_FILE_SIZE:
					flash(f'File {file.filename} too large.','error')
					continue
				filename=secure_filename(file.filename)
				unique_filename=f"{uuid.uuid4()}_{filename}"
				file_path=os.path.join(UPLOAD_FOLDER,unique_filename)
				file.save(file_path)
				content=rag_system.extract_pdf(file_path) if filename.lower().endswith('.pdf') else rag_system.extract_txt(file_path)
				if content.strip():
					uploaded_files.append(file_path)
					file_contents.append(content)
					add_material(filename,content,subject_id,indexed=0)  # Mark as not indexed initially
				else:
					os.remove(file_path)
					flash(f'Could not extract text from {filename}.','error')
			else:flash(f'Invalid file format: {file.filename}.','error')
		if uploaded_files:
			try:
				materials=get_materials()
				rag_system.rebuild_from_db(materials)
				# Mark all uploaded materials as indexed
				for material in materials:
					if material['filename'] in [secure_filename(f.filename) for f in files if f and allowed_file(f.filename)]:
						update_material_indexed_status(material['id'],indexed=1)
				session['last_upload_time']=time.time()  # Update upload timestamp
				session.modified=True
				flash(f'Uploaded and indexed {len(uploaded_files)} file(s) for subject.','success')
			except Exception as e:
				flash(f'Error building index: {str(e)}','error')
				# Mark indexing as failed - files remain as not indexed
		return redirect(url_for('upload'))
	materials,subjects=get_materials(),get_subjects()
	return render_template('index.html',materials=materials,subjects=subjects)

@app.route('/reindex',methods=['POST'])
@login_required
def reindex_files():
	user=get_current_user()
	if user['role']=='student':
		flash('Students cannot re-index files. Only teachers and admins can manage materials.','error')
		return redirect(url_for('index'))
	global rag_system
	try:
		init_rag_system()
		non_indexed_materials=get_non_indexed_materials()
		if non_indexed_materials:
			# Rebuild with all materials but only mark non-indexed ones as processed
			all_materials=get_materials()
			rag_system.rebuild_from_db(all_materials)
			# Mark the previously non-indexed materials as now indexed
			for material in non_indexed_materials:
				update_material_indexed_status(material['id'],indexed=1)
			flash(f'Successfully indexed {len(non_indexed_materials)} file(s) that had indexing problems!','success')
		else:
			flash('All files are already properly indexed!','info')
	except Exception as e:
		flash(f'Error re-indexing files: {str(e)}','error')
	return redirect(url_for('upload'))

@app.route('/chat',methods=['GET','POST'])
@login_required
def chat():
	global rag_system
	init_rag_system()
	if rag_system is None or not rag_system.chunks:
		flash('No materials indexed yet.','warning')
		return redirect(url_for('upload'))
	if request.method=='POST':
		question=request.form['question'].strip()
		if question:
			try:
				answer,sources=rag_system.query(question,top_k=3)
				log_qa(session['user_id'],question,answer)
				if 'chat_history' not in session:session['chat_history']=[]
				session['chat_history'].insert(0,{'question':question,'answer':answer,'sources':sources})
				if len(session['chat_history'])>10:session['chat_history']=session['chat_history'][:10]
				session.modified=True
			except Exception as e:flash(f'Error generating answer: {str(e)}','error')
	chat_history=session.get('chat_history',[])
	return render_template('chat.html',chat_history=chat_history)

@app.route('/quiz',methods=['GET','POST'])
@login_required
def quiz():
	global rag_system
	init_rag_system()
	if request.method=='POST':
		num_questions,description=int(request.form.get('num_questions',5)),request.form.get('description','')
		try:
			quiz_questions=rag_system.generate_quiz(num_questions,description)
			if quiz_questions:
				session['current_quiz']=quiz_questions
				session.modified=True
				return render_template('quiz.html',quiz=quiz_questions,show_quiz=True)
			else:flash('Failed to generate quiz questions.','error')
		except Exception as e:flash(f'Error generating quiz: {str(e)}','error')
	current_quiz=session.get('current_quiz',[])
	if current_quiz:return render_template('quiz.html',quiz=current_quiz,show_quiz=True)
	return render_template('quiz.html',show_quiz=False)

@app.route('/export_quiz')
@login_required
def export_quiz():
	current_quiz=session.get('current_quiz',[])
	if not current_quiz:
		flash('No quiz to export.','error')
		return redirect(url_for('quiz'))
	csv_data=export_quiz_csv(current_quiz)
	response=make_response(csv_data)
	response.headers['Content-Type']='text/csv'
	response.headers['Content-Disposition']='attachment; filename=quiz_export.csv'
	return response

@app.route('/admin',methods=['GET','POST'])
@admin_required
def admin():
	if request.method=='POST':
		username,password,role,subject_ids=request.form['username'],request.form['password'],request.form['role'],request.form.getlist('subject_ids')
		try:
			user_id=add_user(username,password,role)
			if subject_ids and role in ['student','teacher']:
				for subject_id in subject_ids:assign_user_subject(user_id,subject_id)
			flash(f'User {username} created successfully!','success')
		except Exception as e:flash(f'Error creating user: {str(e)}','error')
	users,subjects=get_all_users(),get_subjects()
	return render_template('admin.html',users=users,subjects=subjects)

@app.route('/delete_user/<int:user_id>')
@admin_required
def delete_user_route(user_id):
	if user_id==session['user_id']:flash('Cannot delete your own account.','error')
	else:
		delete_user(user_id)
		flash('User deleted successfully.','success')
	return redirect(url_for('admin'))

@app.route('/progress')
@login_required
def progress():
	user=get_current_user()
	if user['role'] in ['admin','teacher']:
		qa_logs,quiz_results=get_qa_logs(),get_quiz_results()
	else:
		qa_logs,quiz_results=get_qa_logs(user['id']),get_quiz_results(user['id'])
	return render_template('progress.html',qa_logs=qa_logs,quiz_results=quiz_results)

@app.route('/subjects')
@login_required
def subjects():
	user=get_current_user()
	user_subjects,all_subjects=get_user_subjects(user['id']),get_subjects()
	return render_template('subjects.html',user_subjects=user_subjects,all_subjects=all_subjects)

@app.route('/assign_subject',methods=['POST'])
@login_required
def assign_subject():
	user,action,subject_id=get_current_user(),request.form.get('action',''),request.form.get('subject_id')
	if not subject_id:
		flash('Subject ID is required.','error')
		return redirect(url_for('subjects'))
	try:subject_id=int(subject_id)
	except ValueError:
		flash('Invalid subject ID.','error')
		return redirect(url_for('subjects'))
	if action=='assign':
		assign_user_subject(user['id'],subject_id)
		flash('Subject assigned successfully!','success')
	elif action=='remove':
		remove_user_subject(user['id'],subject_id)
		flash('Subject removed successfully!','success')
	else:flash('Invalid action.','error')
	return redirect(url_for('subjects'))

@app.route('/create_quiz',methods=['GET','POST'])
@teacher_required
def create_quiz_route():
	if request.method=='POST':
		title,subject_id,description,num_questions=request.form['title'],request.form['subject_id'],request.form['description'],int(request.form.get('num_questions',5))
		try:
			init_rag_system()
			quiz_questions=rag_system.generate_quiz(num_questions,description,subject_id)
			if quiz_questions:
				quiz_id=create_quiz(title,subject_id,session['user_id'],quiz_questions)
				flash(f'Quiz "{title}" created successfully!','success')
				return redirect(url_for('assign_quiz',quiz_id=quiz_id))
			else:flash('Failed to generate quiz questions.','error')
		except Exception as e:flash(f'Error creating quiz: {str(e)}','error')
	teacher_subjects=get_user_subjects(session['user_id'])
	return render_template('create_quiz.html',subjects=teacher_subjects)

@app.route('/assign_quiz/<int:quiz_id>',methods=['GET','POST'])
@teacher_required
def assign_quiz(quiz_id):
	quiz=get_quiz_by_id(quiz_id)
	if not quiz or quiz['teacher_id']!=session['user_id']:
		flash('Quiz not found.','error')
		return redirect(url_for('my_quizzes'))
	if request.method=='POST':
		student_ids=request.form.getlist('student_ids')
		if student_ids:
			assign_quiz_to_students(quiz_id,student_ids)
			flash('Quiz assigned successfully!','success')
			return redirect(url_for('my_quizzes'))
		else:flash('Please select at least one student.','error')
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, username FROM users WHERE role = "student"')
	students=[{'id':row[0],'username':row[1]} for row in cursor.fetchall()]
	conn.close()
	return render_template('assign_quiz.html',quiz=quiz,students=students)

@app.route('/my_quizzes')
@teacher_required
def my_quizzes():
	quizzes=get_teacher_quizzes(session['user_id'])
	return render_template('my_quizzes.html',quizzes=quizzes)

@app.route('/student_quizzes')
@login_required
def student_quizzes():
	user=get_current_user()
	if user['role']!='student':
		flash('Access denied.','error')
		return redirect(url_for('index'))
	quizzes=get_student_quizzes(user['id'])
	return render_template('student_quizzes.html',quizzes=quizzes)

@app.route('/take_quiz/<int:quiz_id>',methods=['GET','POST'])
@login_required
def take_quiz(quiz_id):
	user=get_current_user()
	if user['role']!='student':
		flash('Access denied.','error')
		return redirect(url_for('index'))
	quiz=get_quiz_by_id(quiz_id)
	if not quiz:
		flash('Quiz not found.','error')
		return redirect(url_for('student_quizzes'))
	try:
		questions=json.loads(quiz['questions']) if isinstance(quiz['questions'],str) else quiz['questions']
	except (TypeError,json.JSONDecodeError):
		questions=quiz['questions']
	if request.method=='POST':
		answers,correct_count=[],0
		for i,question in enumerate(questions):
			answer_key=f'q{i}'
			user_answer=request.form.get(answer_key,'').strip().upper()
			correct_answer=question['correct'].strip().upper()
			if user_answer==correct_answer:correct_count+=1
			answers.append({'question':question['question'],'user_answer':user_answer,'correct_answer':correct_answer,'is_correct':user_answer==correct_answer})
		score=(correct_count/len(questions))*100
		log_quiz_result(user['id'],score,answers,quiz_id)
		update_quiz_score(quiz_id,user['id'],score)
		return render_template('quiz_results.html',quiz=quiz,score=score,total=len(questions),correct=correct_count,percentage=round(score,1),answers=answers)
	return render_template('take_quiz.html',quiz=quiz,questions=questions)

@app.route('/dashboard')
@login_required
def dashboard():
	user=get_current_user()
	if user['role']=='admin':
		stats,recent_activities=get_admin_stats(),get_recent_activities()
	elif user['role']=='teacher':
		stats,recent_activities=get_teacher_stats(user['id']),get_teacher_recent_activities(user['id'])
	else:
		flash('Access denied.','error')
		return redirect(url_for('index'))
	user_distribution,performance_data,subject_activity,time_series_data,score_distribution=get_user_distribution(),get_performance_data(),get_subject_activity(),get_time_series_data(),get_score_distribution()
	return render_template('dashboard.html',stats=stats,recent_activities=recent_activities,user_distribution=user_distribution,performance_data=performance_data,subject_activity=subject_activity,time_series_data=time_series_data,score_distribution=score_distribution)

@app.route('/profile')
@login_required
def profile():
	user=get_current_user()
	user_subjects=get_user_subjects(user['id'])
	return render_template('profile.html',user=user,user_subjects=user_subjects)

@app.route('/change_password',methods=['POST'])
@login_required
def change_password():
	current_password,new_password,confirm_password=request.form['current_password'],request.form['new_password'],request.form['confirm_password']
	user=get_current_user()
	if not verify_user(user['username'],current_password):
		flash('Current password is incorrect.','error')
		return redirect(url_for('profile'))
	if new_password!=confirm_password:
		flash('New passwords do not match.','error')
		return redirect(url_for('profile'))
	if len(new_password)<6:
		flash('Password must be at least 6 characters long.','error')
		return redirect(url_for('profile'))
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('UPDATE users SET password = ? WHERE id = ?',(hashlib.sha256(new_password.encode()).hexdigest(),user['id']))
	conn.commit()
	conn.close()
	flash('Password changed successfully!','success')
	return redirect(url_for('profile'))

@app.route('/manage_subjects')
@admin_required
def manage_subjects():
	subjects=get_subjects()
	return render_template('manage_subjects.html',subjects=subjects)

@app.route('/add_subject',methods=['POST'])
@admin_required
def add_subject():
	name=request.form['name'].strip()
	if name:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('INSERT INTO subjects (name) VALUES (?)',(name,))
		conn.commit()
		conn.close()
		flash(f'Subject "{name}" added successfully!','success')
	else:flash('Subject name cannot be empty.','error')
	return redirect(url_for('manage_subjects'))

@app.route('/edit_subject/<int:subject_id>',methods=['GET','POST'])
@admin_required
def edit_subject(subject_id):
	if request.method=='POST':
		name=request.form['name'].strip()
		if name:
			conn=get_db_connection()
			cursor=conn.cursor()
			cursor.execute('UPDATE subjects SET name = ? WHERE id = ?',(name,subject_id))
			conn.commit()
			conn.close()
			flash(f'Subject updated successfully!','success')
			return redirect(url_for('manage_subjects'))
		else:flash('Subject name cannot be empty.','error')
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM subjects WHERE id = ?',(subject_id,))
	subject=cursor.fetchone()
	conn.close()
	if not subject:
		flash('Subject not found.','error')
		return redirect(url_for('manage_subjects'))
	return render_template('edit_subject.html',subject=subject)

@app.route('/delete_subject/<int:subject_id>')
@admin_required
def delete_subject(subject_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('DELETE FROM subjects WHERE id = ?',(subject_id,))
	conn.commit()
	conn.close()
	flash('Subject deleted successfully!','success')
	return redirect(url_for('manage_subjects'))

def get_admin_stats():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT COUNT(*) FROM users')
	total_users=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM users WHERE role = "student"')
	total_students=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM users WHERE role = "teacher"')
	total_teachers=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM materials')
	total_materials=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM quizzes')
	total_quizzes=cursor.fetchone()[0]
	cursor.execute('SELECT AVG(score) FROM quiz_results')
	avg_score=cursor.fetchone()[0] or 0
	conn.close()
	return {'total_users':total_users,'total_students':total_students,'total_teachers':total_teachers,'total_materials':total_materials,'total_quizzes':total_quizzes,'avg_score':round(avg_score,1)}

def get_teacher_stats(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT COUNT(*) FROM quizzes WHERE teacher_id = ?',(teacher_id,))
	total_quizzes=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(DISTINCT qa.student_id) FROM quiz_assignments qa JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?',(teacher_id,))
	active_students=cursor.fetchone()[0]
	cursor.execute('SELECT AVG(qr.score) FROM quiz_results qr JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?',(teacher_id,))
	avg_score=cursor.fetchone()[0] or 0
	cursor.execute('SELECT COUNT(*) FROM quiz_results qr JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?',(teacher_id,))
	total_attempts=cursor.fetchone()[0]
	conn.close()
	return {'total_quizzes':total_quizzes,'active_students':active_students,'avg_score':round(avg_score,1),'total_attempts':total_attempts}

def get_recent_activities():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT u.username, qr.score, qr.time, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quizzes q ON qr.quiz_id = q.id ORDER BY qr.time DESC LIMIT 10''')
	activities=[{'username':row[0],'score':row[1],'time':row[2],'quiz_title':row[3]} for row in cursor.fetchall()]
	conn.close()
	return activities

def get_teacher_recent_activities(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT u.username, qr.score, qr.time, q.title FROM quiz_results qr JOIN users u ON qr.user_id = u.id JOIN quiz_assignments qa ON qr.quiz_id = qa.quiz_id JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ? ORDER BY qr.time DESC LIMIT 10''',(teacher_id,))
	activities=[{'username':row[0],'score':row[1],'time':row[2],'quiz_title':row[3]} for row in cursor.fetchall()]
	conn.close()
	return activities

def get_user_distribution():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT role, COUNT(*) FROM users GROUP BY role')
	roles=cursor.fetchall()
	labels,values=[role.title() for role,count in roles],[count for role,count in roles]
	conn.close()
	return {'labels':labels,'values':values}

def get_performance_data():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT AVG(score) FROM quiz_results')
	avg_score=cursor.fetchone()[0] or 0
	cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score >= 80')
	high_scores=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score >= 60 AND score < 80')
	medium_scores=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE score < 60')
	low_scores=cursor.fetchone()[0]
	cursor.execute('SELECT COUNT(*) FROM quiz_results')
	total_attempts=cursor.fetchone()[0]
	return {'labels':['High (80%+)','Medium (60-79%)','Low (<60%)'],'values':[high_scores,medium_scores,low_scores],'average_score':round(avg_score,1),'total_attempts':total_attempts}

def get_subject_activity():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT s.name, COUNT(q.id) as quiz_count FROM subjects s LEFT JOIN quizzes q ON s.id = q.subject_id GROUP BY s.id, s.name ORDER BY quiz_count DESC''')
	labels,values=[name for name,count in cursor.fetchall()],[count for name,count in cursor.fetchall()]
	conn.close()
	return {'labels':labels,'values':values}

def get_time_series_data():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT DATE(time) as date, COUNT(*) as attempts FROM quiz_results WHERE time >= date('now', '-7 days') GROUP BY DATE(time) ORDER BY date''')
	labels,values=[date for date,attempts in cursor.fetchall()],[attempts for date,attempts in cursor.fetchall()]
	conn.close()
	return {'labels':labels,'values':values}

def get_score_distribution():
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT CASE WHEN score >= 90 THEN '90-100%' WHEN score >= 80 THEN '80-89%' WHEN score >= 70 THEN '70-79%' WHEN score >= 60 THEN '60-69%' ELSE 'Below 60%' END as range, COUNT(*) as count FROM quiz_results GROUP BY CASE WHEN score >= 90 THEN '90-100%' WHEN score >= 80 THEN '80-89%' WHEN score >= 70 THEN '70-79%' WHEN score >= 60 THEN '60-69%' ELSE 'Below 60%' END ORDER BY CASE WHEN score >= 90 THEN 1 WHEN score >= 80 THEN 2 WHEN score >= 70 THEN 3 WHEN score >= 60 THEN 4 ELSE 5 END''')
	labels,values=[range_name for range_name,count in cursor.fetchall()],[count for range_name,count in cursor.fetchall()]
	conn.close()
	return {'labels':labels,'values':values}

if __name__=='__main__':
	init_db()
	init_rag_system()
	port=int(os.environ.get('PORT',8000))
	app.run(debug=False,host='0.0.0.0',port=port)