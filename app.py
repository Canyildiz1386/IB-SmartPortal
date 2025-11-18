from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
import os
import hashlib
import json
import uuid

from database.db import init_db, verify_user, add_user, get_all_users, delete_user, get_db_connection
from database.db import add_material, get_materials, get_subjects, get_user_subjects, assign_user_subject
from database.db import create_quiz, get_teacher_quizzes, get_student_quizzes, get_quiz_by_id, log_quiz_result, assign_quiz_to_students
from database.db import log_qa, get_qa_logs
from utils.auth import login_required, admin_required, teacher_required, login_user, logout_user, get_current_user
from services.rag_service import get_rag_system
from utils.config import UPLOAD_FOLDER, USER_IMAGES_FOLDER, MAX_FILE_SIZE, SECRET_KEY
from utils.file_utils import allowed_file

app = Flask(__name__)
app.secret_key = SECRET_KEY

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
    users = get_all_users()
    subjects = get_subjects()
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
    return render_template('upload.html', materials=mats, subjects=subs)

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
                ans, srcs = rag.query(q, top_k=3)
                log_qa(session['user_id'], q, ans)
                if 'chat_history' not in session:
                    session['chat_history'] = []
                session['chat_history'].append({'question': q, 'answer': ans, 'sources': srcs})
                if len(session['chat_history']) > 10:
                    session['chat_history'] = session['chat_history'][-10:]
                session.modified = True
                if ajax:
                    return jsonify({
                        'success': True,
                        'question': q,
                        'answer': ans,
                        'sources': [{'metadata': s.get('metadata', {}), 'score': s.get('score', 0)} for s in srcs]
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
    if request.method == 'POST':
        teacher_id = request.form.get('teacher_id')
        message = request.form.get('message', '').strip()
        if teacher_id and message:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('INSERT INTO teacher_chat (from_id, to_id, message) VALUES (?, ?, ?)', (user['id'], teacher_id, message))
                conn.commit()
                conn.close()
                flash('Message sent', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
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

if __name__ == '__main__':
    init_db()
    get_rag_system()
    port = int(os.environ.get('PORT', 2121))
    app.run(debug=True, host='0.0.0.0', port=port)
