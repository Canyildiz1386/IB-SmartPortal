from flask import session, redirect, url_for, flash

def login_required(f):
    def check_login(*args, **kwargs):
        if 'user_id' not in session:
            flash('You need to login first', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return check_login

def admin_required(f):
    def check_admin(*args, **kwargs):
        if 'user_id' not in session:
            flash('Login required', 'error')
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Only admin can access this', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return check_admin

def teacher_required(f):
    def check_teacher(*args, **kwargs):
        if 'user_id' not in session:
            flash('Login required', 'error')
            return redirect(url_for('login'))
        user_role = session.get('role')
        if user_role not in ['admin', 'teacher']:
            flash('Only teachers and admin can access this', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return check_teacher

def login_user(user):
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']

def logout_user():
    session.clear()

def get_current_user():
    user_id = session.get('user_id')
    username = session.get('username')
    role = session.get('role')
    return {
        'id': user_id,
        'username': username,
        'role': role
    }