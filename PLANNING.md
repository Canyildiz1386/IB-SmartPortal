# IB Computer Science Internal Assessment - Planning

## 1. Defining the Problem

### 1.1 Problem Statement
Students in educational institutions face several challenges when studying independently:
- **Limited access to personalized help**: Students often struggle to get immediate answers to their questions outside of class hours
- **Inefficient study material organization**: Educational materials (PDFs, notes) are scattered and difficult to search through
- **Lack of interactive learning tools**: Traditional study methods don't provide engaging, interactive ways to test understanding
- **Isolation in learning**: Students study alone without collaborative opportunities
- **Difficulty tracking progress**: No centralized system to monitor learning progress and identify areas needing improvement

### 1.2 Client/Stakeholder
The target users are:
- **Students**: Need access to study materials, ability to ask questions, take quizzes, and collaborate
- **Teachers**: Need to upload materials, create assignments, track student progress
- **Administrators**: Need to manage users, subjects, and monitor overall system usage

### 1.3 Current Solutions and Limitations
Existing solutions include:
- **Learning Management Systems (LMS)**: Often complex, require extensive training, lack AI-powered features
- **Study apps**: Usually single-purpose (either notes OR quizzes), don't integrate multiple features
- **Chatbots**: Generic, not trained on specific course materials
- **File sharing platforms**: Don't provide intelligent search or Q&A capabilities

**Key Limitations:**
- No intelligent search across uploaded materials
- No AI-powered question answering based on course content
- Limited collaboration features
- No personalized quiz generation from materials
- No progress tracking and analytics

### 1.4 Justification for the Solution
A comprehensive study portal that combines:
- AI-powered question answering using Retrieval Augmented Generation (RAG)
- Intelligent material indexing and search
- Automated quiz generation from study materials
- Real-time collaborative study sessions
- Mood tracking and analytics

This solution addresses multiple problems simultaneously and provides a unified platform for enhanced learning experiences.

---

## 2. Proposed Solution

### 2.1 Solution Overview
**IB Smart Portal** is a web-based educational platform that integrates multiple features:

1. **AI-Powered Study Assistant**: RAG system that answers questions based on uploaded course materials
2. **Intelligent Quiz Generator**: Automatically creates quizzes from study materials with customizable difficulty levels
3. **Collaborative Study Sessions**: Real-time chat and video sessions for group studying
4. **Digital Notes System**: Rich text notes with markdown support, voice input, and image embedding
5. **Progress Analytics**: Comprehensive dashboards for students, teachers, and administrators
6. **Face Recognition Authentication**: Biometric login option for enhanced security
7. **Mood Tracking**: Emotion analysis to understand student engagement

### 2.2 Core Features

#### 2.2.1 User Management System
- **Three user roles**: Admin, Teacher, Student
- **Authentication methods**: Password-based and face recognition
- **Subject assignment**: Users can be assigned to specific subjects
- **Grade tracking**: Students have grade levels for personalized content

#### 2.2.2 RAG (Retrieval Augmented Generation) System
- **Hybrid search**: Combines BM25 keyword search with semantic embedding search
- **Document processing**: Extracts text from PDF and TXT files
- **Intelligent chunking**: Splits documents into optimal chunks with overlap
- **Context-aware answers**: Generates answers using Cohere API based on relevant document chunks
- **Grade-appropriate responses**: Adapts language complexity based on student grade level

#### 2.2.3 Quiz Management
- **AI-generated quizzes**: Creates multiple-choice questions from study materials
- **Difficulty levels**: Easy, Medium, Hard
- **Quiz assignment**: Teachers assign quizzes to specific students
- **Results tracking**: Scores, completion times, and detailed analytics
- **Question explanations**: AI-powered explanations for quiz questions

#### 2.2.4 Study Sessions
- **Session creation**: Teachers/students create study sessions with subject association
- **Real-time chat**: WebSocket-based messaging
- **AI integration**: Students can ask AI questions within sessions using `/ai` command
- **Video conferencing**: WebRTC support for video calls
- **Participant management**: Track who joins/leaves sessions

#### 2.2.5 Notes System
- **Rich text editor**: Markdown support for formatting
- **Voice input**: Speech-to-text for note-taking
- **Image embedding**: Insert images directly into notes
- **Subject organization**: Notes linked to subjects
- **Search functionality**: Search notes by title and content

#### 2.2.6 Analytics and Progress Tracking
- **Student dashboard**: Personal progress, quiz scores, activity history
- **Teacher dashboard**: Student performance, quiz statistics, subject analytics
- **Admin dashboard**: System-wide statistics, user distribution, performance metrics
- **Time series data**: Track progress over time
- **Score distribution**: Visualize performance patterns

#### 2.2.7 Mood Tracking
- **Face analysis**: Analyzes emotions during login
- **Mood calendar**: Visual calendar showing daily moods
- **Trend analysis**: Track mood patterns over time
- **Teacher/Admin views**: Monitor student emotional well-being

### 2.3 Technical Architecture

#### 2.3.1 Technology Stack
- **Backend**: Python 3.x with Flask framework
- **Database**: SQLite for data persistence
- **Real-time**: Flask-SocketIO for WebSocket communication
- **AI/ML**: 
  - Cohere API for embeddings and LLM
  - scikit-learn for NearestNeighbors search
  - rank-bm25 for keyword search
  - DeepFace for face recognition and mood analysis
- **Frontend**: HTML5, CSS3, JavaScript (vanilla)
- **Deployment**: Flask development server (can be deployed to production)

#### 2.3.2 System Architecture
```
┌─────────────────┐
│   Web Browser   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Flask App     │ ◄─── Routes & Controllers
│   (app.py)      │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌─────────┐ ┌──────────────┐
│Database │ │  Services    │
│(SQLite) │ │  - RAG       │
│         │ │  - Session   │
└─────────┘ └──────┬───────┘
                   │
            ┌──────┴──────┐
            │             │
            ▼             ▼
      ┌─────────┐   ┌──────────┐
      │ Cohere  │   │ DeepFace │
      │   API   │   │  Library │
      └─────────┘   └──────────┘
```

#### 2.3.3 Key Algorithms

**Hybrid Search Algorithm:**
1. User query → Tokenize for BM25
2. Generate query embedding via Cohere
3. Score chunks using BM25 (keyword matching)
4. Score chunks using cosine similarity (semantic matching)
5. Combine scores: `final_score = 0.7 × BM25_score + 0.3 × embedding_score`
6. Return top-k results with diversity (max 1/3 from each file)

**RAG Answer Generation:**
1. Retrieve relevant chunks using hybrid search
2. Combine chunks into context
3. Send context + question to Cohere API
4. Generate answer with grade-appropriate language
5. Return answer with source citations

**Quiz Generation:**
1. Filter chunks by subject (if specified)
2. Select diverse chunks (avoid duplicates)
3. Combine chunk with related context
4. Generate prompt with difficulty level
5. Parse AI response to extract question, options, answer
6. Validate format and avoid duplicates

---

## 3. Success Criteria

### 3.1 Functional Requirements

1. **User Authentication**
   - ✅ Users can log in with username/password
   - ✅ Users can log in with face recognition
   - ✅ Session management works correctly
   - ✅ Role-based access control functions properly

2. **Material Management**
   - ✅ Teachers can upload PDF and TXT files
   - ✅ Files are processed and indexed automatically
   - ✅ Materials are associated with subjects
   - ✅ Index can be rebuilt if needed

3. **RAG System**
   - ✅ System answers questions based on uploaded materials
   - ✅ Answers include source citations
   - ✅ Response time < 5 seconds for typical queries
   - ✅ Handles queries when no materials are indexed

4. **Quiz System**
   - ✅ Teachers can generate quizzes from materials
   - ✅ Quizzes have configurable difficulty levels
   - ✅ Students can take assigned quizzes
   - ✅ Results are saved and displayed
   - ✅ Question explanations are provided

5. **Study Sessions**
   - ✅ Users can create and join study sessions
   - ✅ Real-time chat works correctly
   - ✅ AI questions work within sessions
   - ✅ Participant list updates in real-time

6. **Notes System**
   - ✅ Users can create, edit, delete notes
   - ✅ Markdown formatting works
   - ✅ Voice input functions
   - ✅ Images can be embedded
   - ✅ Notes are searchable

7. **Analytics**
   - ✅ Dashboards display correct statistics
   - ✅ Progress tracking works
   - ✅ Charts and graphs render correctly

### 3.2 Non-Functional Requirements

1. **Performance**
   - Page load time < 2 seconds
   - Query response time < 5 seconds
   - Support at least 50 concurrent users

2. **Reliability**
   - System handles errors gracefully
   - Database operations are atomic
   - No data loss during normal operations

3. **Usability**
   - Intuitive user interface
   - Clear navigation
   - Responsive design
   - Helpful error messages

4. **Security**
   - Passwords are hashed (SHA-256)
   - Session management is secure
   - File uploads are validated
   - SQL injection prevention (parameterized queries)

---

## 4. Plan of Action

### 4.1 Development Phases

#### Phase 1: Foundation (Weeks 1-2)
**Objectives**: Set up basic infrastructure and user management

**Tasks**:
- [x] Set up Flask project structure
- [x] Design database schema
- [x] Implement user authentication (password-based)
- [x] Create basic HTML templates
- [x] Implement role-based access control
- [x] Create admin, teacher, student dashboards

**Deliverables**:
- Working login system
- User management (CRUD operations)
- Basic navigation

#### Phase 2: Material Management (Week 3)
**Objectives**: Enable file upload and processing

**Tasks**:
- [x] Implement file upload functionality
- [x] PDF text extraction
- [x] TXT file reading
- [x] Database storage of materials
- [x] Subject management system
- [x] Material listing and display

**Deliverables**:
- File upload working
- Materials stored in database
- Subject association

#### Phase 3: RAG System Implementation (Weeks 4-5)
**Objectives**: Build intelligent question-answering system

**Tasks**:
- [x] Implement text chunking algorithm
- [x] Integrate Cohere API for embeddings
- [x] Build BM25 index
- [x] Implement NearestNeighbors for semantic search
- [x] Create hybrid search algorithm
- [x] Build answer generation function
- [x] Create chat interface
- [x] Add source citation

**Deliverables**:
- Working RAG system
- Chat interface
- Question-answering functionality

#### Phase 4: Quiz System (Week 6)
**Objectives**: Automated quiz generation and management

**Tasks**:
- [x] Implement quiz generation algorithm
- [x] Create quiz database schema
- [x] Build quiz creation interface
- [x] Implement quiz assignment system
- [x] Create quiz taking interface
- [x] Implement scoring system
- [x] Add question explanation feature
- [x] Create results display

**Deliverables**:
- Quiz generation working
- Quiz taking interface
- Results tracking

#### Phase 5: Study Sessions (Week 7)
**Objectives**: Real-time collaboration features

**Tasks**:
- [x] Set up Flask-SocketIO
- [x] Implement session creation
- [x] Build real-time chat
- [x] Integrate AI questions in sessions
- [x] Add participant management
- [x] Implement WebRTC for video (basic structure)

**Deliverables**:
- Working study sessions
- Real-time chat
- AI integration in sessions

#### Phase 6: Additional Features (Week 8)
**Objectives**: Notes system and mood tracking

**Tasks**:
- [x] Create notes database schema
- [x] Build notes CRUD operations
- [x] Implement markdown rendering
- [x] Add voice input functionality
- [x] Implement image embedding
- [x] Integrate DeepFace for face recognition
- [x] Build mood tracking system
- [x] Create mood calendar view

**Deliverables**:
- Notes system working
- Face recognition login
- Mood tracking functional

#### Phase 7: Analytics and Dashboard (Week 9)
**Objectives**: Comprehensive progress tracking

**Tasks**:
- [x] Design analytics database queries
- [x] Build student dashboard
- [x] Build teacher dashboard
- [x] Build admin dashboard
- [x] Implement charts and graphs
- [x] Add time series tracking
- [x] Create export functionality

**Deliverables**:
- Analytics dashboards
- Progress tracking
- Visualizations

#### Phase 8: Testing and Refinement (Week 10)
**Objectives**: Ensure quality and fix issues

**Tasks**:
- [ ] Comprehensive testing of all features
- [ ] Bug fixes
- [ ] Performance optimization
- [ ] UI/UX improvements
- [ ] Error handling enhancement
- [ ] Documentation

**Deliverables**:
- Fully tested system
- Bug fixes
- Documentation

### 4.2 Timeline Summary

| Week | Phase | Key Deliverables |
|------|-------|-----------------|
| 1-2  | Foundation | User auth, basic structure |
| 3    | Material Management | File upload, processing |
| 4-5  | RAG System | Q&A functionality |
| 6    | Quiz System | Quiz generation & taking |
| 7    | Study Sessions | Real-time collaboration |
| 8    | Additional Features | Notes, mood tracking |
| 9    | Analytics | Dashboards, progress |
| 10   | Testing | Final testing, fixes |

### 4.3 Resource Requirements

**Hardware**:
- Development machine (laptop/desktop)
- Webcam for face recognition testing
- Internet connection for API access

**Software**:
- Python 3.8+
- Text editor/IDE (VS Code, PyCharm, etc.)
- Web browser for testing
- Git for version control

**APIs and Services**:
- Cohere API key (for embeddings and LLM)
- DeepFace library (local, no API key needed)

**Knowledge/Skills**:
- Python programming
- Flask web framework
- SQL database design
- HTML/CSS/JavaScript
- REST API concepts
- WebSocket basics
- Understanding of RAG concepts

---

## 5. Risk Assessment

### 5.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| API rate limits | High | Medium | Implement rate limiting, caching |
| Large file processing | Medium | Medium | Add file size limits, chunking |
| Database performance | Medium | Low | Optimize queries, indexing |
| WebSocket connection issues | Low | Low | Error handling, reconnection logic |

### 5.2 Project Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Time constraints | High | Medium | Prioritize core features |
| API costs | Medium | Low | Monitor usage, optimize calls |
| Complexity overload | High | Medium | Focus on core functionality first |
| Testing insufficient | Medium | Medium | Allocate dedicated testing time |

---

## 6. Evaluation Plan

### 6.1 Testing Strategy

1. **Unit Testing**: Test individual functions
2. **Integration Testing**: Test feature interactions
3. **User Testing**: Get feedback from potential users
4. **Performance Testing**: Measure response times
5. **Security Testing**: Check authentication, authorization

### 6.2 Success Metrics

- All functional requirements met ✅
- Response times within acceptable limits
- No critical bugs
- Positive user feedback
- Code is maintainable and documented

---

## Notes for Development

- Use consistent code style
- Comment complex algorithms
- Handle errors gracefully
- Log important operations
- Keep database operations atomic
- Validate all user inputs
- Secure sensitive data

