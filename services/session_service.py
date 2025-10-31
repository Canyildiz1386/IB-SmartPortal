from flask import session as flask_session
from flask_socketio import emit, join_room, leave_room
from database.db import get_db_connection, log_qa
from database.session_db import join_session, leave_session, add_session_message, get_session_participants
from services.rag_service import get_rag_system
import time

def handle_join_session_socket(data, socketio):
    session_id = data.get('session_id')
    user_id = flask_session.get('user_id')
    if user_id and session_id:
        join_room(f'session_{session_id}')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (user_id,))
        user_row = cursor.fetchone()
        conn.close()
        if user_row:
            user = {'id': user_row[0], 'username': user_row[1], 'role': user_row[2]}
            join_session(session_id, user_id)
            participants = get_session_participants(session_id)
            emit('user_joined', {'username': user['username'], 'participants': participants}, room=f'session_{session_id}')

def handle_leave_session_socket(data, socketio):
    session_id = data.get('session_id')
    user_id = flask_session.get('user_id')
    if user_id and session_id:
        leave_room(f'session_{session_id}')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (user_id,))
        user_row = cursor.fetchone()
        conn.close()
        if user_row:
            user = {'id': user_row[0], 'username': user_row[1], 'role': user_row[2]}
            leave_session(session_id, user_id)
            participants = get_session_participants(session_id)
            emit('user_left', {'username': user['username'], 'participants': participants}, room=f'session_{session_id}')

def handle_message_socket(data, socketio):
    session_id = data.get('session_id')
    user_id = flask_session.get('user_id')
    message = data.get('message', '')
    if user_id and session_id and message:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, role FROM users WHERE id = ?', (user_id,))
        user_row = cursor.fetchone()
        conn.close()
        if user_row:
            user = {'id': user_row[0], 'username': user_row[1], 'role': user_row[2]}
            if message.startswith('/ai '):
                question = message[4:].strip()
                if question:
                    try:
                        rag_system = get_rag_system()
                        if rag_system and rag_system.chunks:
                            answer, results = rag_system.query(question, top_k=3)
                            log_qa(user_id, question, answer)
                            add_session_message(session_id, user_id, f'/ai {question}')
                            emit('new_message', {
                                'username': user['username'],
                                'role': user['role'],
                                'message': f'/ai {question}',
                                'timestamp': time.time()
                            }, room=f'session_{session_id}')
                            emit('ai_response', {
                                'username': user['username'],
                                'question': question,
                                'answer': answer,
                                'timestamp': time.time()
                            }, room=f'session_{session_id}')
                        else:
                            add_session_message(session_id, user_id, message)
                            emit('new_message', {
                                'username': user['username'],
                                'role': user['role'],
                                'message': message,
                                'timestamp': time.time()
                            }, room=f'session_{session_id}')
                            emit('ai_response', {
                                'username': user['username'],
                                'question': question,
                                'answer': 'No study materials indexed yet. Please upload materials first.',
                                'timestamp': time.time()
                            }, room=f'session_{session_id}')
                    except Exception as e:
                        add_session_message(session_id, user_id, message)
                        emit('new_message', {
                            'username': user['username'],
                            'role': user['role'],
                            'message': message,
                            'timestamp': time.time()
                        }, room=f'session_{session_id}')
                        emit('ai_response', {
                            'username': user['username'],
                            'question': question,
                            'answer': f'Error: {str(e)}',
                            'timestamp': time.time()
                        }, room=f'session_{session_id}')
                else:
                    add_session_message(session_id, user_id, message)
                    emit('new_message', {
                        'username': user['username'],
                        'role': user['role'],
                        'message': message,
                        'timestamp': time.time()
                    }, room=f'session_{session_id}')
            else:
                add_session_message(session_id, user_id, message)
                emit('new_message', {
                    'username': user['username'],
                    'role': user['role'],
                    'message': message,
                    'timestamp': time.time()
                }, room=f'session_{session_id}')

def handle_offer_socket(data, socketio):
    user_id = flask_session.get('user_id')
    if user_id:
        data['user_id'] = user_id
        emit('offer', data, room=f'session_{data["session_id"]}', include_self=False)

def handle_answer_socket(data, socketio):
    user_id = flask_session.get('user_id')
    if user_id:
        data['user_id'] = user_id
        emit('answer', data, room=f'session_{data["session_id"]}', include_self=False)

def handle_ice_candidate_socket(data, socketio):
    user_id = flask_session.get('user_id')
    if user_id:
        data['user_id'] = user_id
        emit('ice_candidate', data, room=f'session_{data["session_id"]}', include_self=False)

def handle_ready_for_connections_socket(data, socketio):
    user_id = flask_session.get('user_id')
    if user_id:
        emit('ready_for_connections', {'user_id': user_id, 'session_id': data.get('session_id')}, room=f'session_{data.get("session_id")}', include_self=False)

