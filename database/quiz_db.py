from database.db import get_db_connection
import json

def get_quiz_result(result_id, user_id):
	try:
		db_conn = get_db_connection()
		db_cursor = db_conn.cursor()
		db_cursor.execute('SELECT qr.*, q.title, q.questions FROM quiz_results qr JOIN quizzes q ON qr.quiz_id = q.id WHERE qr.id = ? AND qr.user_id = ?', (result_id, user_id))
		result_row = db_cursor.fetchone()
		db_conn.close()
		
		if not result_row:
			return None
		
		quiz_title = result_row[6]
		try:
			answer_list = json.loads(result_row[4]) if isinstance(result_row[4], str) else result_row[4]
			question_list = json.loads(result_row[7]) if isinstance(result_row[7], str) else result_row[7]
		except Exception:
			answer_list = result_row[4]
			question_list = result_row[7]
		
		for idx, answer_item in enumerate(answer_list):
			if idx < len(question_list):
				answer_item['options'] = question_list[idx].get('options', [])
		
		score_val = result_row[3]
		correct_count = sum(1 for ans in answer_list if ans.get('is_correct', False))
		total_count = len(answer_list)
		percentage_val = round(score_val, 1)
		
		return {
			'quiz': {'title': quiz_title},
			'score': score_val,
			'total': total_count,
			'correct': correct_count,
			'percentage': percentage_val,
			'answers': answer_list,
			'quiz_questions': question_list
		}
	except Exception:
		return None
