from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import hashlib
import json
import uuid

from database.db import init_db, verify_user, add_user, get_all_users, delete_user, get_db_connection
from database.db import add_material, get_materials, get_subjects, get_user_subjects, assign_user_subject
from database.db import get_material_by_id, delete_material, update_material_indexed
from database.db import add_subject, delete_subject, update_subject
from database.db import get_user_by_id, update_user, remove_user_subjects
from database.db import create_quiz, get_teacher_quizzes, get_student_quizzes, get_quiz_by_id, log_quiz_result, assign_quiz_to_students
from database.db import update_quiz_questions
from database.db import log_qa, get_qa_logs, add_qa_correction, get_qa_corrections
from database.db import create_note, get_user_notes, get_note_by_id, update_note, delete_note
from utils.auth import login_required, admin_required, teacher_required, login_user, logout_user, get_current_user
from services.rag_service import get_rag_system
from rank_bm25 import BM25Okapi
from utils.config import UPLOAD_FOLDER, MAX_FILE_SIZE, SECRET_KEY
from utils.file_utils import allowed_file

app = Flask(__name__)
app.secret_key = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")

@app.route('/')
def index():
    if 'user_id' in session:
        user = get_current_user()
        if user['role'] == 'admin':
            return redirect(url_for('admin'))
        elif user['role'] == 'teacher':
            return redirect(url_for('upload'))
        else:
            return redirect(url_for('student_quizzes'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        if username and password:
            user = verify_user(username, password)
            if user:
                login_user(user)
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin():
    if request.method == 'POST':
        action = request.form.get('action', 'add')
        if action == 'add':
            username = request.form['username']
            password = request.form['password']
            role = request.form['role']
            subject_ids = request.form.getlist('subject_ids')
            try:
                uid = add_user(username, password, role)
                if subject_ids and role in ['student', 'teacher']:
                    for sid in subject_ids:
                        assign_user_subject(uid, sid)
                flash(f'User {username} created successfully!', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
        elif action == 'edit':
            user_id = request.form.get('user_id')
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            role = request.form.get('role')
            subject_ids = request.form.getlist('subject_ids')
            try:
                if user_id and username:
                    update_user(user_id, username, password if password else None, role)
                    if role in ['student', 'teacher']:
                        remove_user_subjects(user_id)
                        for sid in subject_ids:
                            assign_user_subject(user_id, sid)
                    flash(f'User {username} updated successfully!', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
    users = get_all_users()
    subjects = get_subjects()
    for user in users:
        user_subjects = get_user_subjects(user['id'])
        user['subjects'] = user_subjects
        user['subject_ids'] = [s['id'] for s in user_subjects]
    return render_template('admin.html', users=users, subjects=subjects)

@app.route('/delete_user/<int:user_id>')
@admin_required
def delete_user_route(user_id):
    if user_id == session['user_id']:
        flash('Cannot delete your own account', 'error')
    else:
        delete_user(user_id)
        flash('User deleted', 'success')
    return redirect(url_for('admin'))

@app.route('/manage_subjects', methods=['GET', 'POST'])
@admin_required
def manage_subjects():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            name = request.form.get('name', '').strip()
            if name:
                try:
                    add_subject(name)
                    flash(f'Subject "{name}" added successfully', 'success')
                except Exception as e:
                    flash(f'Error: {str(e)}', 'error')
        elif action == 'update':
            subject_id = request.form.get('subject_id')
            name = request.form.get('name', '').strip()
            if subject_id and name:
                try:
                    update_subject(int(subject_id), name)
                    flash(f'Subject updated successfully', 'success')
                except Exception as e:
                    flash(f'Error: {str(e)}', 'error')
    subjects = get_subjects()
    return render_template('manage_subjects.html', subjects=subjects)

@app.route('/delete_subject/<int:subject_id>')
@admin_required
def delete_subject_route(subject_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM materials WHERE subject_id = ?', (subject_id,))
        mat_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM quizzes WHERE subject_id = ?', (subject_id,))
        quiz_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM user_subjects WHERE subject_id = ?', (subject_id,))
        user_count = cursor.fetchone()[0]
        conn.close()
        if mat_count > 0 or quiz_count > 0 or user_count > 0:
            flash('Cannot delete subject: it is being used by materials, quizzes, or users', 'error')
        else:
            delete_subject(subject_id)
            flash('Subject deleted successfully', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('manage_subjects'))

@app.route('/upload', methods=['GET', 'POST'])
@teacher_required
def upload():
    user = get_current_user()
    rag = get_rag_system()
    if request.method == 'POST':
        files = request.files.getlist('files')
        subj_id = request.form.get('subject_id')
        if not files or all(f.filename == '' for f in files):
            flash('No files selected', 'error')
            return redirect(url_for('upload'))
        if not subj_id:
            flash('Please select a subject', 'error')
            return redirect(url_for('upload'))
        uploaded = []
        for f in files:
            if f and allowed_file(f.filename):
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(0)
                if size > MAX_FILE_SIZE:
                    flash(f'File {f.filename} too large', 'error')
                    continue
                fname = secure_filename(f.filename)
                uniq_name = f"{uuid.uuid4()}_{fname}"
                path = os.path.join(UPLOAD_FOLDER, uniq_name)
                f.save(path)
                if fname.lower().endswith('.pdf'):
                    txt = rag.extract_pdf(path)
                else:
                    txt = rag.extract_txt(path)
                if txt.strip():
                    uploaded.append(path)
                    add_material(fname, txt, subj_id, indexed=0)
                else:
                    os.remove(path)
                    flash(f'Could not extract text from {fname}', 'error')
        if uploaded:
            try:
                mats = get_materials()
                rag.rebuild_from_db(mats)
                flash(f'Uploaded {len(uploaded)} file(s)', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('upload'))
    mats = get_materials()
    subs = get_user_subjects(user['id'])
    all_subjects = get_subjects()
    subject_dict = {s['id']: s['name'] for s in all_subjects}
    for mat in mats:
        mat['subject_name'] = subject_dict.get(mat['subject_id'], 'Unknown')
    return render_template('upload.html', materials=mats, subjects=subs)

@app.route('/index_material/<int:material_id>')
@teacher_required
def index_material(material_id):
    try:
        material = get_material_by_id(material_id)
        if not material:
            flash('Material not found', 'error')
            return redirect(url_for('upload'))
        rag = get_rag_system()
        mats = get_materials()
        rag.rebuild_from_db(mats)
        update_material_indexed(material_id, indexed=1)
        flash(f'Material "{material["filename"]}" indexed successfully', 'success')
    except Exception as e:
        flash(f'Error indexing material: {str(e)}', 'error')
    return redirect(url_for('upload'))

@app.route('/delete_material/<int:material_id>')
@teacher_required
def delete_material_route(material_id):
    try:
        material = get_material_by_id(material_id)
        if not material:
            flash('Material not found', 'error')
            return redirect(url_for('upload'))
        filename = material['filename']
        if delete_material(material_id):
            rag = get_rag_system()
            mats = get_materials()
            if mats:
                rag.rebuild_from_db(mats)
            else:
                rag.chunks = []
                rag.meta = []
                rag.bm25 = None
                rag.nn = None
                rag.embeddings = None
            flash(f'Material "{filename}" deleted successfully', 'success')
        else:
            flash('Error deleting material', 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    return redirect(url_for('upload'))

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    user = get_current_user()
    if user['role'] == 'admin':
        flash('Admins cannot use chat', 'error')
        return redirect(url_for('admin'))
    rag = get_rag_system()
    if rag is None or not rag.chunks:
        flash('No materials available yet', 'warning')
        if user['role'] == 'student':
            return redirect(url_for('student_quizzes'))
        else:
            return redirect(url_for('upload'))
    if request.method == 'POST':
        q = request.form['question'].strip()
        ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if q:
            try:
                import time
                start_time = time.time()
                ans, srcs = rag.query(q, top_k=3)
                response_time = time.time() - start_time
                
                avg_confidence = sum(s.get('score', 0) for s in srcs) / len(srcs) if srcs else 0
                source_data = [{'chunk': s.get('chunk', ''), 'score': s.get('score', 0), 'metadata': s.get('metadata', {})} for s in srcs]
                
                log_qa(session['user_id'], q, ans, response_time, source_data, avg_confidence)
                
                if 'chat_history' not in session:
                    session['chat_history'] = []
                session['chat_history'].append({'question': q, 'answer': ans, 'sources': srcs, 'confidence': avg_confidence})
                if len(session['chat_history']) > 10:
                    session['chat_history'] = session['chat_history'][-10:]
                session.modified = True
                if ajax:
                    return jsonify({
                        'success': True,
                        'question': q,
                        'answer': ans,
                        'sources': [{'metadata': s.get('metadata', {}), 'score': s.get('score', 0), 'chunk': s.get('chunk', '')[:100]} for s in srcs],
                        'confidence': round(avg_confidence * 100, 1),
                        'response_time': round(response_time, 2)
                    })
            except Exception as e:
                if ajax:
                    return jsonify({'success': False, 'error': str(e)})
                flash(f'Error: {str(e)}', 'error')
        else:
            if ajax:
                return jsonify({'success': False, 'error': 'Empty question'})
    history = session.get('chat_history', [])
    return render_template('chat.html', chat_history=history)

@app.route('/chat_teacher', methods=['GET', 'POST'])
@login_required
def chat_teacher():
    user = get_current_user()
    if user['role'] == 'admin':
        flash('Admins cannot use chat', 'error')
        return redirect(url_for('admin'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if user['role'] == 'student':
        cursor.execute('SELECT DISTINCT u.id, u.username FROM users u JOIN user_subjects us1 ON u.id = us1.user_id JOIN user_subjects us2 ON us1.subject_id = us2.subject_id WHERE u.role = "teacher" AND us2.user_id = ?', (user['id'],))
    else:
        cursor.execute('SELECT DISTINCT u.id, u.username FROM users u JOIN user_subjects us1 ON u.id = us1.user_id JOIN user_subjects us2 ON us1.subject_id = us2.subject_id WHERE u.role = "student" AND us2.user_id = ?', (user['id'],))
    teachers = cursor.fetchall()
    conn.close()
    
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')
        message = request.form.get('message', '').strip()
        if teacher_id and message:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('INSERT INTO teacher_chat (from_id, to_id, message) VALUES (?, ?, ?)', (user['id'], teacher_id, message))
                message_id = cursor.lastrowid
                cursor.execute('SELECT tc.*, u1.username as from_name, u2.username as to_name FROM teacher_chat tc JOIN users u1 ON tc.from_id = u1.id JOIN users u2 ON tc.to_id = u2.id WHERE tc.id = ?', (message_id,))
                msg_data = cursor.fetchone()
                conn.commit()
                conn.close()
                
                # Format timestamp - handle both string and datetime objects
                timestamp = msg_data[4]
                if timestamp:
                    if isinstance(timestamp, datetime):
                        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(timestamp, str):
                        timestamp_str = timestamp
                    else:
                        timestamp_str = str(timestamp)
                else:
                    timestamp_str = ''
                
                # Emit WebSocket event for real-time messaging
                room_name = f'chat_{min(int(user["id"]), int(teacher_id))}_{max(int(user["id"]), int(teacher_id))}'
                socketio.emit('new_message', {
                    'id': msg_data[0],
                    'from_id': msg_data[1],
                    'to_id': msg_data[2],
                    'message': msg_data[3],
                    'timestamp': timestamp_str,
                    'from_name': msg_data[5],
                    'to_name': msg_data[6]
                }, room=room_name)
                
                if is_ajax:
                    return jsonify({
                        'success': True,
                        'message': {
                            'id': msg_data[0],
                            'from_id': msg_data[1],
                            'to_id': msg_data[2],
                            'message': msg_data[3],
                            'timestamp': timestamp_str,
                            'from_name': msg_data[5],
                            'to_name': msg_data[6]
                        }
                    })
                flash('Message sent', 'success')
            except Exception as e:
                if is_ajax:
                    return jsonify({'success': False, 'error': str(e)})
                flash(f'Error: {str(e)}', 'error')
        else:
            if is_ajax:
                return jsonify({'success': False, 'error': 'Missing teacher_id or message'})
        if is_ajax:
            return jsonify({'success': False, 'error': 'Invalid request'})
        return redirect(url_for('chat_teacher'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    if user['role'] == 'student':
        cursor.execute('SELECT tc.*, u1.username as from_name, u2.username as to_name FROM teacher_chat tc JOIN users u1 ON tc.from_id = u1.id JOIN users u2 ON tc.to_id = u2.id WHERE tc.from_id = ? OR tc.to_id = ? ORDER BY tc.timestamp DESC LIMIT 50', (user['id'], user['id']))
    else:
        cursor.execute('SELECT tc.*, u1.username as from_name, u2.username as to_name FROM teacher_chat tc JOIN users u1 ON tc.from_id = u1.id JOIN users u2 ON tc.to_id = u2.id WHERE tc.from_id = ? OR tc.to_id = ? ORDER BY tc.timestamp DESC LIMIT 50', (user['id'], user['id']))
    messages = cursor.fetchall()
    conn.close()
    return render_template('chat_teacher.html', teachers=teachers, messages=messages, user=user)

@app.route('/chat_teacher/api/messages')
@login_required
def get_chat_messages():
    user = get_current_user()
    other_user_id = request.args.get('other_user_id', type=int)
    
    if not other_user_id:
        return jsonify({'success': False, 'error': 'Missing other_user_id'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT tc.*, u1.username as from_name, u2.username as to_name 
        FROM teacher_chat tc 
        JOIN users u1 ON tc.from_id = u1.id 
        JOIN users u2 ON tc.to_id = u2.id 
        WHERE (tc.from_id = ? AND tc.to_id = ?) OR (tc.from_id = ? AND tc.to_id = ?)
        ORDER BY tc.timestamp ASC
        LIMIT 100
    ''', (user['id'], other_user_id, other_user_id, user['id']))
    rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for row in rows:
        timestamp = row[4]
        if timestamp:
            if isinstance(timestamp, datetime):
                timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            elif isinstance(timestamp, str):
                timestamp_str = timestamp
            else:
                timestamp_str = str(timestamp)
        else:
            timestamp_str = ''
        
        messages.append({
            'id': row[0],
            'from_id': row[1],
            'to_id': row[2],
            'message': row[3],
            'timestamp': timestamp_str,
            'from_name': row[5],
            'to_name': row[6]
        })
    
    return jsonify({'success': True, 'messages': messages})

@app.route('/create_quiz', methods=['GET', 'POST'])
@teacher_required
def create_quiz_route():
    if request.method == 'POST':
        title = request.form['title']
        sid = request.form['subject_id']
        desc = request.form['description']
        num_q = int(request.form.get('num_questions', 5))
        try:
            rag = get_rag_system()
            qs = rag.generate_quiz(num_q, desc, sid)
            if qs:
                qid = create_quiz(title, sid, session['user_id'], qs)
                flash(f'Quiz "{title}" created!', 'success')
                return redirect(url_for('my_quizzes'))
            else:
                flash('Failed to generate quiz', 'error')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    teacher_subs = get_user_subjects(session['user_id'])
    return render_template('create_quiz.html', subjects=teacher_subs)

@app.route('/assign_quiz/<int:quiz_id>', methods=['GET', 'POST'])
@teacher_required
def assign_quiz(quiz_id):
    quiz = get_quiz_by_id(quiz_id)
    if not quiz or quiz['teacher_id'] != session['user_id']:
        flash('Quiz not found', 'error')
        return redirect(url_for('my_quizzes'))
    if request.method == 'POST':
        sids = request.form.getlist('student_ids')
        if sids:
            assign_quiz_to_students(quiz_id, sids)
            flash('Quiz assigned!', 'success')
            return redirect(url_for('my_quizzes'))
        else:
            flash('Please select students', 'error')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT student_id FROM quiz_assignments WHERE quiz_id = ?', (quiz_id,))
    assigned = set(row[0] for row in cursor.fetchall())
    quiz_subject_id = quiz.get('subject_id')
    if quiz_subject_id:
        cursor.execute('SELECT DISTINCT u.id, u.username FROM users u JOIN user_subjects us ON u.id = us.user_id WHERE u.role = "student" AND us.subject_id = ?', (quiz_subject_id,))
    else:
        cursor.execute('SELECT id, username FROM users WHERE role = "student"')
    students = []
    for row in cursor.fetchall():
        students.append({'id': row[0], 'username': row[1], 'assigned': row[0] in assigned})
    conn.close()
    return render_template('assign_quiz.html', quiz=quiz, students=students)

@app.route('/my_quizzes')
@teacher_required
def my_quizzes():
    quizzes = get_teacher_quizzes(session['user_id'])
    return render_template('my_quizzes.html', quizzes=quizzes)

@app.route('/edit_quiz/<int:quiz_id>', methods=['GET', 'POST'])
@teacher_required
def edit_quiz(quiz_id):
    quiz = get_quiz_by_id(quiz_id)
    if not quiz or quiz['teacher_id'] != session['user_id']:
        flash('Quiz not found', 'error')
        return redirect(url_for('my_quizzes'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM quiz_assignments WHERE quiz_id = ?', (quiz_id,))
    assigned_count = cursor.fetchone()[0]
    conn.close()
    
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            questions = quiz['questions'] if isinstance(quiz['questions'], list) else json.loads(quiz['questions'])
            
            if action == 'add':
                question_text = request.form.get('question', '').strip()
                option_a = request.form.get('option_a', '').strip()
                option_b = request.form.get('option_b', '').strip()
                option_c = request.form.get('option_c', '').strip()
                option_d = request.form.get('option_d', '').strip()
                correct = request.form.get('correct', '').strip().upper()
                
                if question_text and option_a and option_b and option_c and option_d and correct in ['A', 'B', 'C', 'D']:
                    new_question = {
                        'question': question_text,
                        'options': [option_a, option_b, option_c, option_d],
                        'correct': correct,
                        'type': 'multiple_choice'
                    }
                    questions.append(new_question)
                    update_quiz_questions(quiz_id, questions)
                    flash('Question added successfully', 'success')
                else:
                    flash('Invalid question data', 'error')
            
            elif action == 'delete':
                question_index = int(request.form.get('question_index'))
                if 0 <= question_index < len(questions):
                    questions.pop(question_index)
                    update_quiz_questions(quiz_id, questions)
                    flash('Question deleted successfully', 'success')
                else:
                    flash('Invalid question index', 'error')
            
            elif action == 'generate':
                num_q = int(request.form.get('num_questions', 1))
                desc = request.form.get('description', '')
                sid = quiz.get('subject_id')
                try:
                    rag = get_rag_system()
                    existing_questions = questions
                    new_qs = rag.generate_quiz(num_q, desc, sid, difficulty="medium", existing_questions=existing_questions)
                    if new_qs:
                        questions.extend(new_qs)
                        update_quiz_questions(quiz_id, questions)
                        flash(f'{len(new_qs)} question(s) generated successfully', 'success')
                    else:
                        flash('Failed to generate questions', 'error')
                except Exception as e:
                    flash(f'Error generating questions: {str(e)}', 'error')
            
            return redirect(url_for('edit_quiz', quiz_id=quiz_id))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    questions = quiz['questions'] if isinstance(quiz['questions'], list) else json.loads(quiz['questions'])
    return render_template('edit_quiz.html', quiz=quiz, questions=questions, assigned_count=assigned_count)

@app.route('/student_quizzes')
@login_required
def student_quizzes():
    user = get_current_user()
    if user['role'] != 'student':
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    quizzes = get_student_quizzes(user['id'])
    conn = get_db_connection()
    cursor = conn.cursor()
    for quiz in quizzes:
        cursor.execute('SELECT id, score, time FROM quiz_results WHERE user_id = ? AND quiz_id = ? ORDER BY time DESC LIMIT 1', (user['id'], quiz['id']))
        result = cursor.fetchone()
        if result:
            quiz['completed_time'] = result[2]
            quiz['score'] = round(result[1], 1)
        else:
            quiz['completed_time'] = None
            quiz['score'] = None
    conn.close()
    return render_template('student_quizzes.html', quizzes=quizzes)

@app.route('/take_quiz/<int:quiz_id>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_id):
    user = get_current_user()
    if user['role'] != 'student':
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    quiz = get_quiz_by_id(quiz_id)
    if not quiz:
        flash('Quiz not found', 'error')
        return redirect(url_for('student_quizzes'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM quiz_results WHERE user_id = ? AND quiz_id = ?', (user['id'], quiz_id))
    if cursor.fetchone():
        flash('You already completed this quiz', 'info')
        conn.close()
        return redirect(url_for('student_quizzes'))
    conn.close()
    try:
        qs = json.loads(quiz['questions']) if isinstance(quiz['questions'], str) else quiz['questions']
    except:
        qs = quiz['questions']
    if request.method == 'POST':
        ans = []
        correct = 0
        for i, q in enumerate(qs):
            key = f'q{i}'
            u_ans = request.form.get(key, '').strip().upper()
            corr_ans = q['correct'].strip().upper()
            if u_ans == corr_ans:
                correct += 1
            ans.append({'question': q['question'], 'user_answer': u_ans, 'correct_answer': corr_ans, 'is_correct': u_ans == corr_ans})
        score = (correct / len(qs)) * 100
        log_quiz_result(user['id'], score, ans, quiz_id)
        return redirect(url_for('student_quizzes'))
    return render_template('take_quiz.html', quiz=quiz, questions=qs)

@app.route('/notes', methods=['GET', 'POST'])
@login_required
def notes():
    user = get_current_user()
    if user['role'] != 'student':
        flash('Access denied', 'error')
        return redirect(url_for('index'))
    
    user_subjects = get_user_subjects(user['id'])
    filter_subject = request.args.get('subject_id', type=int)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '')
            subject_id = request.form.get('subject_id', type=int)
            if title:
                note_id = create_note(user['id'], title, content, subject_id)
                if note_id:
                    flash('Note created successfully', 'success')
                else:
                    flash('Error creating note', 'error')
            else:
                flash('Title is required', 'error')
        elif action == 'update':
            note_id = request.form.get('note_id')
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '')
            subject_id = request.form.get('subject_id', type=int)
            if note_id and title:
                if update_note(int(note_id), user['id'], title, content, subject_id):
                    flash('Note updated successfully', 'success')
                else:
                    flash('Error updating note', 'error')
            else:
                flash('Title is required', 'error')
        elif action == 'delete':
            note_id = request.form.get('note_id')
            if note_id:
                if delete_note(int(note_id), user['id']):
                    flash('Note deleted successfully', 'success')
                else:
                    flash('Error deleting note', 'error')
        return redirect(url_for('notes', subject_id=filter_subject))
    
    user_notes = get_user_notes(user['id'], filter_subject)
    return render_template('notes.html', notes=user_notes, subjects=user_subjects, filter_subject=filter_subject)

@app.route('/notes/<int:note_id>')
@login_required
def get_note(note_id):
    user = get_current_user()
    if user['role'] != 'student':
        return jsonify({'error': 'Access denied'}), 403
    note = get_note_by_id(note_id, user['id'])
    if note:
        return jsonify(note)
    return jsonify({'error': 'Note not found'}), 404

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = get_current_user()
    if request.method == 'POST':
        new_username = request.form.get('username', '')
        new_password = request.form.get('password', '')
        if new_username:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET username = ? WHERE id = ?', (new_username, user['id']))
            if new_password:
                pwd_hash = hashlib.sha256(new_password.encode()).hexdigest()
                cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (pwd_hash, user['id']))
            conn.commit()
            conn.close()
            session['username'] = new_username
            flash('Profile updated', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user)

@app.route('/query_history')
@admin_required
def query_history():
    logs = get_qa_logs()
    conn = get_db_connection()
    cursor = conn.cursor()
    for log in logs:
        cursor.execute('SELECT username FROM users WHERE id = ?', (log['user_id'],))
        user_row = cursor.fetchone()
        log['username'] = user_row[0] if user_row else 'Unknown'
        log['corrections'] = get_qa_corrections(log['id'])
    conn.close()
    return render_template('query_history.html', logs=logs)

@app.route('/correct_answer/<int:qa_log_id>', methods=['POST'])
@teacher_required
def correct_answer(qa_log_id):
    corrected_answer = request.form.get('corrected_answer', '').strip()
    if corrected_answer:
        correction_id = add_qa_correction(qa_log_id, session['user_id'], corrected_answer)
        if correction_id:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT question FROM qa_logs WHERE id = ?', (qa_log_id,))
                qa_row = cursor.fetchone()
                conn.close()
                if qa_row:
                    question = qa_row[0]
                    rag = get_rag_system()
                    correction_text = f"Question: {question}\nCorrect Answer: {corrected_answer}"
                    rag.chunks.append(correction_text)
                    rag.meta.append({'file': 'correction', 'chunk_id': len(rag.chunks)-1, 'file_path': 'correction', 'subject_id': None})
                    if rag.chunks:
                        from rank_bm25 import BM25Okapi
                        tokenized_chunks = [chunk.lower().split() for chunk in rag.chunks]
                        rag.bm25 = BM25Okapi(tokenized_chunks)
                        rag.embeddings = rag.get_embeddings(rag.chunks)
                        embed_count = len(rag.embeddings)
                        k_value = min(10, max(1, embed_count))
                        from sklearn.neighbors import NearestNeighbors
                        rag.nn = NearestNeighbors(n_neighbors=k_value, metric='cosine')
                        rag.nn.fit(rag.embeddings)
                    flash('Correction added and indexed successfully', 'success')
            except Exception as e:
                flash(f'Error indexing correction: {str(e)}', 'error')
        else:
            flash('Error saving correction', 'error')
    else:
        flash('Please provide a corrected answer', 'error')
    return redirect(request.referrer or url_for('query_history'))

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('join_room')
def handle_join_room(data):
    user_id = data.get('user_id')
    other_user_id = data.get('other_user_id')
    if user_id and other_user_id:
        room_name = f'chat_{min(int(user_id), int(other_user_id))}_{max(int(user_id), int(other_user_id))}'
        join_room(room_name)
        print(f'User {user_id} joined room {room_name}')

@socketio.on('leave_room')
def handle_leave_room(data):
    user_id = data.get('user_id')
    other_user_id = data.get('other_user_id')
    if user_id and other_user_id:
        room_name = f'chat_{min(int(user_id), int(other_user_id))}_{max(int(user_id), int(other_user_id))}'
        leave_room(room_name)
        print(f'User {user_id} left room {room_name}')

if __name__ == '__main__':
    init_db()
    get_rag_system()
    port = int(os.environ.get('PORT', 2121))
    socketio.run(app, debug=True, host='0.0.0.0', port=port)
