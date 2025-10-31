import os
import uuid
import json
import hashlib
import time
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import session as flask_session
from werkzeug.utils import secure_filename

from utils.config import UPLOAD_FOLDER, USER_IMAGES_FOLDER, MAX_FILE_SIZE, SECRET_KEY, PERMANENT_SESSION_LIFETIME
from database.db import (init_db, verify_user, add_material, log_qa, get_materials, add_user, delete_user, get_all_users,
                log_quiz_result, get_qa_logs, get_quiz_results, export_quiz_csv, get_subjects, get_user_subjects,
                assign_user_subject, remove_user_subject, create_quiz, assign_quiz_to_students, get_teacher_quizzes,
                get_student_quizzes, get_quiz_by_id, update_quiz_score, get_db_connection, get_non_indexed_materials,
                update_material_indexed_status, get_subjects_with_counts, get_user_face_image, update_user_face_image,
                add_mood_tracking, get_user_mood_today, get_user_mood_history, get_all_student_moods,
                get_student_moods_by_teacher, get_all_users_with_faces, get_user_grade)
from utils.auth import login_required, admin_required, teacher_required, login_user, logout_user, get_current_user
from services.rag_service import get_rag_system
from database.session_db import (create_study_session, get_study_sessions, get_session_participants,
                                  join_session, leave_session, add_session_message, get_session_messages)
from database.analytics_db import (get_admin_stats, get_teacher_stats, get_recent_activities,
                                    get_teacher_recent_activities, get_user_distribution, get_performance_data,
                                    get_subject_activity, get_time_series_data, get_score_distribution,
                                    get_teacher_qa_logs, get_teacher_quiz_results, get_teacher_performance_data,
                                    get_teacher_student_stats, get_teacher_quiz_stats, get_teacher_time_series,
                                    get_teacher_subject_performance)
from database.notes_db import get_user_notes, create_note, get_note, update_note, delete_note
from database.quiz_db import get_quiz_result
from services.session_service import (handle_join_session_socket, handle_leave_session_socket, handle_message_socket,
                                       handle_offer_socket, handle_answer_socket, handle_ice_candidate_socket,
                                       handle_ready_for_connections_socket)
from utils.file_utils import allowed_file
from utils.face_utils import prepare_uploaded_image, verify_face, analyze_mood, mood_emoji, get_mood_theme

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['PERMANENT_SESSION_LIFETIME'] = PERMANENT_SESSION_LIFETIME
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")

@app.template_filter('emoji')
def emoji_filter(mood):
    return mood_emoji(mood) if mood else '🙂'

@app.template_filter('month_name')
def month_name_filter(month_num):
    months=['January','February','March','April','May','June','July','August','September','October','November','December']
    return months[month_num-1] if 1<=month_num<=12 else 'Unknown'

@app.context_processor
def inject_mood_theme():
    mood = session.get('user_mood')
    if mood:
        theme = get_mood_theme(mood)
        return {'user_mood': mood, 'mood_theme': theme}
    return {'user_mood': None, 'mood_theme': None}

@app.route('/')
def index():
    if 'user_id' in session:
        user = get_current_user()
        if user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif user['role'] == 'teacher':
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
            user = verify_user(username, password)
        elif face_image:
            usersWithFaces=get_all_users_with_faces()
            if not usersWithFaces:
                flash('No users have registered face images. Please use password login.','error')
                return render_template('login.html')
            tempDir=os.path.join(USER_IMAGES_FOLDER,'temp')
            os.makedirs(tempDir,exist_ok=True)
            tmpImg=os.path.join(tempDir,'temp_login.jpg')
            from PIL import Image
            img=Image.open(face_image)
            if img.mode=='RGBA':img=img.convert('RGB')
            img.save(tmpImg,format='JPEG')
            match=None
            for u in usersWithFaces:
                if u['face_image'] and os.path.exists(u['face_image']):
                    if verify_face(u['face_image'],tmpImg):
                        match=u
                        break
            if match:
                user={'id':match['id'],'username':match['username'],'role':match['role']}
                mood=analyze_mood(tmpImg)
                add_mood_tracking(user['id'],mood['mood'],mood['age'],mood['gender'],mood['race'])
                session['user_mood']=mood['mood']
            if os.path.exists(tmpImg):os.remove(tmpImg)
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

@app.route('/upload', methods=['GET', 'POST'])
@teacher_required
def upload():
    user = get_current_user()
    rag = get_rag_system()
    if request.method == 'POST':
        lastUpload = session.get('last_upload_time', 0)
        now = time.time()
        diff = now - lastUpload
        if diff < 120:
            wait = 120 - int(diff)
            flash(f'Upload rate limit: Please wait {wait} seconds before uploading again.', 'error')
            return redirect(url_for('upload'))
        
        files = request.files.getlist('files')
        subjId = request.form.get('subject_id')
        
        if not files or all(f.filename == '' for f in files):
            flash('No files selected.', 'error')
            return redirect(url_for('upload'))
        if not subjId:
            flash('Please select a subject.', 'error')
            return redirect(url_for('upload'))
        
        uploaded = []
        for f in files:
            if f and allowed_file(f.filename):
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(0)
                if size > MAX_FILE_SIZE:
                    flash(f'File {f.filename} too large.', 'error')
                    continue
                
                fname = secure_filename(f.filename)
                uniqName = f"{uuid.uuid4()}_{fname}"
                path = os.path.join(UPLOAD_FOLDER, uniqName)
                f.save(path)
                
                if fname.lower().endswith('.pdf'):
                    txt = rag.extract_pdf(path)
                else:
                    txt = rag.extract_txt(path)
                
                if txt.strip():
                    uploaded.append(path)
                    add_material(fname, txt, subjId, indexed=0)
                else:
                    os.remove(path)
                    flash(f'Could not extract text from {fname}.', 'error')
            else:
                flash(f'Invalid file format: {f.filename}.', 'error')
        
        if uploaded:
            try:
                mats = get_materials()
                rag.rebuild_from_db(mats)
                for mat in mats:
                    if mat['filename'] in [secure_filename(f.filename) for f in files if f and allowed_file(f.filename)]:
                        update_material_indexed_status(mat['id'], indexed=1)
                session['last_upload_time'] = time.time()
                session.modified = True
                flash(f'Uploaded and indexed {len(uploaded)} file(s) for subject.', 'success')
            except Exception as e:
                flash(f'Error building index: {str(e)}', 'error')
        return redirect(url_for('upload'))
    
    mats = get_materials()
    subs = get_user_subjects(user['id'])
    return render_template('index.html', materials=mats, subjects=subs)

@app.route('/reindex', methods=['POST'])
@teacher_required
def reindex_files():
    user = get_current_user()
    try:
        rag = get_rag_system()
        nonIndexed = get_non_indexed_materials()
        if nonIndexed:
            allMats = get_materials()
            rag.rebuild_from_db(allMats)
            for mat in nonIndexed:
                update_material_indexed_status(mat['id'], indexed=1)
            flash(f'Successfully indexed {len(nonIndexed)} file(s) that had indexing problems!', 'success')
        else:
            flash('All files are already properly indexed!', 'info')
    except Exception as e:
        flash(f'Error re-indexing files: {str(e)}', 'error')
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
    
    if user['role'] == 'admin':
        flash('Admins do not have access to chat.', 'error')
        return redirect(url_for('admin_dashboard'))
    rag = get_rag_system()
    if rag is None or not rag.chunks:
        flash('No materials indexed yet. Please ask a teacher to upload materials first.', 'warning')
        if user['role'] == 'student':
            return redirect(url_for('student_quizzes'))
        else:
            return redirect(url_for('upload'))
    if request.method=='POST':
        q=request.form['question'].strip()
        ajax=request.headers.get('X-Requested-With')=='XMLHttpRequest'
        if q:
            try:
                grade=get_user_grade(user['id'])
                ans,srcs=rag.query(q,top_k=3,user_grade=grade)
                log_qa(session['user_id'],q,ans)
                if 'chat_history' not in session:session['chat_history']=[]
                session['chat_history'].append({'question':q,'answer':ans,'sources':srcs})
                if len(session['chat_history'])>10:session['chat_history']=session['chat_history'][-10:]
                session.modified=True
                if ajax:
                    return jsonify({
                        'success':True,
                        'question':q,
                        'answer':ans,
                        'sources':[{'metadata':s.get('metadata',{}),'score':s.get('score',0)} for s in srcs]
                    })
            except Exception as e:
                if ajax:
                    return jsonify({'success':False,'error':str(e)})
                flash(f'Error generating answer: {str(e)}','error')
        else:
            if ajax:
                return jsonify({'success':False,'error':'Empty question'})
    history=session.get('chat_history',[])
    return render_template('chat.html',chat_history=history)

@app.route('/quiz', methods=['GET', 'POST'])
@login_required
def quiz():
    rag = get_rag_system()
    if request.method=='POST':
        numQ,desc=int(request.form.get('num_questions',5)),request.form.get('description','')
        try:
            questions=rag.generate_quiz(numQ,desc)
            if questions:
                session['current_quiz']=questions
                session.modified=True
                return render_template('quiz.html',quiz=questions,show_quiz=True)
            else:flash('Failed to generate quiz questions.','error')
        except Exception as e:flash(f'Error generating quiz: {str(e)}','error')
    quizData=session.get('current_quiz',[])
    if quizData:return render_template('quiz.html',quiz=quizData,show_quiz=True)
    return render_template('quiz.html',show_quiz=False)

@app.route('/export_quiz')
@login_required
def export_quiz():
    quiz_to_export=session.get('current_quiz',[])
    if not quiz_to_export:
        flash('No quiz to export.','error')
        return redirect(url_for('quiz'))
    csv_output=export_quiz_csv(quiz_to_export)
    http_response=make_response(csv_output)
    http_response.headers['Content-Type']='text/csv'
    http_response.headers['Content-Disposition']='attachment; filename=quiz_export.csv'
    return http_response

@app.route('/admin',methods=['GET','POST'])
@admin_required
def admin():
    if request.method=='POST':
        username,password,role,subject_ids=request.form['username'],request.form['password'],request.form['role'],request.form.getlist('subject_ids')
        grade=request.form.get('grade','').strip() if role=='student' else None
        faceImg=request.files.get('face_image')
        imgPath=None
        if faceImg and faceImg.filename:
            userDir=os.path.join(USER_IMAGES_FOLDER,username)
            os.makedirs(userDir,exist_ok=True)
            imgPath=os.path.join(userDir,f"{username}_face.jpg")
            ok,msg=prepare_uploaded_image(faceImg,imgPath)
            if not ok:
                flash(f'Face image error: {msg}','error')
                users,subjects=get_all_users(),get_subjects()
                return render_template('admin.html',users=users,all_subjects=subjects)
        try:
            uid=add_user(username,password,role,imgPath,grade)
            if subject_ids and role in ['student','teacher']:
                for sid in subject_ids:assign_user_subject(uid,sid)
            flash(f'User {username} created successfully!','success')
        except Exception as e:flash(f'Error creating user: {str(e)}','error')
    users,subjects=get_all_users(),get_subjects()
    return render_template('admin.html',users=users,all_subjects=subjects)

@app.route('/edit_user/<int:user_id>',methods=['GET','POST'])
@admin_required
def edit_user(user_id):
    if request.method == 'POST':
        db_conn = get_db_connection()
        db_cursor = db_conn.cursor()
        uname = request.form['username']
        role = request.form['role']
        sids = request.form.getlist('subject_ids')
        pwd=request.form.get('password','').strip()
        grd=request.form.get('grade','').strip() if role=='student' else None
        faceImg=request.files.get('face_image')
        try:
            db_cursor.execute('UPDATE users SET username = ?, role = ?, grade = ? WHERE id = ?',(uname,role,grd,user_id))
            if pwd:
                pwdHash=hashlib.sha256(pwd.encode()).hexdigest()
                db_cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',(pwdHash,user_id))
            if faceImg and faceImg.filename:
                imgDir=os.path.join(USER_IMAGES_FOLDER,uname)
                os.makedirs(imgDir,exist_ok=True)
                picPath=os.path.join(imgDir,f"{uname}_face.jpg")
                ok,msg=prepare_uploaded_image(faceImg,picPath)
                if ok:
                    db_cursor.execute('UPDATE users SET face_image = ? WHERE id = ?',(picPath,user_id))
                else:
                    flash(f'Face image error: {msg}','error')
            db_cursor.execute('DELETE FROM user_subjects WHERE user_id = ?',(user_id,))
            if sids and role in ['student','teacher']:
                for sid in sids:
                    db_cursor.execute('INSERT OR IGNORE INTO user_subjects (user_id, subject_id) VALUES (?, ?)',(user_id,sid))
            db_conn.commit()
            db_conn.close()
            flash(f'User {uname} updated successfully!','success')
            return redirect(url_for('admin'))
        except Exception as e:
            db_conn.rollback()
            db_conn.close()
            flash(f'Error updating user: {str(e)}','error')
            return redirect(url_for('edit_user',user_id=user_id))
    db_conn=get_db_connection()
    db_cursor=db_conn.cursor()
    db_cursor.execute('SELECT id, username, role, grade FROM users WHERE id = ?',(user_id,))
    user_row=db_cursor.fetchone()
    if not user_row:
        db_conn.close()
        flash('User not found.','error')
        return redirect(url_for('admin'))
    user_dict={'id':user_row[0],'username':user_row[1],'role':user_row[2],'grade':user_row[3]}
    db_conn.close()
    subs=get_user_subjects(user_id)
    allSubs=get_subjects()
    return render_template('edit_user.html',user=user_dict,user_subjects=subs,all_subjects=allSubs)

@app.route('/delete_user/<int:user_id>')
@admin_required
def delete_user_route(user_id):
    if user_id==session['user_id']:
        flash('Cannot delete your own account.','error')
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
        title,sid,desc,numQ,diff=request.form['title'],request.form['subject_id'],request.form['description'],int(request.form.get('num_questions',5)),request.form.get('difficulty','medium')
        try:
            rag = get_rag_system()
            qs = rag.generate_quiz(numQ, desc, sid, diff)
            if qs:
                qid = create_quiz(title, sid, session['user_id'], qs, diff)
                flash(f'Quiz "{title}" created successfully!', 'success')
                return redirect(url_for('quiz_editor', quiz_id=qid))
            else:
                flash('Failed to generate quiz questions.', 'error')
        except Exception as e:
            flash(f'Error creating quiz: {str(e)}', 'error')
    teacherSubs = get_user_subjects(session['user_id'])
    return render_template('create_quiz.html', subjects=teacherSubs)

@app.route('/assign_quiz/<int:quiz_id>',methods=['GET','POST'])
@teacher_required
def assign_quiz(quiz_id):
    quiz=get_quiz_by_id(quiz_id)
    if not quiz or quiz['teacher_id']!=session['user_id']:
        flash('Quiz not found.','error')
        return redirect(url_for('my_quizzes'))
    if request.method=='POST':
        sids=request.form.getlist('student_ids')
        if sids:
            assign_quiz_to_students(quiz_id,sids)
            flash('Quiz assigned successfully!','success')
            return redirect(url_for('my_quizzes'))
        else:flash('Please select at least one student.','error')
    db_conn=get_db_connection()
    db_cursor=db_conn.cursor()
    db_cursor.execute('SELECT student_id FROM quiz_assignments WHERE quiz_id = ?',(quiz_id,))
    assigned_student_ids=set(row[0] for row in db_cursor.fetchall())
    quiz_subject_id=quiz.get('subject_id')
    if quiz_subject_id:
        db_cursor.execute('''SELECT DISTINCT u.id, u.username FROM users u 
            JOIN user_subjects us ON u.id = us.user_id 
            WHERE u.role = "student" AND us.subject_id = ?''',(quiz_subject_id,))
    else:
        db_cursor.execute('SELECT id, username FROM users WHERE role = "student"')
    student_list=[]
    for student_row in db_cursor.fetchall():
        student_list.append({'id':student_row[0],'username':student_row[1],'assigned':student_row[0] in assigned_student_ids})
    db_conn.close()
    return render_template('assign_quiz.html',quiz=quiz,students=student_list)

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
    student_quiz_list=get_student_quizzes(user['id'])
    db_conn=get_db_connection()
    db_cursor=db_conn.cursor()
    for quiz_item in student_quiz_list:
        db_cursor.execute('SELECT id, score, time FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY time DESC LIMIT 1',(user['id'],quiz_item['id']))
        result_row=db_cursor.fetchone()
        if result_row:
            quiz_item['completed_time']=result_row[2]
            quiz_item['score']=round(result_row[1],1)
            quiz_item['result_id']=result_row[0]
        else:
            quiz_item['completed_time']=None
            quiz_item['score']=None
            quiz_item['result_id']=None
    db_conn.close()
    
    return render_template('student_quizzes.html',quizzes=student_quiz_list)

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
    db_conn=get_db_connection()
    db_cursor=db_conn.cursor()
    db_cursor.execute('SELECT id, score, time, answers FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY time DESC LIMIT 1',(user['id'],quiz_id))
    previous_result=db_cursor.fetchone()
    db_conn.close()
    if previous_result:
        flash('You have already completed this quiz. Viewing your results.','info')
        return redirect(url_for('view_quiz_result',result_id=previous_result[0]))
    
    try:
        qs=json.loads(quiz['questions']) if isinstance(quiz['questions'],str) else quiz['questions']
    except (TypeError,json.JSONDecodeError):
        qs=quiz['questions']
    if request.method=='POST':
        ans,correct=[],0
        for i,q in enumerate(qs):
            key=f'q{i}'
            uAns=request.form.get(key,'').strip().upper()
            corrAns=q['correct'].strip().upper()
            if uAns==corrAns:
                correct+=1
            ans.append({'question':q['question'],'user_answer':uAns,'correct_answer':corrAns,'is_correct':uAns==corrAns})
        score=(correct/len(qs))*100
        rid=log_quiz_result(user['id'],score,ans,quiz_id)
        update_quiz_score(quiz_id,user['id'],score)
        return redirect(url_for('view_quiz_result',result_id=rid))
    return render_template('take_quiz.html',quiz=quiz,questions=qs)

@app.route('/view_quiz_result/<int:result_id>')
@login_required
def view_quiz_result(result_id):
    user = get_current_user()
    quiz_result_info = get_quiz_result(result_id, user['id'])
    if not quiz_result_info:
        flash('Result not found.', 'error')
        return redirect(url_for('student_quizzes'))
    return render_template('quiz_results.html', **quiz_result_info)

@app.route('/explain_question',methods=['POST'])
@login_required
def explain_question():
    request_data=request.json
    question_text=request_data.get('question','')
    option_list=request_data.get('options',[])
    correct_ans=request_data.get('correct_answer','')
    student_ans=request_data.get('user_answer','')
    
    if not question_text:
        return jsonify({'success':False,'error':'Question is required'})
    
    try:
        rag = get_rag_system()
        options_text='\n'.join([f"{chr(65+i)}) {opt}" for i,opt in enumerate(option_list)])
        explanation_prompt=f"""Explain this quiz question and why the correct answer is right:

Question: {question_text}

Options:
{options_text}

Correct Answer: {correct_ans}
{'Student answered: ' + student_ans if student_ans else ''}

Please provide:
1. A clear explanation of what the question is asking
2. Why the correct answer ({correct_ans}) is correct
3. Why the other options are incorrect (if applicable)
4. Any key concepts the student should understand

Keep your explanation concise but informative."""

        rag.rate_limit()
        api_response=rag.client.chat(
            message=explanation_prompt,
            model='command-a-03-2025',
            preamble="You are a helpful educational assistant. Provide clear, concise explanations that help students understand quiz questions and answers.",
            chat_history=[]
        )
        
        explanation_text=api_response.text.strip()
        return jsonify({'success':True,'explanation':explanation_text})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)})

@app.route('/admin_dashboard')
@admin_required
def admin_dashboard():
    user=get_current_user()
    stats,recent=get_admin_stats(),get_recent_activities()
    userDist,perfData,subjAct,tsData,scoreDist=get_user_distribution(),get_performance_data(),get_subject_activity(),get_time_series_data(),get_score_distribution()
    return render_template('admin_dashboard.html',user=user,stats=stats,recent_activities=recent,user_distribution=userDist,performance_data=perfData,subject_activity=subjAct,time_series_data=tsData,score_distribution=scoreDist)

@app.route('/teacher_dashboard')
@teacher_required
def teacher_dashboard():
    user=get_current_user()
    stats,recent=get_teacher_stats(user['id']),get_teacher_recent_activities(user['id'])
    userDist,perfData,subjAct,tsData,scoreDist=get_user_distribution(),get_performance_data(),get_subject_activity(),get_time_series_data(),get_score_distribution()
    return render_template('teacher_dashboard.html',user=user,stats=stats,recent_activities=recent,user_distribution=userDist,performance_data=perfData,subject_activity=subjAct,time_series_data=tsData,score_distribution=scoreDist)

@app.route('/user_images/<path:filename>')
@login_required
def serve_user_image(filename):
    return send_from_directory(USER_IMAGES_FOLDER, filename)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user=get_current_user()
    subs=[] if user['role']=='admin' else get_user_subjects(user['id'])
    imgPath = get_user_face_image(user['id'])
    user['face_image'] = imgPath
    if request.method == 'POST':
        faceImg = request.files.get('face_image')
        if faceImg and faceImg.filename:
            uname = user['username']
            imgDir = os.path.join(USER_IMAGES_FOLDER, uname)
            os.makedirs(imgDir, exist_ok=True)
            picPath = os.path.join(imgDir, f"{uname}_face.jpg")
            ok, msg = prepare_uploaded_image(faceImg, picPath)
            if ok:
                update_user_face_image(user['id'], picPath)
                flash('Profile image updated successfully!', 'success')
            else:
                flash(f'Image upload error: {msg}', 'error')
        elif not imgPath:
            flash('Please select an image file.', 'error')
        return redirect(url_for('profile'))
    
    return render_template('profile.html',user=user,user_subjects=subs)

@app.route('/change_password',methods=['POST'])
@login_required
def change_password():
    currPwd,newPwd,confirmPwd=request.form['current_password'],request.form['new_password'],request.form['confirm_password']
    user=get_current_user()
    if not verify_user(user['username'],currPwd):
        flash('Current password is incorrect.','error')
        return redirect(url_for('profile'))
    if newPwd!=confirmPwd:
        flash('New passwords do not match.','error')
        return redirect(url_for('profile'))
    if len(newPwd)<6:
        flash('Password must be at least 6 characters long.','error')
        return redirect(url_for('profile'))
    conn=get_db_connection()
    cursor=conn.cursor()
    cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',(hashlib.sha256(newPwd.encode()).hexdigest(),user['id']))
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
        qs=json.loads(quiz['questions']) if isinstance(quiz['questions'],str) else quiz['questions']
    except (TypeError,json.JSONDecodeError):
        qs=quiz['questions']
    return render_template('quiz_editor.html',quiz=quiz,questions=qs)

@app.route('/update_quiz_questions/<int:quiz_id>',methods=['POST'])
@teacher_required
def update_quiz_questions(quiz_id):
    quiz=get_quiz_by_id(quiz_id)
    if not quiz or quiz['teacher_id']!=session['user_id']:
        return jsonify({'success':False,'error':'Quiz not found'})
    try:
        qs=request.json.get('questions',[])
        conn=get_db_connection()
        cursor=conn.cursor()
        cursor.execute('UPDATE quizzes SET questions = ? WHERE id = ?',(json.dumps(qs),quiz_id))
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
        rag = get_rag_system()
        qs = rag.generate_quiz(5, quiz['description'], quiz['subject_id'])
        if qs:
            conn=get_db_connection()
            cursor=conn.cursor()
            cursor.execute('UPDATE quizzes SET questions = ? WHERE id = ?',(json.dumps(qs),quiz_id))
            conn.commit()
            conn.close()
            flash('Quiz regenerated successfully!','success')
        else:flash('Failed to regenerate quiz questions.','error')
    except Exception as e:flash(f'Error regenerating quiz: {str(e)}','error')
    return redirect(url_for('quiz_editor',quiz_id=quiz_id))

@app.route('/notes')
@login_required
def notes():
    user = get_current_user()
    if user['role'] == 'admin':
        flash('Admins do not have access to notes.', 'error')
        return redirect(url_for('admin_dashboard'))
    notes = get_user_notes(user['id'])
    subs = get_user_subjects(user['id'])
    return render_template('notes.html', notes=notes, subjects=subs)

@app.route('/create_note', methods=['POST'])
@login_required
def create_note_route():
    user = get_current_user()
    if user['role'] == 'admin':
        return jsonify({'success': False, 'error': 'Admins do not have access to notes'})
    title = request.json.get('title', '')
    content = request.json.get('content', '')
    sid = request.json.get('subject_id')
    if not title or not content:
        return jsonify({'success': False, 'error': 'Title and content are required'})
    try:
        create_note(user['id'], title, content, sid)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/update_note/<int:note_id>', methods=['PUT'])
@login_required
def update_note_route(note_id):
    user = get_current_user()
    if user['role'] == 'admin':
        return jsonify({'success': False, 'error': 'Admins do not have access to notes'})
    title = request.json.get('title', '')
    content = request.json.get('content', '')
    sid = request.json.get('subject_id')
    if not title or not content:
        return jsonify({'success': False, 'error': 'Title and content are required'})
    try:
        if update_note(note_id, user['id'], title, content, sid):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Note not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_note/<int:note_id>', methods=['GET'])
@login_required
def get_note_route(note_id):
    user = get_current_user()
    if user['role'] == 'admin':
        return jsonify({'success': False, 'error': 'Admins do not have access to notes'})
    note = get_note(note_id, user['id'])
    if not note:
        return jsonify({'success': False, 'error': 'Note not found'})
    return jsonify({'success': True, 'note': note})

@app.route('/delete_note/<int:note_id>', methods=['DELETE'])
@login_required
def delete_note_route(note_id):
    user = get_current_user()
    if user['role'] == 'admin':
        return jsonify({'success': False, 'error': 'Admins do not have access to notes'})
    try:
        if delete_note(note_id, user['id']):
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Note not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/mood_map')
@login_required
def mood_map():
    user=get_current_user()
    history=get_user_mood_history(user['id'],limit=30)
    from datetime import date,datetime
    import calendar
    now=datetime.now()
    year,month=now.year,now.month
    moods={d['date']:d['mood'] for d in history}
    cal=calendar.monthcalendar(year,month)
    days=[]
    for week in cal:
        weekMoods=[]
        for day in week:
            if day==0:
                weekMoods.append("")
            else:
                dstr=f"{year}-{month:02d}-{day:02d}"
                m=moods.get(dstr)
                weekMoods.append(mood_emoji(m) if m else "")
        days.append(weekMoods)
    currMood=get_user_mood_today(user['id'])
    return render_template('mood_map.html',calendar=days,year=year,month=month,current_mood=currMood,mood_history=history)

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


@app.route('/study_together')
@login_required
def study_together():
    user = get_current_user()
    subs = get_user_subjects(user['id']) if user['role'] in ['student', 'teacher'] else []
    sessions = get_study_sessions()
    return render_template('study_together.html', sessions=sessions, user_subjects=subs, user=user)

@app.route('/create_session', methods=['GET', 'POST'])
@login_required
def create_session():
    if request.method == 'POST':
        user = get_current_user()
        title = request.form['title']
        sid = request.form.get('subject_id')
        desc = request.form.get('description', '')
        maxP = int(request.form.get('max_participants', 10))
        try:
            sessId = create_study_session(user['id'], title, sid, desc, maxP)
            flash('Study session created successfully!', 'success')
            return redirect(url_for('study_session', session_id=sessId))
        except Exception as e:
            flash(f'Error creating session: {str(e)}', 'error')
    subs = get_user_subjects(session['user_id']) if session.get('role') in ['student', 'teacher'] else []
    allSubs = get_subjects()
    return render_template('create_session.html', subjects=allSubs, user_subjects=subs)

@app.route('/study_session/<int:session_id>')
@login_required
def study_session(session_id):
    user=get_current_user()
    db_conn=get_db_connection()
    db_cursor=db_conn.cursor()
    db_cursor.execute('''SELECT s.*, u.username as host_name, sub.name as subject_name
        FROM study_sessions s
        JOIN users u ON s.host_id = u.id
        LEFT JOIN subjects sub ON s.subject_id = sub.id
        WHERE s.id = ? AND s.is_active = 1''',(session_id,))
    session_row=db_cursor.fetchone()
    db_conn.close()
    if not session_row:
        flash('Session not found or inactive.','error')
        return redirect(url_for('study_together'))
    session_info={
        'id':session_row[0],'host_id':session_row[1],'title':session_row[2],'subject_id':session_row[3],
        'description':session_row[4],'max_participants':session_row[5],'created_at':session_row[6],
        'is_active':session_row[7],'host_name':session_row[8],'subject_name':session_row[9]
    }
    participant_list=get_session_participants(session_id)
    message_list=get_session_messages(session_id)
    join_session(session_id,user['id'])
    return render_template('study_session.html',session=session_info,participants=participant_list,messages=message_list,user=user)

@socketio.on('join_session')
def handle_join_session(socket_data):
    handle_join_session_socket(socket_data, socketio)

@socketio.on('leave_session')
def handle_leave_session(socket_data):
    handle_leave_session_socket(socket_data, socketio)

@socketio.on('send_message')
def handle_message(socket_data):
    handle_message_socket(socket_data, socketio)

@socketio.on('offer')
def handle_offer(socket_data):
    handle_offer_socket(socket_data, socketio)

@socketio.on('answer')
def handle_answer(socket_data):
    handle_answer_socket(socket_data, socketio)

@socketio.on('ice_candidate')
def handle_ice_candidate(socket_data):
    handle_ice_candidate_socket(socket_data, socketio)

@socketio.on('ready_for_connections')
def handle_ready_for_connections(socket_data):
    handle_ready_for_connections_socket(socket_data, socketio)

if __name__ == '__main__':
    init_db()
    get_rag_system()
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)