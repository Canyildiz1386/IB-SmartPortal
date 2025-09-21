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
		self.nn=NearestNeighbors(n_neighbors=10,metric='cosine')
		self.nn.fit(self.embeddings)

	def search(self,query,top_k=5):
		if not self.chunks or self.bm25 is None or self.nn is None:return []
		query_tokens=query.lower().split()
		bm25_scores=self.bm25.get_scores(query_tokens)
		query_embedding=self.get_embeddings([query])
		nn_distances,nn_indices=self.nn.kneighbors(query_embedding)
		combined_scores=[]
		for i in range(len(self.chunks)):
			bm25_score=bm25_scores[i]
			nn_score=1-nn_distances[0][i] if i<len(nn_distances[0]) else 0
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

	def generate_answer(self,question,search_results):
		if not search_results:return "I don't have enough information to answer that question."
		context="\n\n".join([result['chunk'] for result in search_results])
		self.rate_limit()
		response=self.client.chat(message=question,model='command-a-03-2025',preamble="You are a helpful study assistant. Answer questions based on the provided context. Be accurate and helpful.",chat_history=[],documents=[{"text":context}])
		return response.text

	def generate_quiz(self,num_questions=5,description="",subject_id=None):
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

TEACHER REQUIREMENTS: {description}

IMPORTANT: You must respond in EXACTLY this format with no extra text:
Question: [Your question here]
A) [First option]
B) [Second option] 
C) [Third option]
D) [Fourth option]
Answer: A

The Answer must be exactly A, B, C, or D. Choose the correct option letter. Focus on the teacher's requirements: {description}."""
				else:
					message=f"""Create ONE multiple choice question from this educational content:

CONTENT: {combined_content[:2000]}

IMPORTANT: You must respond in EXACTLY this format with no extra text:
Question: [Your question here]
A) [First option]
B) [Second option] 
C) [Third option]
D) [Fourth option]
Answer: A

The Answer must be exactly A, B, C, or D. Choose the correct option letter."""
				response=self.client.chat(message=message,model='command-a-03-2025',preamble="You are an expert quiz creator. You MUST follow the exact format. The answer must be exactly A, B, C, or D. Create questions that test real understanding of the content.",chat_history=[])
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
					quiz_questions.append({'question':question,'options':options,'correct':correct})
				else:continue
			except:continue
		return quiz_questions

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
			self.nn=NearestNeighbors(n_neighbors=10,metric='cosine')
			self.nn.fit(self.embeddings)

	def query(self,question,top_k=5):
		results=self.search(question,top_k)
		answer=self.generate_answer(question,results)
		return answer,results