import os

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'txt'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
MAX_FILE_SIZE = 10 * 1024 * 1024

SECRET_KEY = 'IB-Smartportal'
PERMANENT_SESSION_LIFETIME = 86400

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

