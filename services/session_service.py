from flask import session as flask_session
from flask_socketio import emit, join_room, leave_room
from database.db import get_db_connection, log_qa
from database.session_db import join_session, leave_session, add_session_message, get_session_participants
from services.rag_service import get_rag_system
import time

def handle_join_session_socket(socket_data, socketio):
	try:
		sid = socket_data.get('session_id')
		uid = flask_session.get('user_id')
		if uid and sid:
			join_room(f'session_{sid}')
			db_conn = get_db_connection()
			db_cursor = db_conn.cursor()
			db_cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (uid,))
			u = db_cursor.fetchone()
			db_conn.close()
			if u:
				user = {'id': u[0], 'username': u[1], 'role': u[2]}
				join_session(sid, uid)
				participants = get_session_participants(sid)
				emit('user_joined', {'username': user['username'], 'participants': participants}, room=f'session_{sid}')
	except Exception:
		pass

def handle_leave_session_socket(socket_data, socketio):
	try:
		sid = socket_data.get('session_id')
		uid = flask_session.get('user_id')
		if uid and sid:
			leave_room(f'session_{sid}')
			db_conn = get_db_connection()
			db_cursor = db_conn.cursor()
			db_cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (uid,))
			u = db_cursor.fetchone()
			db_conn.close()
			if u:
				user = {'id': u[0], 'username': u[1], 'role': u[2]}
				leave_session(sid, uid)
				participants = get_session_participants(sid)
				emit('user_left', {'username': user['username'], 'participants': participants}, room=f'session_{sid}')
	except Exception:
		pass

def handle_message_socket(socket_data, socketio):
	try:
		sid = socket_data.get('session_id')
		uid = flask_session.get('user_id')
		msg = socket_data.get('message', '')
		if uid and sid and msg:
			db_conn = get_db_connection()
			db_cursor = db_conn.cursor()
			db_cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (uid,))
			u = db_cursor.fetchone()
			db_conn.close()
			if u:
				user = {'id': u[0], 'username': u[1], 'role': u[2]}
				if msg.startswith('/ai '):
					q = msg[4:].strip()
					if q:
						try:
							rag = get_rag_system()
							if rag and rag.chunks:
								ans, srcs = rag.query(q, top_k=3)
								log_qa(uid, q, ans)
								add_session_message(sid, uid, f'/ai {q}')
								emit('new_message', {
									'username': user['username'],
									'role': user['role'],
									'message': f'/ai {q}',
									'timestamp': time.time()
								}, room=f'session_{sid}')
								emit('ai_response', {
									'username': user['username'],
									'question': q,
									'answer': ans,
									'timestamp': time.time()
								}, room=f'session_{sid}')
							else:
								add_session_message(sid, uid, msg)
								emit('new_message', {
									'username': user['username'],
									'role': user['role'],
									'message': msg,
									'timestamp': time.time()
								}, room=f'session_{sid}')
								emit('ai_response', {
									'username': user['username'],
									'question': q,
									'answer': 'No study materials indexed yet. Please upload materials first.',
									'timestamp': time.time()
								}, room=f'session_{sid}')
						except Exception as e:
							add_session_message(sid, uid, msg)
							emit('new_message', {
								'username': user['username'],
								'role': user['role'],
								'message': msg,
								'timestamp': time.time()
							}, room=f'session_{sid}')
							emit('ai_response', {
								'username': user['username'],
								'question': q,
								'answer': f'Error: {str(e)}',
								'timestamp': time.time()
							}, room=f'session_{sid}')
					else:
						add_session_message(sid, uid, msg)
						emit('new_message', {
							'username': user['username'],
							'role': user['role'],
							'message': msg,
							'timestamp': time.time()
						}, room=f'session_{sid}')
				else:
					add_session_message(sid, uid, msg)
					emit('new_message', {
						'username': user['username'],
						'role': user['role'],
						'message': msg,
						'timestamp': time.time()
					}, room=f'session_{sid}')
	except Exception:
		pass

def handle_offer_socket(socket_data, socketio):
	try:
		uid = flask_session.get('user_id')
		if uid:
			socket_data['user_id'] = uid
			emit('offer', socket_data, room=f'session_{socket_data["session_id"]}', include_self=False)
	except Exception:
		pass

def handle_answer_socket(socket_data, socketio):
	try:
		uid = flask_session.get('user_id')
		if uid:
			socket_data['user_id'] = uid
			emit('answer', socket_data, room=f'session_{socket_data["session_id"]}', include_self=False)
	except Exception:
		pass

def handle_ice_candidate_socket(socket_data, socketio):
	try:
		uid = flask_session.get('user_id')
		if uid:
			socket_data['user_id'] = uid
			emit('ice_candidate', socket_data, room=f'session_{socket_data["session_id"]}', include_self=False)
	except Exception:
		pass

def handle_ready_for_connections_socket(socket_data, socketio):
	try:
		uid = flask_session.get('user_id')
		if uid:
			emit('ready_for_connections', {'user_id': uid, 'session_id': socket_data.get('session_id')}, room=f'session_{socket_data.get("session_id")}', include_self=False)
	except Exception:
		pass
