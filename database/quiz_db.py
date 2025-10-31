from db import get_db_connection
import json

def get_quiz_result(result_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT qr.*, q.title, q.questions FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.id = ? AND qr.user_id = ?', (result_id, user_id))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return None
    
    quiz = {'title': result[6]}
    try:
        answers = json.loads(result[4]) if isinstance(result[4], str) else result[4]
        quiz_questions = json.loads(result[7]) if isinstance(result[7], str) else result[7]
    except:
        answers = result[4]
        quiz_questions = result[7]
    
    for i, answer in enumerate(answers):
        if i < len(quiz_questions):
            answer['options'] = quiz_questions[i].get('options', [])
    
    score = result[3]
    correct = sum(1 for a in answers if a.get('is_correct', False))
    total = len(answers)
    percentage = round(score, 1)
    
    return {
        'quiz': quiz,
        'score': score,
        'total': total,
        'correct': correct,
        'percentage': percentage,
        'answers': answers,
        'quiz_questions': quiz_questions
    }

