import os,time
import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.neighbors import NearestNeighbors
import cohere

class SmartStudyRAG:
	def __init__(self,api_key):
		self.client=cohere.Client(api_key)
		self.chunks=[]
		self.meta=[]
		self.bm25=None
		self.nn=None
		self.embeddings=None
		self.alpha=0.7
		self.last_time=0
		self.delay=2.0

	def chunk_text(self,text,chunk_size=500,overlap=50,subject_id=None):
		words=text.split()
		chunks=[]
		for i in range(0,len(words),chunk_size-overlap):
			chunk=' '.join(words[i:i+chunk_size])
			if chunk.strip():chunks.append(chunk.strip())
		return chunks

	def extract_pdf(self,path):
		try:
			import pypdf
			with open(path,'rb') as file:
				reader=pypdf.PdfReader(file)
				text=""
				for page in reader.pages:text+=page.extract_text()+"\n"
				return text
		except:return ""

	def extract_txt(self,path):
		try:
			with open(path,'r',encoding='utf-8') as file:return file.read()
		except:return ""

	def rate_limit(self):
		current_time=time.time()
		time_diff=current_time-self.last_time
		if time_diff<self.delay:time.sleep(self.delay-time_diff)
		self.last_time=time.time()

	def get_embeddings(self,texts):
		self.rate_limit()
		response=self.client.embed(texts=texts,model='embed-english-v3.0',input_type='search_document')
		return np.array(response.embeddings)

	def build_index(self,files,subject_id=None):
		all_chunks,all_meta=[],[]
		for file_path in files:
			if isinstance(file_path,dict):file_path=file_path.get('file_path','')
			if not isinstance(file_path,str):continue
			if file_path.lower().endswith('.pdf'):text=self.extract_pdf(file_path)
			elif file_path.lower().endswith('.txt'):text=self.extract_txt(file_path)
			else:continue
			if not text.strip():continue
			chunks=self.chunk_text(text,subject_id=subject_id)
			for i,chunk in enumerate(chunks):
				all_chunks.append(chunk)
				all_meta.append({'file':os.path.basename(file_path),'chunk_id':i,'file_path':file_path,'subject_id':subject_id})
		if not all_chunks:raise ValueError("No valid text chunks found")
		self.chunks=all_chunks
		self.meta=all_meta
		tokenized=[chunk.lower().split() for chunk in all_chunks]
		self.bm25=BM25Okapi(tokenized)
		self.embeddings=self.get_embeddings(all_chunks)
		num_samples=len(self.embeddings)
		n_neighbors=min(10,max(1,num_samples))
		self.nn=NearestNeighbors(n_neighbors=n_neighbors,metric='cosine')
		self.nn.fit(self.embeddings)

	def search(self,query,top_k=5):
		if not self.chunks or self.bm25 is None or self.nn is None:return []
		query_tokens=query.lower().split()
		bm25_scores=self.bm25.get_scores(query_tokens)
		query_embedding=self.get_embeddings([query])
		
		num_samples=len(self.chunks)
		if num_samples==0:return []
		
		try:
			max_neighbors=min(self.nn.n_neighbors,num_samples)
			nn_distances,nn_indices=self.nn.kneighbors(query_embedding,n_neighbors=max_neighbors)
		except ValueError as e:
			nn_distances,nn_indices=self.nn.kneighbors(query_embedding,n_neighbors=num_samples)
		
		combined_scores=[]
		nn_score_map={}
		if len(nn_indices[0])>0:
			for pos,chunk_idx in enumerate(nn_indices[0]):
				distance=nn_distances[0][pos] if pos<len(nn_distances[0]) else 1.0
				nn_score_map[chunk_idx]=1-distance
		
		for i in range(len(self.chunks)):
			bm25_score=bm25_scores[i]
			nn_score=nn_score_map.get(i,0)
			combined_score=self.alpha*bm25_score+(1-self.alpha)*nn_score
			combined_scores.append((i,combined_score))
		combined_scores.sort(key=lambda x:x[1],reverse=True)
		results=[]
		seen_files={}
		max_per_file=max(1,top_k//3)
		for i,score in combined_scores:
			if len(results)>=top_k:break
			file_name=self.meta[i]['file']
			file_count=seen_files.get(file_name,0)
			if file_count<max_per_file:
				results.append({'chunk':self.chunks[i],'score':score,'metadata':self.meta[i]})
				seen_files[file_name]=file_count+1
		return results

	def generate_answer(self,question,search_results,user_grade=None):
		if not search_results:return "I don't have enough information to answer that question."
		context="\n\n".join([result['chunk'] for result in search_results])
		self.rate_limit()
		grade_context=""
		if user_grade:
			grade_context=f"\n\nIMPORTANT: The student asking this question is in {user_grade} grade. Please tailor your explanation to be appropriate for their grade level. Use language and concepts that are suitable for a {user_grade} grade student. Simplify complex concepts and provide examples that are relevant to their educational level."
		strict_preamble=f"""You are a study assistant. You MUST answer ONLY using information from the provided context documents. Do NOT use any knowledge outside the provided context. If the answer is not in the context, say "I don't have enough information in the provided materials to answer this question." Never make up facts, names, dates, or details that are not explicitly stated in the context. Be precise and factual.{grade_context}

IMPORTANT FORMATTING REQUIREMENTS:
- Provide your answer as plain, natural text directly
- Do NOT wrap your answer in boxes, containers, or formatted structures
- Do NOT use special formatting characters or borders
- Write your answer as if you are speaking naturally to the user
- Keep your response concise and to the point
- Start directly with the answer without preamble phrases like "Based on the context" unless necessary"""
		response=self.client.chat(message=question,model='command-a-03-2025',preamble=strict_preamble,chat_history=[],documents=[{"text":context}])
		answer_text=response.text.strip()
		if answer_text.startswith('```') or answer_text.startswith('```'):
			lines=answer_text.split('\n')
			if len(lines)>2 and lines[0].startswith('```'):
				answer_text='\n'.join(lines[1:-1])
		return answer_text

	def generate_quiz(self,num_questions=5,description="",subject_id=None,difficulty="medium",existing_questions=None):
		if not self.chunks:return []
		if subject_id:
			subject_chunks=[]
			for i,chunk in enumerate(self.chunks):
				if i<len(self.meta):
					chunk_subject_id=self.meta[i].get('subject_id')
					if chunk_subject_id==int(subject_id):subject_chunks.append(chunk)
			if not subject_chunks:return []
			chunks_to_use=subject_chunks
		else:chunks_to_use=self.chunks
		quiz_questions=[]
		used_chunks=set()
		existing_questions_text=""
		if existing_questions:
			existing_questions_text="\n\nEXISTING QUESTIONS TO AVOID DUPLICATING:\n"
			for i,eq in enumerate(existing_questions):
				existing_questions_text+=f"{i+1}. {eq.get('question','')}\n"
		
		difficulty_instructions={
			"easy":"Create questions that test basic recall and understanding of fundamental concepts. Use straightforward language. The correct answer should be clearly identifiable from the content.",
			"medium":"Create questions that require applying concepts and analyzing relationships. Include some reasoning but keep it accessible. Options should be plausible but distinguishable with proper understanding.",
			"hard":"Create questions that require complex reasoning, synthesis of multiple concepts, and critical thinking. Include subtle distinctions between options. Test deep understanding and ability to apply knowledge in new contexts."
		}
		difficulty_instruction=difficulty_instructions.get(difficulty,"Create questions that test understanding of the content.")
		
		for i in range(num_questions):
			available_chunks=[j for j in range(len(chunks_to_use)) if j not in used_chunks]
			if not available_chunks:
				available_chunks=list(range(len(chunks_to_use)))
				used_chunks.clear()
			chunk_index=available_chunks[i%len(available_chunks)]
			chunk=chunks_to_use[chunk_index]
			used_chunks.add(chunk_index)
			combined_content=chunk
			if len(chunks_to_use)>1:
				additional_chunks=[]
				for j in range(min(2,len(chunks_to_use))):
					if j!=chunk_index and j not in used_chunks:additional_chunks.append(chunks_to_use[j][:500])
				if additional_chunks:combined_content=chunk+"\n\n"+"\n\n".join(additional_chunks)
            
			try:
				self.rate_limit()
				if description:
					message=f"""Create ONE multiple choice question from this educational content:

CONTENT: {combined_content[:2000]}

DIFFICULTY LEVEL: {difficulty.upper()}
DIFFICULTY GUIDELINE: {difficulty_instruction}

TEACHER REQUIREMENTS: {description}
{existing_questions_text}

IMPORTANT: You must respond in EXACTLY this format with no extra text:
Question: [Your question here]
A) [First option]
B) [Second option] 
C) [Third option]
D) [Fourth option]
Answer: A

The Answer must be exactly A, B, C, or D. Choose the correct option letter. Follow the {difficulty} difficulty guideline above. Focus on the teacher's requirements: {description}. Make sure your question is completely different from any existing questions listed above.
ALWAYS USE MARKDOWN FORMAT FOR THE QUESTION AND OPTIONS.
"""
				else:
					message=f"""Create ONE multiple choice question from this educational content:

CONTENT: {combined_content[:2000]}

DIFFICULTY LEVEL: {difficulty.upper()}
DIFFICULTY GUIDELINE: {difficulty_instruction}
{existing_questions_text}

IMPORTANT: You must respond in EXACTLY this format with no extra text:
Question: [Your question here]
A) [First option]
B) [Second option] 
C) [Third option]
D) [Fourth option]
Answer: A

The Answer must be exactly A, B, C, or D. Choose the correct option letter. Follow the {difficulty} difficulty guideline above. Make sure your question is completely different from any existing questions listed above.
ALWAYS USE MARKDOWN FORMAT FOR THE QUESTION AND OPTIONS.
"""
				response=self.client.chat(message=message,model='command-a-03-2025',preamble=f"You are an expert quiz creator. You MUST follow the exact format. The answer must be exactly A, B, C, or D. Create {difficulty}-level questions that test real understanding of the content. Follow the difficulty guidelines precisely. Avoid creating questions that are similar to existing ones.",chat_history=[])
				text=response.text.strip()
				question,options,correct="",[],""
				lines=text.split('\n')
				for line in lines:
					line=line.strip()
					if line.startswith('Question:'):question=line.replace('Question:','').strip()
					elif line.startswith('A)'):options.append(line.replace('A)','').strip())
					elif line.startswith('B)'):options.append(line.replace('B)','').strip())
					elif line.startswith('C)'):options.append(line.replace('C)','').strip())
					elif line.startswith('D)'):options.append(line.replace('D)','').strip())
					elif line.startswith('Answer:'):correct=line.replace('Answer:','').strip().upper()
				if question and len(options)==4 and correct in ['A','B','C','D']:
					is_duplicate=False
					if existing_questions:
						for eq in existing_questions:
							if self._questions_similar(question,eq.get('question','')):
								is_duplicate=True
								break
					if not is_duplicate:
						quiz_questions.append({'question':question,'options':options,'correct':correct,'type':'multiple_choice'})
				else:continue
			except:continue
		return quiz_questions

	def _questions_similar(self,question1,question2,threshold=0.8):
		if not question1 or not question2:
			return False
		words1=set(question1.lower().split())
		words2=set(question2.lower().split())
		if not words1 or not words2:
			return False
		intersection=len(words1.intersection(words2))
		union=len(words1.union(words2))
		similarity=intersection/union if union>0 else 0
		return similarity>=threshold

	def rebuild_from_db(self,materials):
		all_chunks,all_meta=[],[]
		for material in materials:
			if isinstance(material,dict):
				material_id,filename,sha,content,subject_id,upload_time=material['id'],material['filename'],material['sha'],material.get('content',''),material['subject_id'],material['upload_time']
			else:
				material_id,filename,sha,content,subject_id,upload_time=material
			if not content or not content.strip():continue
			text=content
			chunks=self.chunk_text(text,subject_id=subject_id)
			for i,chunk in enumerate(chunks):
				all_chunks.append(chunk)
				all_meta.append({'file':filename,'chunk_id':i,'file_path':f"db:{material_id}",'subject_id':subject_id})
		if all_chunks:
			self.chunks=all_chunks
			self.meta=all_meta
			tokenized=[chunk.lower().split() for chunk in all_chunks]
			self.bm25=BM25Okapi(tokenized)
			self.embeddings=self.get_embeddings(all_chunks)
			num_samples=len(self.embeddings)
			n_neighbors=min(10,max(1,num_samples))
			self.nn=NearestNeighbors(n_neighbors=n_neighbors,metric='cosine')
			self.nn.fit(self.embeddings)

	def query(self,question,top_k=5,user_grade=None):
		results=self.search(question,top_k)
		answer=self.generate_answer(question,results,user_grade=user_grade)
		return answer,results

