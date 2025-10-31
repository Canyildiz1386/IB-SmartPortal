import os
import cv2
import numpy as np
from PIL import Image
from deepface import DeepFace

def prepare_uploaded_image(file_obj, save_path, brightness_threshold=40):
	try:
		img_obj = Image.open(file_obj)
		if img_obj.mode == 'RGBA':
			img_obj = img_obj.convert('RGB')
		img_obj.save(save_path, format='JPEG')
		gray_img = cv2.imread(save_path, cv2.IMREAD_GRAYSCALE)
		if gray_img is None:
			return False, "Image is not readable. Please try again."
		brightness_val = gray_img.mean()
		if brightness_val < brightness_threshold:
			color_img = cv2.imread(save_path)
			hsv_img = cv2.cvtColor(color_img, cv2.COLOR_BGR2HSV)
			h_chan, s_chan, v_chan = cv2.split(hsv_img)
			v_chan = cv2.equalizeHist(v_chan)
			enhanced_hsv = cv2.merge((h_chan, s_chan, v_chan))
			brighter_img = cv2.cvtColor(enhanced_hsv, cv2.COLOR_HSV2BGR)
			cv2.imwrite(save_path, brighter_img)
			new_brightness_val = cv2.cvtColor(brighter_img, cv2.COLOR_BGR2GRAY).mean()
			if new_brightness_val < brightness_threshold:
				os.remove(save_path)
				return False, "The image is too dark even after enhancement. Please take a photo in better lighting conditions."
		return True, "Image processed successfully."
	except Exception as e:
		return False, f"Error processing image: {str(e)}"

def verify_face(registered_path, login_path):
	try:
		if not os.path.exists(registered_path) or not os.path.exists(login_path):
			return False
		verify_result = DeepFace.verify(
			img1_path=registered_path,
			img2_path=login_path,
			model_name='VGG-Face',
			distance_metric='cosine',
			enforce_detection=False
		)
		is_verified = verify_result.get('verified', False)
		distance_val = verify_result.get('distance', 1.0)
		threshold_val = verify_result.get('threshold', 0.4)
		if is_verified and distance_val < threshold_val:
			return True
		return False
	except Exception:
		return False

def analyze_mood(img_path):
	try:
		analysis_result = DeepFace.analyze(
			img_path,
			actions=['emotion', 'age', 'gender', 'race'],
			enforce_detection=False
		)
		if isinstance(analysis_result, list):
			result_dict = analysis_result[0]
		else:
			result_dict = analysis_result
		return {
			'mood': result_dict.get('dominant_emotion', 'neutral'),
			'age': result_dict.get('age'),
			'gender': result_dict.get('dominant_gender'),
			'race': result_dict.get('dominant_race')
		}
	except Exception:
		return {
			'mood': 'neutral',
			'age': None,
			'gender': None,
			'race': None
		}

def mood_emoji(mood_str):
	emoji_map = {
		'angry': '😡',
		'sad': '😢',
		'happy': '😄',
		'surprise': '😲',
		'fear': '😱',
		'disgust': '🤢',
		'neutral': '😐'
	}
	return emoji_map.get(mood_str, '🙂')

def get_mood_theme(mood_str):
	theme_map = {
		'angry': {'bg': '#fee2e2', 'primary': '#dc2626', 'accent': '#ef4444'},
		'sad': {'bg': '#dbeafe', 'primary': '#2563eb', 'accent': '#3b82f6'},
		'happy': {'bg': '#fef3c7', 'primary': '#f59e0b', 'accent': '#fbbf24'},
		'surprise': {'bg': '#fce7f3', 'primary': '#ec4899', 'accent': '#f472b6'},
		'fear': {'bg': '#ede9fe', 'primary': '#7c3aed', 'accent': '#8b5cf6'},
		'disgust': {'bg': '#f0fdf4', 'primary': '#16a34a', 'accent': '#22c55e'},
		'neutral': {'bg': '#f3f4f6', 'primary': '#6b7280', 'accent': '#9ca3af'}
	}
	return theme_map.get(mood_str, theme_map['neutral'])
