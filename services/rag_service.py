import os
from services.rag import SmartStudyRAG
from database.db import get_materials

rag_system = None

def init_rag_system():
    global rag_system
    if rag_system is None:
        api_key = os.getenv('COHERE_API_KEY')
        if not api_key:
            api_key = "dummy_key_for_development"
        rag_system = SmartStudyRAG(api_key)
    try:
        materials = get_materials()
        if materials:
            rag_system.rebuild_from_db(materials)
    except:
        pass
    return rag_system

def get_rag_system():
    return init_rag_system()

