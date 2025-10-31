import os,uuid,json,hashlib,time
from flask import Flask,render_template,request,redirect,url_for,session,flash,jsonify,make_response
from flask_socketio import SocketIO,emit,join_room,leave_room
from flask import session as flask_session
from werkzeug.utils import secure_filename
from db import init_db,verify_user,add_material,log_qa,get_materials,add_user,delete_user,get_all_users,log_quiz_result,get_qa_logs,get_quiz_results,export_quiz_csv,get_subjects,get_user_subjects,assign_user_subject,remove_user_subject,create_quiz,assign_quiz_to_students,get_teacher_quizzes,get_student_quizzes,get_quiz_by_id,update_quiz_score,get_db_connection,get_non_indexed_materials,update_material_indexed_status,get_subjects_with_counts,get_user_face_image,update_user_face_image,add_mood_tracking,get_user_mood_today,get_user_mood_history,get_all_student_moods,get_student_moods_by_teacher,get_all_users_with_faces
from auth import login_required,admin_required,teacher_required,login_user,logout_user,get_current_user
from rag import SmartStudyRAG
from face_utils import prepare_uploaded_image,verify_face,analyze_mood,mood_emoji,get_mood_theme

app=Flask(__name__)
app.secret_key='IB-Smartportal'
app.config['PERMANENT_SESSION_LIFETIME']=86400
app.config['SECRET_KEY']='IB-Smartportal'
socketio=SocketIO(app,cors_allowed_origins="*")

@app.template_filter('emoji')
def emoji_filter(mood):
	return mood_emoji(mood) if mood else '🙂'

@app.template_filter('month_name')
def month_name_filter(month_num):
	months=['January','February','March','April','May','June','July','August','September','October','November','December']
	return months[month_num-1] if 1<=month_num<=12 else 'Unknown'

@app.context_processor
def inject_mood_theme():
	mood=session.get('user_mood')
	if mood:
		theme=get_mood_theme(mood)
		return {'user_mood':mood,'mood_theme':theme}
	return {'user_mood':None,'mood_theme':None}
UPLOAD_FOLDER='uploads'
USER_IMAGES_FOLDER='user_images'
ALLOWED_EXTENSIONS={'pdf','txt'}
ALLOWED_IMAGE_EXTENSIONS={'jpg','jpeg','png','gif'}
MAX_FILE_SIZE=10*1024*1024
os.makedirs(UPLOAD_FOLDER,exist_ok=True)
os.makedirs(USER_IMAGES_FOLDER,exist_ok=True)
rag_system=None

def allowed_file(filename):return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def init_rag_system():
	global rag_system
	if rag_system is None:
		api_key=os.getenv('COHERE_API_KEY')
		if not api_key:
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
		if user['role']=='admin':
			return redirect(url_for('admin_dashboard'))
		elif user['role']=='teacher':
			return redirect(url_for('teacher_dashboard'))
		else:
			return redirect(url_for('student_quizzes'))
	return redirect(url_for('login'))

@app.route('/login',methods=['GET','POST'])
def login():
	if request.method=='POST':
		username=request.form.get('username','')
		password=request.form.get('password','')
		face_image=request.files.get('face_image')
		user=None
		if password and username:
			user=verify_user(username,password)
		elif face_image:
			users_with_faces=get_all_users_with_faces()
			if not users_with_faces:
				flash('No users have registered face images. Please use password login.','error')
				return render_template('login.html')
			temp_folder=os.path.join(USER_IMAGES_FOLDER,'temp')
			os.makedirs(temp_folder,exist_ok=True)
			temp_image_path=os.path.join(temp_folder,'temp_login.jpg')
			from PIL import Image
			image=Image.open(face_image)
			if image.mode=='RGBA':image=image.convert('RGB')
			image.save(temp_image_path,format='JPEG')
			matched_user=None
			for user_data in users_with_faces:
				if user_data['face_image'] and os.path.exists(user_data['face_image']):
					if verify_face(user_data['face_image'],temp_image_path):
						matched_user=user_data
						break
			if matched_user:
				user={'id':matched_user['id'],'username':matched_user['username'],'role':matched_user['role']}
				mood_data=analyze_mood(temp_image_path)
				add_mood_tracking(user['id'],mood_data['mood'],mood_data['age'],mood_data['gender'],mood_data['race'])
				session['user_mood']=mood_data['mood']
			if os.path.exists(temp_image_path):os.remove(temp_image_path)
			if not user:
				flash('Face recognition failed. Your face does not match any registered user.','error')
		if user:
			login_user(user)
			session.permanent=True
			current_mood=get_user_mood_today(user['id'])
			if current_mood:session['user_mood']=current_mood
			return redirect(url_for('index'))
		else:
			if not password and not face_image:
				flash('Please provide either password or face image.','error')
			elif not user:
				flash('Invalid username, password, or face recognition failed.','error')
	return render_template('login.html')

@app.route('/logout')
def logout():
	logout_user()
	return redirect(url_for('login'))

@app.route('/upload',methods=['GET','POST'])
@teacher_required
def upload():
	user=get_current_user()
	global rag_system
	init_rag_system()
	if request.method=='POST':
		last_upload=session.get('last_upload_time',0)
		current_time=time.time()
		time_diff=current_time-last_upload
		if time_diff<120:
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
					add_material(filename,content,subject_id,indexed=0)
				else:
					os.remove(file_path)
					flash(f'Could not extract text from {filename}.','error')
			else:flash(f'Invalid file format: {file.filename}.','error')
		if uploaded_files:
			try:
				materials=get_materials()
				rag_system.rebuild_from_db(materials)
				for material in materials:
					if material['filename'] in [secure_filename(f.filename) for f in files if f and allowed_file(f.filename)]:
						update_material_indexed_status(material['id'],indexed=1)
				session['last_upload_time']=time.time()
				session.modified=True
				flash(f'Uploaded and indexed {len(uploaded_files)} file(s) for subject.','success')
			except Exception as e:
				flash(f'Error building index: {str(e)}','error')
		return redirect(url_for('upload'))
	materials=get_materials()
	user_subjects=get_user_subjects(user['id'])
	return render_template('index.html',materials=materials,subjects=user_subjects)

@app.route('/reindex',methods=['POST'])
@teacher_required
def reindex_files():
	user=get_current_user()
	global rag_system
	try:
		init_rag_system()
		non_indexed_materials=get_non_indexed_materials()
		if non_indexed_materials:
			all_materials=get_materials()
			rag_system.rebuild_from_db(all_materials)
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
	if 'user_id' not in session:
		flash('You need to login first','error')
		return redirect(url_for('login'))
	
	user=get_current_user()
	if not user or not user.get('id'):
		flash('Session expired. Please login again.','error')
		return redirect(url_for('login'))
	
	if user['role']=='admin':
		flash('Admins do not have access to chat.','error')
		return redirect(url_for('admin_dashboard'))
	global rag_system
	init_rag_system()
	if rag_system is None or not rag_system.chunks:
		flash('No materials indexed yet. Please ask a teacher to upload materials first.','warning')
		if user['role']=='student':
			return redirect(url_for('student_quizzes'))
		else:
			return redirect(url_for('upload'))
	if request.method=='POST':
		question=request.form['question'].strip()
		is_ajax=request.headers.get('X-Requested-With')=='XMLHttpRequest'
		if question:
			try:
				answer,sources=rag_system.query(question,top_k=3)
				log_qa(session['user_id'],question,answer)
				if 'chat_history' not in session:session['chat_history']=[]
				session['chat_history'].append({'question':question,'answer':answer,'sources':sources})
				if len(session['chat_history'])>10:session['chat_history']=session['chat_history'][-10:]
				session.modified=True
				if is_ajax:
					return jsonify({
						'success':True,
						'question':question,
						'answer':answer,
						'sources':[{'metadata':s.get('metadata',{}),'score':s.get('score',0)} for s in sources]
					})
			except Exception as e:
				if is_ajax:
					return jsonify({'success':False,'error':str(e)})
				flash(f'Error generating answer: {str(e)}','error')
		else:
			if is_ajax:
				return jsonify({'success':False,'error':'Empty question'})
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
		username,password,role,subject_ids=request.form['username'],request.form['password'],request.form['role'],request.getlist('subject_ids')
		face_image=request.files.get('face_image')
		face_image_path=None
		if face_image and face_image.filename:
			user_folder=os.path.join(USER_IMAGES_FOLDER,username)
			os.makedirs(user_folder,exist_ok=True)
			face_image_path=os.path.join(user_folder,f"{username}_face.jpg")
			success,msg=prepare_uploaded_image(face_image,face_image_path)
			if not success:
				flash(f'Face image error: {msg}','error')
				users,subjects=get_all_users(),get_subjects()
				return render_template('admin.html',users=users,all_subjects=subjects)
		try:
			user_id=add_user(username,password,role,face_image_path)
			if subject_ids and role in ['student','teacher']:
				for subject_id in subject_ids:assign_user_subject(user_id,subject_id)
			flash(f'User {username} created successfully!','success')
		except Exception as e:flash(f'Error creating user: {str(e)}','error')
	users,subjects=get_all_users(),get_subjects()
	return render_template('admin.html',users=users,all_subjects=subjects)

@app.route('/edit_user/<int:user_id>',methods=['GET','POST'])
@admin_required
def edit_user(user_id):
	if request.method=='POST':
		conn=get_db_connection()
		cursor=conn.cursor()
		username,role,subject_ids=request.form['username'],request.form['role'],request.form.getlist('subject_ids')
		password=request.form.get('password','').strip()
		face_image=request.files.get('face_image')
		try:
			cursor.execute('UPDATE users SET username = ?, role = ? WHERE id = ?',(username,role,user_id))
			if password:
				password_hash=hashlib.sha256(password.encode()).hexdigest()
				cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',(password_hash,user_id))
			if face_image and face_image.filename:
				user_folder=os.path.join(USER_IMAGES_FOLDER,username)
				os.makedirs(user_folder,exist_ok=True)
				face_image_path=os.path.join(user_folder,f"{username}_face.jpg")
				success,msg=prepare_uploaded_image(face_image,face_image_path)
				if success:
					cursor.execute('UPDATE users SET face_image = ? WHERE id = ?',(face_image_path,user_id))
				else:
					flash(f'Face image error: {msg}','error')
			cursor.execute('DELETE FROM user_subjects WHERE user_id = ?',(user_id,))
			if subject_ids and role in ['student','teacher']:
				for subject_id in subject_ids:
					cursor.execute('INSERT OR IGNORE INTO user_subjects (user_id, subject_id) VALUES (?, ?)',(user_id,subject_id))
			conn.commit()
			conn.close()
			flash(f'User {username} updated successfully!','success')
			return redirect(url_for('admin'))
		except Exception as e:
			conn.rollback()
			conn.close()
			flash(f'Error updating user: {str(e)}','error')
			return redirect(url_for('edit_user',user_id=user_id))
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, username, role FROM users WHERE id = ?',(user_id,))
	user=cursor.fetchone()
	if not user:
		conn.close()
		flash('User not found.','error')
		return redirect(url_for('admin'))
	user_dict={'id':user[0],'username':user[1],'role':user[2]}
	conn.close()
	user_subjects=get_user_subjects(user_id)
	all_subjects=get_subjects()
	return render_template('edit_user.html',user=user_dict,user_subjects=user_subjects,all_subjects=all_subjects)

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
	if user['role']=='teacher':
		qa_logs=get_teacher_qa_logs(user['id'])
		quiz_results=get_teacher_quiz_results(user['id'])
		performance_data=get_teacher_performance_data(user['id'])
		student_stats=get_teacher_student_stats(user['id'])
		quiz_stats=get_teacher_quiz_stats(user['id'])
		time_series=get_teacher_time_series(user['id'])
		subject_performance=get_teacher_subject_performance(user['id'])
	elif user['role']=='admin':
		qa_logs=get_qa_logs()
		quiz_results=get_quiz_results()
		performance_data=get_performance_data()
		student_stats={'total_students':0,'active_students':0}
		quiz_stats={'total_quizzes':0,'completed_quizzes':0}
		time_series=get_time_series_data()
		subject_performance={'labels':[],'values':[]}
	else:
		qa_logs=get_qa_logs(user['id'])
		quiz_results=get_quiz_results(user['id'])
		performance_data={'average_score':0,'total_attempts':0}
		student_stats={'total_students':0,'active_students':0}
		quiz_stats={'total_quizzes':0,'completed_quizzes':0}
		time_series={'labels':[],'values':[]}
		subject_performance={'labels':[],'values':[]}
	return render_template('progress.html',qa_logs=qa_logs,quiz_results=quiz_results,performance_data=performance_data,student_stats=student_stats,quiz_stats=quiz_stats,time_series=time_series,subject_performance=subject_performance,user_role=user['role'])

@app.route('/subjects')
@login_required
def subjects():
	user=get_current_user()
	if user['role']=='admin':
		flash('Admins do not have subjects.','error')
		return redirect(url_for('admin_dashboard'))
	user_subjects=get_user_subjects(user['id'])
	return render_template('subjects.html',user_subjects=user_subjects,all_subjects=[],read_only=True)

@app.route('/assign_subject',methods=['POST'])
@admin_required
def assign_subject():
	user_id,subject_ids,action=request.form.get('user_id'),request.form.getlist('subject_ids'),request.form.get('action','assign')
	if not user_id:
		flash('User ID is required.','error')
		return redirect(url_for('admin'))
	try:user_id=int(user_id)
	except ValueError:
		flash('Invalid user ID.','error')
		return redirect(url_for('admin'))
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('DELETE FROM user_subjects WHERE user_id = ?',(user_id,))
	for subject_id in subject_ids:
		try:
			subject_id=int(subject_id)
			assign_user_subject(user_id,subject_id)
		except ValueError:
			continue
	conn.commit()
	conn.close()
	flash('Subjects updated successfully!','success')
	return redirect(request.referrer or url_for('admin'))

@app.route('/create_quiz',methods=['GET','POST'])
@teacher_required
def create_quiz_route():
	if request.method=='POST':
		title,subject_id,description,num_questions,difficulty=request.form['title'],request.form['subject_id'],request.form['description'],int(request.form.get('num_questions',5)),request.form.get('difficulty','medium')
		try:
			init_rag_system()
			quiz_questions=rag_system.generate_quiz(num_questions,description,subject_id,difficulty)
			if quiz_questions:
				quiz_id=create_quiz(title,subject_id,session['user_id'],quiz_questions,difficulty)
				flash(f'Quiz "{title}" created successfully!','success')
				return redirect(url_for('quiz_editor',quiz_id=quiz_id))
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
	cursor.execute('SELECT student_id FROM quiz_assignments WHERE quiz_id = ?',(quiz_id,))
	assigned_student_ids=set(row[0] for row in cursor.fetchall())
	quiz_subject_id=quiz.get('subject_id')
	if quiz_subject_id:
		cursor.execute('''SELECT DISTINCT u.id, u.username FROM users u 
			JOIN user_subjects us ON u.id = us.user_id 
			WHERE u.role = "student" AND us.subject_id = ?''',(quiz_subject_id,))
	else:
		cursor.execute('SELECT id, username FROM users WHERE role = "student"')
	all_students=[{'id':row[0],'username':row[1],'assigned':row[0] in assigned_student_ids} for row in cursor.fetchall()]
	conn.close()
	return render_template('assign_quiz.html',quiz=quiz,students=all_students)

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
	conn=get_db_connection()
	cursor=conn.cursor()
	for quiz in quizzes:
		cursor.execute('SELECT id, score, time FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY time DESC LIMIT 1',(user['id'],quiz['id']))
		result=cursor.fetchone()
		if result:
			quiz['completed_time']=result[2]
			quiz['score']=round(result[1],1)
			quiz['result_id']=result[0]
		else:
			quiz['completed_time']=None
			quiz['score']=None
			quiz['result_id']=None
	conn.close()
	
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
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, score, time, answers FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY time DESC LIMIT 1',(user['id'],quiz_id))
	existing_result=cursor.fetchone()
	conn.close()
	if existing_result:
		flash('You have already completed this quiz. Viewing your results.','info')
		return redirect(url_for('view_quiz_result',result_id=existing_result[0]))
	
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
		result_id=log_quiz_result(user['id'],score,answers,quiz_id)
		update_quiz_score(quiz_id,user['id'],score)
		return redirect(url_for('view_quiz_result',result_id=result_id))
	return render_template('take_quiz.html',quiz=quiz,questions=questions)

@app.route('/view_quiz_result/<int:result_id>')
@login_required
def view_quiz_result(result_id):
	user=get_current_user()
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT qr.*, q.title, q.questions FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.id = ? AND qr.user_id = ?',(result_id,user['id']))
	result=cursor.fetchone()
	conn.close()
	
	if not result:
		flash('Result not found.','error')
		return redirect(url_for('student_quizzes'))
	
	quiz={'title':result[6]}
	try:
		answers=json.loads(result[4]) if isinstance(result[4],str) else result[4]
		quiz_questions=json.loads(result[7]) if isinstance(result[7],str) else result[7]
	except:
		answers=result[4]
		quiz_questions=result[7]
	for i,answer in enumerate(answers):
		if i<len(quiz_questions):
			answer['options']=quiz_questions[i].get('options',[])
	
	score=result[3]
	correct=sum(1 for a in answers if a.get('is_correct',False))
	total=len(answers)
	percentage=round(score,1)
	
	return render_template('quiz_results.html',quiz=quiz,score=score,total=total,correct=correct,percentage=percentage,answers=answers,quiz_questions=quiz_questions)

@app.route('/explain_question',methods=['POST'])
@login_required
def explain_question():
	data=request.json
	question=data.get('question','')
	options=data.get('options',[])
	correct_answer=data.get('correct_answer','')
	user_answer=data.get('user_answer','')
	
	if not question:
		return jsonify({'success':False,'error':'Question is required'})
	
	try:
		global rag_system
		init_rag_system()
		options_text='\n'.join([f"{chr(65+i)}) {opt}" for i,opt in enumerate(options)])
		prompt=f"""Explain this quiz question and why the correct answer is right:

Question: {question}

Options:
{options_text}

Correct Answer: {correct_answer}
{'Student answered: ' + user_answer if user_answer else ''}

Please provide:
1. A clear explanation of what the question is asking
2. Why the correct answer ({correct_answer}) is correct
3. Why the other options are incorrect (if applicable)
4. Any key concepts the student should understand

Keep your explanation concise but informative."""

		rag_system.rate_limit()
		response=rag_system.client.chat(
			message=prompt,
			model='command-a-03-2025',
			preamble="You are a helpful educational assistant. Provide clear, concise explanations that help students understand quiz questions and answers.",
			chat_history=[]
		)
		
		explanation=response.text.strip()
		return jsonify({'success':True,'explanation':explanation})
	except Exception as e:
		return jsonify({'success':False,'error':str(e)})

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
	user=get_current_user()
	stats,recent_activities=get_admin_stats(),get_recent_activities()
	user_distribution,performance_data,subject_activity,time_series_data,score_distribution=get_user_distribution(),get_performance_data(),get_subject_activity(),get_time_series_data(),get_score_distribution()
	return render_template('admin_dashboard.html',user=user,stats=stats,recent_activities=recent_activities,user_distribution=user_distribution,performance_data=performance_data,subject_activity=subject_activity,time_series_data=time_series_data,score_distribution=score_distribution)

@app.route('/teacher_dashboard')
@teacher_required
def teacher_dashboard():
	user=get_current_user()
	stats,recent_activities=get_teacher_stats(user['id']),get_teacher_recent_activities(user['id'])
	user_distribution,performance_data,subject_activity,time_series_data,score_distribution=get_user_distribution(),get_performance_data(),get_subject_activity(),get_time_series_data(),get_score_distribution()
	return render_template('teacher_dashboard.html',user=user,stats=stats,recent_activities=recent_activities,user_distribution=user_distribution,performance_data=performance_data,subject_activity=subject_activity,time_series_data=time_series_data,score_distribution=score_distribution)

@app.route('/profile')
@login_required
def profile():
	user=get_current_user()
	user_subjects=[] if user['role']=='admin' else get_user_subjects(user['id'])
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
	cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',(hashlib.sha256(new_password.encode()).hexdigest(),user['id']))
	conn.commit()
	conn.close()
	flash('Password changed successfully!','success')
	return redirect(url_for('profile'))

@app.route('/manage_subjects')
@admin_required
def manage_subjects():
	subjects=get_subjects_with_counts()
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
	conn=get_db_connection()
	cursor=conn.cursor()
	if request.method=='POST':
		name=request.form['name'].strip()
		if name:
			try:
				cursor.execute('UPDATE subjects SET name = ? WHERE id = ?',(name,subject_id))
				conn.commit()
				conn.close()
				flash(f'Subject updated successfully!','success')
				return redirect(url_for('manage_subjects'))
			except Exception as e:
				flash(f'Error updating subject: {str(e)}','error')
		else:flash('Subject name cannot be empty.','error')
	cursor.execute('SELECT id, name FROM subjects WHERE id = ?',(subject_id,))
	subject_row=cursor.fetchone()
	conn.close()
	if not subject_row:
		flash('Subject not found.','error')
		return redirect(url_for('manage_subjects'))
	subject={'id':subject_row[0],'name':subject_row[1]}
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

@app.route('/quiz_editor/<int:quiz_id>')
@teacher_required
def quiz_editor(quiz_id):
	quiz=get_quiz_by_id(quiz_id)
	if not quiz or quiz['teacher_id']!=session['user_id']:
		flash('Quiz not found.','error')
		return redirect(url_for('my_quizzes'))
	try:
		questions=json.loads(quiz['questions']) if isinstance(quiz['questions'],str) else quiz['questions']
	except (TypeError,json.JSONDecodeError):
		questions=quiz['questions']
	return render_template('quiz_editor.html',quiz=quiz,questions=questions)

@app.route('/update_quiz_questions/<int:quiz_id>',methods=['POST'])
@teacher_required
def update_quiz_questions(quiz_id):
	quiz=get_quiz_by_id(quiz_id)
	if not quiz or quiz['teacher_id']!=session['user_id']:
		return jsonify({'success':False,'error':'Quiz not found'})
	try:
		questions=request.json.get('questions',[])
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('UPDATE quizzes SET questions = ? WHERE id = ?',(json.dumps(questions),quiz_id))
		conn.commit()
		conn.close()
		return jsonify({'success':True})
	except Exception as e:
		return jsonify({'success':False,'error':str(e)})

@app.route('/regenerate_quiz/<int:quiz_id>')
@teacher_required
def regenerate_quiz(quiz_id):
	quiz=get_quiz_by_id(quiz_id)
	if not quiz or quiz['teacher_id']!=session['user_id']:
		flash('Quiz not found.','error')
		return redirect(url_for('my_quizzes'))
	try:
		init_rag_system()
		quiz_questions=rag_system.generate_quiz(5,quiz['description'],quiz['subject_id'])
		if quiz_questions:
			conn=get_db_connection()
			cursor=conn.cursor()
			cursor.execute('UPDATE quizzes SET questions = ? WHERE id = ?',(json.dumps(quiz_questions),quiz_id))
			conn.commit()
			conn.close()
			flash('Quiz regenerated successfully!','success')
		else:flash('Failed to regenerate quiz questions.','error')
	except Exception as e:flash(f'Error regenerating quiz: {str(e)}','error')
	return redirect(url_for('quiz_editor',quiz_id=quiz_id))

@app.route('/notes')
@login_required
def notes():
	user=get_current_user()
	if user['role']=='admin':
		flash('Admins do not have access to notes.','error')
		return redirect(url_for('admin_dashboard'))
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY created_at DESC',(user['id'],))
	notes=[{'id':row[0],'title':row[2],'content':row[3],'subject_id':row[4],'created_at':row[5]} for row in cursor.fetchall()]
	user_subjects=get_user_subjects(user['id'])
	conn.close()
	return render_template('notes.html',notes=notes,subjects=user_subjects)

@app.route('/create_note',methods=['POST'])
@login_required
def create_note():
	user=get_current_user()
	if user['role']=='admin':
		return jsonify({'success':False,'error':'Admins do not have access to notes'})
	title,content,subject_id=request.json.get('title',''),request.json.get('content',''),request.json.get('subject_id')
	if not title or not content:
		return jsonify({'success':False,'error':'Title and content are required'})
	try:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('INSERT INTO notes (user_id, title, content, subject_id) VALUES (?, ?, ?, ?)',(user['id'],title,content,subject_id))
		conn.commit()
		conn.close()
		return jsonify({'success':True})
	except Exception as e:
		return jsonify({'success':False,'error':str(e)})

@app.route('/update_note/<int:note_id>',methods=['PUT'])
@login_required
def update_note(note_id):
	user=get_current_user()
	if user['role']=='admin':
		return jsonify({'success':False,'error':'Admins do not have access to notes'})
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT user_id FROM notes WHERE id = ?',(note_id,))
	note=cursor.fetchone()
	if not note or note[0]!=user['id']:
		return jsonify({'success':False,'error':'Note not found'})
	title,content,subject_id=request.json.get('title',''),request.json.get('content',''),request.json.get('subject_id')
	if not title or not content:
		return jsonify({'success':False,'error':'Title and content are required'})
	try:
		cursor.execute('UPDATE notes SET title = ?, content = ?, subject_id = ? WHERE id = ?',(title,content,subject_id,note_id))
		conn.commit()
		conn.close()
		return jsonify({'success':True})
	except Exception as e:
		return jsonify({'success':False,'error':str(e)})

@app.route('/get_note/<int:note_id>',methods=['GET'])
@login_required
def get_note(note_id):
	user=get_current_user()
	if user['role']=='admin':
		return jsonify({'success':False,'error':'Admins do not have access to notes'})
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, user_id, title, content, subject_id FROM notes WHERE id = ?',(note_id,))
	note=cursor.fetchone()
	conn.close()
	if not note or note[1]!=user['id']:
		return jsonify({'success':False,'error':'Note not found'})
	return jsonify({'success':True,'note':{'id':note[0],'title':note[2],'content':note[3],'subject_id':note[4]}})

@app.route('/delete_note/<int:note_id>',methods=['DELETE'])
@login_required
def delete_note(note_id):
	user=get_current_user()
	if user['role']=='admin':
		return jsonify({'success':False,'error':'Admins do not have access to notes'})
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT user_id FROM notes WHERE id = ?',(note_id,))
	note=cursor.fetchone()
	if not note or note[0]!=user['id']:
		return jsonify({'success':False,'error':'Note not found'})
	try:
		cursor.execute('DELETE FROM notes WHERE id = ?',(note_id,))
		conn.commit()
		conn.close()
		return jsonify({'success':True})
	except Exception as e:
		return jsonify({'success':False,'error':str(e)})

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
	results=cursor.fetchall()
	labels=[name for name,count in results]
	values=[count for name,count in results]
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

def get_teacher_qa_logs(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT qa.question, qa.answer, qa.timestamp, u.username FROM qa_logs qa 
		JOIN users u ON qa.user_id = u.id 
		WHERE u.id IN (SELECT DISTINCT qa2.student_id FROM quiz_assignments qa2 JOIN quizzes q ON qa2.quiz_id = q.id WHERE q.teacher_id = ?)
		ORDER BY qa.timestamp DESC LIMIT 100''',(teacher_id,))
	logs=[{'question':row[0],'answer':row[1],'timestamp':row[2],'username':row[3]} for row in cursor.fetchall()]
	conn.close()
	return logs

def get_teacher_quiz_results(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT qr.score, qr.time, qr.answers, u.username, q.title FROM quiz_results qr 
		JOIN users u ON qr.user_id = u.id 
		JOIN quizzes q ON qr.quiz_id = q.id 
		WHERE q.teacher_id = ? ORDER BY qr.time DESC LIMIT 100''',(teacher_id,))
	results=[{'score':row[0],'time':row[1],'answers':json.loads(row[2]),'username':row[3],'quiz_title':row[4]} for row in cursor.fetchall()]
	conn.close()
	return results

def get_teacher_performance_data(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT AVG(qr.score) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''',(teacher_id,))
	avg_score=cursor.fetchone()[0] or 0
	cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score >= 80''',(teacher_id,))
	high_scores=cursor.fetchone()[0]
	cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score >= 60 AND qr.score < 80''',(teacher_id,))
	medium_scores=cursor.fetchone()[0]
	cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ? AND qr.score < 60''',(teacher_id,))
	low_scores=cursor.fetchone()[0]
	cursor.execute('''SELECT COUNT(*) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''',(teacher_id,))
	total_attempts=cursor.fetchone()[0]
	conn.close()
	return {'labels':['High (80%+)','Medium (60-79%)','Low (<60%)'],'values':[high_scores,medium_scores,low_scores],'average_score':round(avg_score,1),'total_attempts':total_attempts}

def get_teacher_student_stats(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT COUNT(DISTINCT qa.student_id) FROM quiz_assignments qa JOIN quizzes q ON qa.quiz_id = q.id WHERE q.teacher_id = ?''',(teacher_id,))
	total_students=cursor.fetchone()[0]
	cursor.execute('''SELECT COUNT(DISTINCT qr.user_id) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''',(teacher_id,))
	active_students=cursor.fetchone()[0]
	conn.close()
	return {'total_students':total_students,'active_students':active_students}

def get_teacher_quiz_stats(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT COUNT(*) FROM quizzes WHERE teacher_id = ?',(teacher_id,))
	total_quizzes=cursor.fetchone()[0]
	cursor.execute('''SELECT COUNT(DISTINCT qr.quiz_id) FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE q.teacher_id = ?''',(teacher_id,))
	completed_quizzes=cursor.fetchone()[0]
	conn.close()
	return {'total_quizzes':total_quizzes,'completed_quizzes':completed_quizzes}

def get_teacher_time_series(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT DATE(qr.time) as date, COUNT(*) as attempts FROM quiz_results qr 
		JOIN quizzes q ON qr.quiz_id = q.id 
		WHERE q.teacher_id = ? AND qr.time >= date('now', '-7 days') 
		GROUP BY DATE(qr.time) ORDER BY date''',(teacher_id,))
	results=cursor.fetchall()
	labels=[date for date,attempts in results]
	values=[attempts for date,attempts in results]
	conn.close()
	return {'labels':labels,'values':values}

def get_teacher_subject_performance(teacher_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT s.name, AVG(qr.score) as avg_score FROM quiz_results qr 
		JOIN quizzes q ON qr.quiz_id = q.id 
		JOIN subjects s ON q.subject_id = s.id 
		WHERE q.teacher_id = ? 
		GROUP BY s.id, s.name 
		ORDER BY avg_score DESC LIMIT 10''',(teacher_id,))
	results=cursor.fetchall()
	labels=[name for name,avg_score in results]
	values=[round(avg_score,1) for name,avg_score in results]
	conn.close()
	return {'labels':labels,'values':values}

@app.route('/mood_map')
@login_required
def mood_map():
	user=get_current_user()
	mood_history=get_user_mood_history(user['id'],limit=30)
	from datetime import date,datetime
	import calendar
	now=datetime.now()
	year,month=now.year,now.month
	moods={d['date']:d['mood'] for d in mood_history}
	cal=calendar.monthcalendar(year,month)
	mood_days=[]
	for week in cal:
		week_moods=[]
		for day in week:
			if day==0:
				week_moods.append("")
			else:
				dstr=f"{year}-{month:02d}-{day:02d}"
				mood=moods.get(dstr)
				week_moods.append(mood_emoji(mood) if mood else "")
		mood_days.append(week_moods)
	current_mood=get_user_mood_today(user['id'])
	return render_template('mood_map.html',calendar=mood_days,year=year,month=month,current_mood=current_mood,mood_history=mood_history)

@app.route('/admin/mood_tracking')
@admin_required
def admin_mood_tracking():
	student_moods=get_all_student_moods()
	return render_template('admin_mood_tracking.html',student_moods=student_moods)

@app.route('/teacher/mood_tracking')
@teacher_required
def teacher_mood_tracking():
	user=get_current_user()
	student_moods=get_student_moods_by_teacher(user['id'])
	return render_template('teacher_mood_tracking.html',student_moods=student_moods)

def create_study_session(host_id,title,subject_id=None,description='',max_participants=10):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('INSERT INTO study_sessions (host_id, title, subject_id, description, max_participants) VALUES (?, ?, ?, ?, ?)',(host_id,title,subject_id,description,max_participants))
	session_id=cursor.lastrowid
	cursor.execute('INSERT INTO session_participants (session_id, user_id) VALUES (?, ?)',(session_id,host_id))
	conn.commit()
	conn.close()
	return session_id

def get_study_sessions(user_id=None,subject_id=None):
	conn=get_db_connection()
	cursor=conn.cursor()
	query='''SELECT s.*, u.username as host_name, sub.name as subject_name,
		(SELECT COUNT(*) FROM session_participants WHERE session_id = s.id) as participant_count
		FROM study_sessions s
		JOIN users u ON s.host_id = u.id
		LEFT JOIN subjects sub ON s.subject_id = sub.id
		WHERE s.is_active = 1'''
	params=[]
	if subject_id:
		query+=' AND s.subject_id = ?'
		params.append(subject_id)
	query+=' ORDER BY s.created_at DESC'
	cursor.execute(query,tuple(params))
	results=cursor.fetchall()
	sessions=[]
	for row in results:
		sessions.append({
			'id':row[0],'host_id':row[1],'title':row[2],'subject_id':row[3],
			'description':row[4],'max_participants':row[5],'created_at':row[6],
			'is_active':row[7],'host_name':row[8],'subject_name':row[9],'participant_count':row[10]
		})
	conn.close()
	return sessions

def get_session_participants(session_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT u.id, u.username, u.role, sp.joined_at
		FROM session_participants sp
		JOIN users u ON sp.user_id = u.id
		WHERE sp.session_id = ?
		ORDER BY sp.joined_at''',(session_id,))
	participants=[{'id':row[0],'username':row[1],'role':row[2],'joined_at':row[3]} for row in cursor.fetchall()]
	conn.close()
	return participants

def join_session(session_id,user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('INSERT OR IGNORE INTO session_participants (session_id, user_id) VALUES (?, ?)',(session_id,user_id))
	conn.commit()
	conn.close()

def leave_session(session_id,user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('DELETE FROM session_participants WHERE session_id = ? AND user_id = ?',(session_id,user_id))
	conn.commit()
	conn.close()

def add_session_message(session_id,user_id,message):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('INSERT INTO session_messages (session_id, user_id, message) VALUES (?, ?, ?)',(session_id,user_id,message))
	conn.commit()
	conn.close()

def get_session_messages(session_id,limit=50):
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT sm.*, u.username, u.role
		FROM session_messages sm
		JOIN users u ON sm.user_id = u.id
		WHERE sm.session_id = ?
		ORDER BY sm.timestamp DESC
		LIMIT ?''',(session_id,limit))
	messages=[]
	for row in cursor.fetchall():
		messages.append({
			'id':row[0],'session_id':row[1],'user_id':row[2],'message':row[3],
			'timestamp':row[4],'username':row[5],'role':row[6]
		})
	conn.close()
	return list(reversed(messages))

@app.route('/study_together')
@login_required
def study_together():
	user=get_current_user()
	user_subjects=get_user_subjects(user['id']) if user['role'] in ['student','teacher'] else []
	sessions=get_study_sessions()
	return render_template('study_together.html',sessions=sessions,user_subjects=user_subjects,user=user)

@app.route('/create_session',methods=['GET','POST'])
@login_required
def create_session():
	if request.method=='POST':
		user=get_current_user()
		title=request.form['title']
		subject_id=request.form.get('subject_id')
		description=request.form.get('description','')
		max_participants=int(request.form.get('max_participants',10))
		try:
			session_id=create_study_session(user['id'],title,subject_id,description,max_participants)
			flash('Study session created successfully!','success')
			return redirect(url_for('study_session',session_id=session_id))
		except Exception as e:
			flash(f'Error creating session: {str(e)}','error')
	user_subjects=get_user_subjects(session['user_id']) if session.get('role') in ['student','teacher'] else []
	subjects=get_subjects()
	return render_template('create_session.html',subjects=subjects,user_subjects=user_subjects)

@app.route('/study_session/<int:session_id>')
@login_required
def study_session(session_id):
	user=get_current_user()
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('''SELECT s.*, u.username as host_name, sub.name as subject_name
		FROM study_sessions s
		JOIN users u ON s.host_id = u.id
		LEFT JOIN subjects sub ON s.subject_id = sub.id
		WHERE s.id = ? AND s.is_active = 1''',(session_id,))
	result=cursor.fetchone()
	conn.close()
	if not result:
		flash('Session not found or inactive.','error')
		return redirect(url_for('study_together'))
	session_data={
		'id':result[0],'host_id':result[1],'title':result[2],'subject_id':result[3],
		'description':result[4],'max_participants':result[5],'created_at':result[6],
		'is_active':result[7],'host_name':result[8],'subject_name':result[9]
	}
	participants=get_session_participants(session_id)
	messages=get_session_messages(session_id)
	join_session(session_id,user['id'])
	return render_template('study_session.html',session=session_data,participants=participants,messages=messages,user=user)

@socketio.on('join_session')
def handle_join_session(data):
	session_id=data.get('session_id')
	user_id=flask_session.get('user_id')
	if user_id and session_id:
		join_room(f'session_{session_id}')
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT id, username, role FROM users WHERE id = ?',(user_id,))
		user_row=cursor.fetchone()
		conn.close()
		if user_row:
			user={'id':user_row[0],'username':user_row[1],'role':user_row[2]}
			join_session(session_id,user_id)
			participants=get_session_participants(session_id)
			emit('user_joined',{'username':user['username'],'participants':participants},room=f'session_{session_id}')

@socketio.on('leave_session')
def handle_leave_session(data):
	session_id=data.get('session_id')
	user_id=flask_session.get('user_id')
	if user_id and session_id:
		leave_room(f'session_{session_id}')
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT id, username, role FROM users WHERE id = ?',(user_id,))
		user_row=cursor.fetchone()
		conn.close()
		if user_row:
			user={'id':user_row[0],'username':user_row[1],'role':user_row[2]}
			leave_session(session_id,user_id)
			participants=get_session_participants(session_id)
			emit('user_left',{'username':user['username'],'participants':participants},room=f'session_{session_id}')

@socketio.on('send_message')
def handle_message(data):
	session_id=data.get('session_id')
	user_id=flask_session.get('user_id')
	message=data.get('message','')
	if user_id and session_id and message:
		conn=get_db_connection()
		cursor=conn.cursor()
		cursor.execute('SELECT id, username, role FROM users WHERE id = ?',(user_id,))
		user_row=cursor.fetchone()
		conn.close()
		if user_row:
			user={'id':user_row[0],'username':user_row[1],'role':user_row[2]}
			if message.startswith('/ai '):
				question=message[4:].strip()
				if question:
					try:
						init_rag_system()
						if rag_system and rag_system.chunks:
							answer,results=rag_system.query(question,top_k=3)
							log_qa(user_id,question,answer)
							add_session_message(session_id,user_id,f'/ai {question}')
							emit('new_message',{
								'username':user['username'],
								'role':user['role'],
								'message':f'/ai {question}',
								'timestamp':time.time()
							},room=f'session_{session_id}')
							emit('ai_response',{
								'username':user['username'],
								'question':question,
								'answer':answer,
								'timestamp':time.time()
							},room=f'session_{session_id}')
						else:
							add_session_message(session_id,user_id,message)
							emit('new_message',{
								'username':user['username'],
								'role':user['role'],
								'message':message,
								'timestamp':time.time()
							},room=f'session_{session_id}')
							emit('ai_response',{
								'username':user['username'],
								'question':question,
								'answer':'No study materials indexed yet. Please upload materials first.',
								'timestamp':time.time()
							},room=f'session_{session_id}')
					except Exception as e:
						add_session_message(session_id,user_id,message)
						emit('new_message',{
							'username':user['username'],
							'role':user['role'],
							'message':message,
							'timestamp':time.time()
						},room=f'session_{session_id}')
						emit('ai_response',{
							'username':user['username'],
							'question':question,
							'answer':f'Error: {str(e)}',
							'timestamp':time.time()
						},room=f'session_{session_id}')
				else:
					add_session_message(session_id,user_id,message)
					emit('new_message',{
						'username':user['username'],
						'role':user['role'],
						'message':message,
						'timestamp':time.time()
					},room=f'session_{session_id}')
			else:
				add_session_message(session_id,user_id,message)
				emit('new_message',{
					'username':user['username'],
					'role':user['role'],
					'message':message,
					'timestamp':time.time()
				},room=f'session_{session_id}')

@socketio.on('offer')
def handle_offer(data):
	user_id=flask_session.get('user_id')
	if user_id:
		data['user_id']=user_id
		emit('offer',data,room=f'session_{data["session_id"]}',include_self=False)

@socketio.on('answer')
def handle_answer(data):
	user_id=flask_session.get('user_id')
	if user_id:
		data['user_id']=user_id
		emit('answer',data,room=f'session_{data["session_id"]}',include_self=False)

@socketio.on('ice_candidate')
def handle_ice_candidate(data):
	user_id=flask_session.get('user_id')
	if user_id:
		data['user_id']=user_id
		emit('ice_candidate',data,room=f'session_{data["session_id"]}',include_self=False)

@socketio.on('ready_for_connections')
def handle_ready_for_connections(data):
	user_id=flask_session.get('user_id')
	if user_id:
		emit('ready_for_connections',{'user_id':user_id,'session_id':data.get('session_id')},room=f'session_{data.get("session_id")}',include_self=False)

if __name__=='__main__':
	init_db()
	init_rag_system()
	port=int(os.environ.get('PORT',2121))
	socketio.run(app,debug=False,host='0.0.0.0',port=port)