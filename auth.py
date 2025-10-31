from flask import session,redirect,url_for,flash

def login_required(f):
	def wrapper(*args,**kwargs):
		if 'user_id' not in session:
			flash('You need to login first','error')
			return redirect(url_for('login'))
		return f(*args,**kwargs)
	wrapper.__name__=f.__name__
	return wrapper

def admin_required(f):
	def wrapper(*args,**kwargs):
		if 'user_id' not in session:
			flash('Login required','error')
			return redirect(url_for('login'))
		if session.get('role')!='admin':
			flash('Only admin can access this','error')
			return redirect(url_for('login'))
		return f(*args,**kwargs)
	wrapper.__name__=f.__name__
	return wrapper

def teacher_required(f):
	def wrapper(*args,**kwargs):
		if 'user_id' not in session:
			flash('Login required','error')
			return redirect(url_for('login'))
		user_role=session.get('role')
		if user_role not in ['admin','teacher']:
			flash('Only teachers and admin can access this','error')
			if user_role=='student':
				return redirect(url_for('student_quizzes'))
			return redirect(url_for('login'))
		return f(*args,**kwargs)
	wrapper.__name__=f.__name__
	return wrapper

def login_user(user):
	session['user_id']=user['id']
	session['username']=user['username']
	session['role']=user['role']

def logout_user():
	session.clear()

def get_current_user():
	user_id,username,role=session.get('user_id'),session.get('username'),session.get('role')
	return {'id':user_id,'username':username,'role':role}