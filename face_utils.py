import os
import cv2
import numpy as np
from PIL import Image
from deepface import DeepFace

def prepare_uploaded_image(file_storage, save_path, brightness_threshold=40):
    image = Image.open(file_storage)
    if image.mode == 'RGBA':
        image = image.convert('RGB')
    image.save(save_path, format='JPEG')
    img = cv2.imread(save_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return False, "Image is not readable. Please try again."
    mean_brightness = img.mean()
    if mean_brightness < brightness_threshold:
        color_img = cv2.imread(save_path)
        hsv = cv2.cvtColor(color_img, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        v = cv2.equalizeHist(v)
        final_hsv = cv2.merge((h, s, v))
        brighter_img = cv2.cvtColor(final_hsv, cv2.COLOR_HSV2BGR)
        cv2.imwrite(save_path, brighter_img)
        new_brightness = cv2.cvtColor(brighter_img, cv2.COLOR_BGR2GRAY).mean()
        if new_brightness < brightness_threshold:
            os.remove(save_path)
            return False, "The image is too dark even after enhancement. Please take a photo in better lighting conditions."
    return True, "Image processed successfully."

def verify_face(registered_image_path, login_image_path):
    try:
        if not os.path.exists(registered_image_path) or not os.path.exists(login_image_path):
            return False
        verification = DeepFace.verify(
            img1_path=registered_image_path,
            img2_path=login_image_path,
            model_name='VGG-Face',
            distance_metric='cosine',
            enforce_detection=False
        )
        verified = verification.get('verified', False)
        distance = verification.get('distance', 1.0)
        threshold = verification.get('threshold', 0.4)
        if verified and distance < threshold:
            return True
        return False
    except Exception as e:
        return False

def analyze_mood(image_path):
    try:
        analysis = DeepFace.analyze(
            image_path,
            actions=['emotion', 'age', 'gender', 'race'],
            enforce_detection=False
        )
        result = analysis[0] if isinstance(analysis, list) else analysis
        return {
            'mood': result.get('dominant_emotion', 'neutral'),
            'age': result.get('age'),
            'gender': result.get('dominant_gender'),
            'race': result.get('dominant_race')
        }
    except Exception as e:
        return {
            'mood': 'neutral',
            'age': None,
            'gender': None,
            'race': None
        }

def mood_emoji(mood):
    mood_map = {
        'angry': '😡',
        'sad': '😢',
        'happy': '😄',
        'surprise': '😲',
        'fear': '😱',
        'disgust': '🤢',
        'neutral': '😐'
    }
    return mood_map.get(mood, '🙂')

def get_mood_theme(mood):
    themes = {
        'angry': {'bg': '#fee2e2', 'primary': '#dc2626', 'accent': '#ef4444'},
        'sad': {'bg': '#dbeafe', 'primary': '#2563eb', 'accent': '#3b82f6'},
        'happy': {'bg': '#fef3c7', 'primary': '#f59e0b', 'accent': '#fbbf24'},
        'surprise': {'bg': '#fce7f3', 'primary': '#ec4899', 'accent': '#f472b6'},
        'fear': {'bg': '#ede9fe', 'primary': '#7c3aed', 'accent': '#8b5cf6'},
        'disgust': {'bg': '#f0fdf4', 'primary': '#16a34a', 'accent': '#22c55e'},
        'neutral': {'bg': '#f3f4f6', 'primary': '#6b7280', 'accent': '#9ca3af'}
    }
    return themes.get(mood, themes['neutral'])

