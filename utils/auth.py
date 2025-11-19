from flask import session, redirect, url_for, flash
from functools import wraps

def login_required(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		if 'user_id' not in session:
			flash('You need to login first', 'error')
			return redirect(url_for('login'))
		return f(*args, **kwargs)
	return wrapper

def admin_required(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		if 'user_id' not in session or session.get('role') != 'admin':
			flash('Access denied', 'error')
			return redirect(url_for('login'))
		return f(*args, **kwargs)
	return wrapper

def teacher_required(f):
	@wraps(f)
	def wrapper(*args, **kwargs):
		if 'user_id' not in session:
			flash('Login required', 'error')
			return redirect(url_for('login'))
		if session.get('role') not in ['admin', 'teacher']:
			flash('Access denied', 'error')
			return redirect(url_for('student_quizzes') if session.get('role') == 'student' else url_for('login'))
		return f(*args, **kwargs)
	return wrapper

def login_user(user):
	session['user_id'] = user['id']
	session['username'] = user['username']
	session['role'] = user['role']

def logout_user():
	session.clear()

def get_current_user():
	return {'id': session.get('user_id'), 'username': session.get('username'), 'role': session.get('role')}

