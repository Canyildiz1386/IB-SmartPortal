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
		word_list=text.split()
		chunk_list=[]
		step_size=chunk_size-overlap
		for i in range(0,len(word_list),step_size):
			chunk_text=' '.join(word_list[i:i+chunk_size])
			if chunk_text.strip():
				chunk_list.append(chunk_text.strip())
		return chunk_list

	def extract_pdf(self,file_path):
		try:
			import pypdf
			with open(file_path,'rb') as pdf_file:
				pdf_reader=pypdf.PdfReader(pdf_file)
				extracted_text=""
				for page_obj in pdf_reader.pages:
					extracted_text+=page_obj.extract_text()+"\n"
				return extracted_text
		except Exception:
			return ""

	def extract_txt(self,file_path):
		try:
			with open(file_path,'r',encoding='utf-8') as txt_file:
				return txt_file.read()
		except Exception:
			return ""

	def rate_limit(self):
		now=time.time()
		elapsed=now-self.last_time
		if elapsed<self.delay:
			time.sleep(self.delay-elapsed)
		self.last_time=time.time()

	def get_embeddings(self,text_list):
		self.rate_limit()
		embed_response=self.client.embed(texts=text_list,model='embed-english-v3.0',input_type='search_document')
		return np.array(embed_response.embeddings)

	def build_index(self,file_list,subject_id=None):
		all_chunks,all_meta=[],[]
		for f in file_list:
			if isinstance(f,dict):
				path=f.get('file_path','')
			else:
				path=f
			if not isinstance(path,str):
				continue
			if path.lower().endswith('.pdf'):
				txt=self.extract_pdf(path)
			elif path.lower().endswith('.txt'):
				txt=self.extract_txt(path)
			else:
				continue
			if not txt.strip():
				continue
			chunks=self.chunk_text(txt,subject_id=subject_id)
			for idx,chunk in enumerate(chunks):
				all_chunks.append(chunk)
				all_meta.append({'file':os.path.basename(path),'chunk_id':idx,'file_path':path,'subject_id':subject_id})
		if not all_chunks:
			raise ValueError("No valid text chunks found")
		self.chunks=all_chunks
		self.meta=all_meta
		tokenized_chunks=[chunk.lower().split() for chunk in all_chunks]
		self.bm25=BM25Okapi(tokenized_chunks)
		self.embeddings=self.get_embeddings(all_chunks)
		embed_count=len(self.embeddings)
		k_value=min(10,max(1,embed_count))
		self.nn=NearestNeighbors(n_neighbors=k_value,metric='cosine')
		self.nn.fit(self.embeddings)

	def search(self,query_text,top_k=5):
		if not self.chunks or self.bm25 is None or self.nn is None:
			return []
		query_words=query_text.lower().split()
		bm25_scores=self.bm25.get_scores(query_words)
		query_embedding=self.get_embeddings([query_text])
		
		chunk_count=len(self.chunks)
		if chunk_count==0:
			return []
		
		try:
			max_k=min(self.nn.n_neighbors,chunk_count)
			nn_distances,nn_indices=self.nn.kneighbors(query_embedding,n_neighbors=max_k)
		except ValueError:
			nn_distances,nn_indices=self.nn.kneighbors(query_embedding,n_neighbors=chunk_count)
		
		scores=[]
		nn_scores={}
		if len(nn_indices[0])>0:
			for i,chunk_idx in enumerate(nn_indices[0]):
				dist=nn_distances[0][i] if i<len(nn_distances[0]) else 1.0
				nn_scores[chunk_idx]=1-dist
		
		for i in range(len(self.chunks)):
			bm25_score=bm25_scores[i]
			nn_score=nn_scores.get(i,0)
			combined=self.alpha*bm25_score+(1-self.alpha)*nn_score
			scores.append((i,combined))
		scores.sort(key=lambda x:x[1],reverse=True)
		
		results=[]
		file_counts={}
		max_per_file=max(1,top_k//3)
		for idx,score in scores:
			if len(results)>=top_k:
				break
			fname=self.meta[idx]['file']
			count=file_counts.get(fname,0)
			if count<max_per_file:
				results.append({'chunk':self.chunks[idx],'score':score,'metadata':self.meta[idx]})
				file_counts[fname]=count+1
		return results

	def generate_answer(self,question_text,search_results_list,user_grade=None):
		if not search_results_list:
			return "I don't have enough information to answer that question."
		parts=[r['chunk'] for r in search_results_list]
		context="\n\n".join(parts)
		self.rate_limit()
		grade_prompt=""
		if user_grade:
			grade_prompt=f"\n\nStudent is in {user_grade} grade. Use appropriate language."
		preamble=f"""Answer using only the context provided. If info isn't there, say so. Don't make things up.{grade_prompt}

Format: plain text, no boxes or special formatting. Be concise."""
		resp=self.client.chat(message=question_text,model='command-a-03-2025',preamble=preamble,chat_history=[],documents=[{"text":context}])
		ans=resp.text.strip()
		if ans.startswith('```'):
			lines=ans.split('\n')
			if len(lines)>2 and lines[0].startswith('```'):
				ans='\n'.join(lines[1:-1])
		return ans

	def generate_quiz(self,num_questions=5,description="",subject_id=None,difficulty="medium",existing_questions=None):
		if not self.chunks:
			return []
		if subject_id:
			filtered=[]
			for i,chunk in enumerate(self.chunks):
				if i<len(self.meta):
					subj=self.meta[i].get('subject_id')
					if subj==int(subject_id):
						filtered.append(chunk)
			if not filtered:
				return []
			chunks=filtered
		else:
			chunks=self.chunks
		quiz_list=[]
		used=set()
		existing_text=""
		if existing_questions:
			existing_text="\n\nEXISTING QUESTIONS TO AVOID DUPLICATING:\n"
			for i,q in enumerate(existing_questions):
				existing_text+=f"{i+1}. {q.get('question','')}\n"
		
		difficulty_map={
			"easy":"Create questions that test basic recall and understanding of fundamental concepts. Use straightforward language. The correct answer should be clearly identifiable from the content.",
			"medium":"Create questions that require applying concepts and analyzing relationships. Include some reasoning but keep it accessible. Options should be plausible but distinguishable with proper understanding.",
			"hard":"Create questions that require complex reasoning, synthesis of multiple concepts, and critical thinking. Include subtle distinctions between options. Test deep understanding and ability to apply knowledge in new contexts."
		}
		difficulty_guide=difficulty_map.get(difficulty,"Create questions that test understanding of the content.")
		
		for q_num in range(num_questions):
			available=[j for j in range(len(chunks)) if j not in used]
			if not available:
				available=list(range(len(chunks)))
				used.clear()
			idx=available[q_num%len(available)]
			chunk=chunks[idx]
			used.add(idx)
			combined=chunk
			if len(chunks)>1:
				extra=[]
				for j in range(min(2,len(chunks))):
					if j!=idx and j not in used:
						extra.append(chunks[j][:500])
				if extra:
					combined=chunk+"\n\n"+"\n\n".join(extra)
            
			try:
				self.rate_limit()
				if description:
					prompt=f"""Create a multiple choice question:

{combined[:2000]}

Difficulty: {difficulty}
Guide: {difficulty_guide}
Requirements: {description}
{existing_text}

Format:
Question: [question]
A) [option]
B) [option]
C) [option]
D) [option]
Answer: A

Answer must be A, B, C, or D. Use markdown."""
				else:
					prompt=f"""Create a multiple choice question:

{combined[:2000]}

Difficulty: {difficulty}
Guide: {difficulty_guide}
{existing_text}

Format:
Question: [question]
A) [option]
B) [option]
C) [option]
D) [option]
Answer: A

Answer must be A, B, C, or D. Use markdown."""
				resp=self.client.chat(message=prompt,model='command-a-03-2025',preamble=f"Create {difficulty} quiz questions. Follow format. Answer is A/B/C/D.",chat_history=[])
				text=resp.text.strip()
				q,opts,correct="",[],""
				lines=text.split('\n')
				for line in lines:
					line=line.strip()
					if line.startswith('Question:'):
						q=line.replace('Question:','').strip()
					elif line.startswith('A)'):
						opts.append(line.replace('A)','').strip())
					elif line.startswith('B)'):
						opts.append(line.replace('B)','').strip())
					elif line.startswith('C)'):
						opts.append(line.replace('C)','').strip())
					elif line.startswith('D)'):
						opts.append(line.replace('D)','').strip())
					elif line.startswith('Answer:'):
						correct=line.replace('Answer:','').strip().upper()
				if q and len(opts)==4 and correct in ['A','B','C','D']:
					dup=False
					if existing_questions:
						for eq in existing_questions:
							if self._questions_similar(q,eq.get('question','')):
								dup=True
								break
					if not dup:
						quiz_list.append({'question':q,'options':opts,'correct':correct,'type':'multiple_choice'})
			except Exception:
				pass
		return quiz_list

	def _questions_similar(self,q1,q2,threshold=0.8):
		if not q1 or not q2:
			return False
		word_set1=set(q1.lower().split())
		word_set2=set(q2.lower().split())
		if not word_set1 or not word_set2:
			return False
		common_words=len(word_set1.intersection(word_set2))
		all_words=len(word_set1.union(word_set2))
		similarity_ratio=common_words/all_words if all_words>0 else 0
		return similarity_ratio>=threshold

	def rebuild_from_db(self,material_list):
		all_chunks,all_meta=[],[]
		for m in material_list:
			if isinstance(m,dict):
				mat_id=m['id']
				fname=m['filename']
				sha=m['sha']
				content=m.get('content','')
				subj=m['subject_id']
				time=m['upload_time']
			else:
				mat_id,fname,sha,content,subj,time=m
			if not content or not content.strip():
				continue
			chunks=self.chunk_text(content,subject_id=subj)
			for i,chunk in enumerate(chunks):
				all_chunks.append(chunk)
				all_meta.append({'file':fname,'chunk_id':i,'file_path':f"db:{mat_id}",'subject_id':subj})
		if all_chunks:
			self.chunks=all_chunks
			self.meta=all_meta
			tokenized_list=[chunk.lower().split() for chunk in all_chunks]
			self.bm25=BM25Okapi(tokenized_list)
			self.embeddings=self.get_embeddings(all_chunks)
			embed_count=len(self.embeddings)
			k_val=min(10,max(1,embed_count))
			self.nn=NearestNeighbors(n_neighbors=k_val,metric='cosine')
			self.nn.fit(self.embeddings)

	def query(self,question_text,top_k=5,user_grade=None):
		search_results=self.search(question_text,top_k)
		answer_text=self.generate_answer(question_text,search_results,user_grade=user_grade)
		return answer_text,search_results
