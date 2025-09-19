import os
import pathlib
import gradio as gr
from rag import RagIndex

INDEX_PATH = "rag_index.pkl"
state = {"index": None}

def build_index(files):
    if not files:
        return "No files provided.", None
    idx = RagIndex()
    for f in files:
        file_path = f.name
        with open(file_path, "rb") as fh:
            bytes_ = fh.read()
        idx.add_document(bytes_, pathlib.Path(file_path).name)
    idx.build()
    idx.save(INDEX_PATH)
    state["index"] = idx
    meta = idx.metadata
    return f"✅ Index built.\n- Files: {len(meta.get('files', []))}\n- Chunks: {len(idx.chunks)}", meta

def load_index():
    try:
        idx = RagIndex.load(INDEX_PATH)
        state["index"] = idx
        meta = idx.metadata
        return f"📂 Loaded existing index.\n- Files: {len(meta.get('files', []))}\n- Chunks: {len(idx.chunks)}", meta
    except Exception as e:
        return f"⚠️ No saved index found: {e}", None

def answer_question(question, top_k):
    idx = state.get("index")
    if idx is None:
        try:
            idx = RagIndex.load(INDEX_PATH)
            state["index"] = idx
        except Exception as e:
            return f"⚠️ Index not available. Build or load it first. ({e})", None
    try:
        out = idx.answer(question, k=top_k)
        answer = f"### 💡 Answer\n{out['answer']}"
        ctx_table = [[c["source"], f"{c['score']:.3f}", c["text"][:180]+"..."] for c in out["contexts"]]
        return answer, ctx_table
    except Exception as e:
        return f"❌ Error: {e}", None

with gr.Blocks(
    title="RAG — Smart QA (Cohere)", 
    theme=gr.themes.Soft(primary_hue="blue", secondary_hue="violet").set(body_background_fill_dark="#0f0f0f")
) as demo:
    gr.Markdown(
        """
        # 🔎 RAG — Smart QA (Cohere)
        Build a **local index** and ask grounded questions.

        ⚡ **Note:** Requires internet for Cohere API and a valid `COHERE_API_KEY`.
        """,
        elem_id="title"
    )

    with gr.Tab("📑 Build / Load Index"):
        files = gr.File(file_count="multiple", file_types=[".pdf", ".txt", ".md"], label="📂 Upload Files")
        with gr.Row():
            build_btn = gr.Button("⚙️ Build Index", variant="primary")
            load_btn = gr.Button("📥 Load Saved Index")
        status = gr.Markdown()
        meta = gr.JSON()
        build_btn.click(build_index, inputs=[files], outputs=[status, meta])
        load_btn.click(load_index, inputs=[], outputs=[status, meta])

    with gr.Tab("💬 Ask"):
        q = gr.Textbox(label="Your question", placeholder="Type your question here...")
        topk = gr.Slider(1, 10, value=5, step=1, label="Top-K retrieved chunks")
        ask_btn = gr.Button("🚀 Ask", variant="primary")
        ans = gr.Markdown()
        ctx = gr.Dataframe(headers=["Source", "Score", "Snippet"], wrap=True, interactive=False)
        ask_btn.click(answer_question, inputs=[q, topk], outputs=[ans, ctx])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False, inbrowser=True)
