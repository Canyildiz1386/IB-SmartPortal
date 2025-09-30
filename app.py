import os,uuid,json,hashlib,time
from flask import Flask,render_template,request,redirect,url_for,session,flash,jsonify,make_response
from werkzeug.utils import secure_filename
from db import init_db,verify_user,add_material,log_qa,get_materials,add_user,delete_user,get_all_users,log_quiz_result,get_qa_logs,get_quiz_results,export_quiz_csv,get_subjects,get_user_subjects,assign_user_subject,remove_user_subject,create_quiz,assign_quiz_to_students,get_teacher_quizzes,get_student_quizzes,get_quiz_by_id,update_quiz_score,get_db_connection,get_non_indexed_materials,update_material_indexed_status,get_subjects_with_counts
from auth import login_required,admin_required,teacher_required,login_user,logout_user,get_current_user
from rag import SmartStudyRAG
from PIL import Image
import pytesseract
import cv2
import numpy as np
import io
import base64

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
@teacher_required
def upload():
	user=get_current_user()
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
@teacher_required
def reindex_files():
	user=get_current_user()
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
	user=get_current_user()
	if user['role']=='admin':
		flash('Admins do not have access to chat.','error')
		return redirect(url_for('admin_dashboard'))
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
	return render_template('admin.html',users=users,all_subjects=subjects)

@app.route('/edit_user/<int:user_id>',methods=['GET','POST'])
@admin_required
def edit_user(user_id):
	conn=get_db_connection()
	cursor=conn.cursor()
	if request.method=='POST':
		username,role,subject_ids=request.form['username'],request.form['role'],request.form.getlist('subject_ids')
		password=request.form.get('password','').strip()
		try:
			# Update username and role
			cursor.execute('UPDATE users SET username = ?, role = ? WHERE id = ?',(username,role,user_id))
			# Update password if provided
			if password:
				password_hash=hashlib.sha256(password.encode()).hexdigest()
				cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',(password_hash,user_id))
			# Update subjects - remove all and add new ones
			cursor.execute('DELETE FROM user_subjects WHERE user_id = ?',(user_id,))
			if subject_ids and role in ['student','teacher']:
				for subject_id in subject_ids:
					assign_user_subject(user_id,subject_id)
			conn.commit()
			flash(f'User {username} updated successfully!','success')
			return redirect(url_for('admin'))
		except Exception as e:
			flash(f'Error updating user: {str(e)}','error')
		finally:
			conn.close()
	# GET request - show edit form
	cursor.execute('SELECT id, username, role FROM users WHERE id = ?',(user_id,))
	user=cursor.fetchone()
	if not user:
		flash('User not found.','error')
		conn.close()
		return redirect(url_for('admin'))
	user_dict={'id':user[0],'username':user[1],'role':user[2]}
	user_subjects=get_user_subjects(user_id)
	all_subjects=get_subjects()
	conn.close()
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
	if user['role'] in ['admin','teacher']:
		qa_logs,quiz_results=get_qa_logs(),get_quiz_results()
	else:
		qa_logs,quiz_results=get_qa_logs(user['id']),get_quiz_results(user['id'])
	return render_template('progress.html',qa_logs=qa_logs,quiz_results=quiz_results)

@app.route('/subjects')
@login_required
def subjects():
	user=get_current_user()
	if user['role']=='admin':
		flash('Admins do not have subjects.','error')
		return redirect(url_for('admin_dashboard'))
	# Users can only view their subjects, not assign them
	user_subjects=get_user_subjects(user['id'])
	return render_template('subjects.html',user_subjects=user_subjects,all_subjects=[],read_only=True)

@app.route('/assign_subject',methods=['POST'])
@admin_required
def assign_subject():
	# Only admins can assign subjects now
	user_id,subject_ids,action=request.form.get('user_id'),request.form.getlist('subject_ids'),request.form.get('action','assign')
	if not user_id:
		flash('User ID is required.','error')
		return redirect(url_for('admin'))
	try:user_id=int(user_id)
	except ValueError:
		flash('Invalid user ID.','error')
		return redirect(url_for('admin'))
	# Remove all existing subjects for the user
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('DELETE FROM user_subjects WHERE user_id = ?',(user_id,))
	# Add new subjects
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
	
	# Add completion status and scores to quizzes
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
	
	# Check if student has already completed this quiz
	conn=get_db_connection()
	cursor=conn.cursor()
	cursor.execute('SELECT id, score, time, answers FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY time DESC LIMIT 1',(user['id'],quiz_id))
	existing_result=cursor.fetchone()
	conn.close()
	
	if existing_result:
		# Quiz already completed - redirect to view results
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
	
	# Enhance answers with full question data
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
		
		# Create prompt for explanation
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

# Quiz Editor Routes
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

# Notes System Routes
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

@app.route('/extract_text_from_image',methods=['POST'])
@login_required
def extract_text_from_image():
	if 'image' not in request.files:
		return jsonify({'success':False,'error':'No image file provided'})
	file=request.files['image']
	if file.filename=='':
		return jsonify({'success':False,'error':'No image file selected'})
	try:
		image=Image.open(file.stream)
		image_array=np.array(image)
		if len(image_array.shape)==3:
			image_array=cv2.cvtColor(image_array,cv2.COLOR_RGB2GRAY)
		text=pytesseract.image_to_string(image_array)
		return jsonify({'success':True,'extracted_text':text.strip()})
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

if __name__=='__main__':
	init_db()
	init_rag_system()
	port=int(os.environ.get('PORT',2121))
	app.run(debug=False,host='0.0.0.0',port=port)