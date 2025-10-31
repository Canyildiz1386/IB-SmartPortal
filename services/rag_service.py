import os
from services.rag import SmartStudyRAG
from database.db import get_materials

rag_instance = None

def init_rag_system():
    global rag_instance
    if rag_instance is None:
        cohere_key = os.getenv('COHERE_API_KEY')
        if not cohere_key:
            cohere_key = "nothing"
        rag_instance = SmartStudyRAG(cohere_key)
    try:
        material_list = get_materials()
        if material_list:
            rag_instance.rebuild_from_db(material_list)
    except Exception:
        pass
    return rag_instance

def get_rag_system():
    return init_rag_system()

