import os
import textwrap
from pathlib import Path
import asyncio  # Import asyncio
from decouple import config
from IPython.display import Markdown
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Qdrant
from langchain_community.document_loaders import UnstructuredMarkdownLoader
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from llama_parse import LlamaParse

os.environ["GROQ_API_KEY"] = config(
    'GROQ_API_KEY'
)


def print_response(response):
    response_txt = response["result"]
    for chunk in response_txt.split("\n"):
        if not chunk:
            print()
            continue
        print("\n".join(textwrap.wrap(chunk, 100, break_long_words=False)))


instruction = """
The provided documents contain comprehensive medical information about various drugs, their administration, potential allergic reactions, perceptions on how to take the drugs, and other related medical data.
Your task is to:
1. Extract detailed information about each drug, including its usage, dosage, side effects, contraindications, and interactions.
2. Summarize information about potential allergic reactions associated with different drugs.
3. Provide guidelines on the proper administration of each drug.
4. Extract any additional medical insights, including perceptions and recommendations on how to take the drugs.
5. Ensure all information is accurate, up-to-date, and well-organized.

Load and process all the provided PDFs to extract this information.
"""

pdf_files = [
   'content/NLEM.pdf',
   'content/data.pdf',
   'content/data1.pdf',
   'content/data2.pdf',
   'content/data3.pdf',
   'content/data4.pdf',
   'content/data5.pdf',
   'content/data6.pdf',
   'content/data7.pdf',
   'content/data8.pdf',
   'content/data9.pdf',
]

parser = LlamaParse(
    api_key=config('LLAMA_PARSE'),
    result_type="markdown",
    parsing_instruction=instruction,
    max_timeout=5000,
)


async def load_all_pdfs(pdf_files):
    llama_parse_documents = []
    for pdf_file in pdf_files:
        parsed_data = await parser.aload_data(pdf_file)
        llama_parse_documents.append(parsed_data)
    return llama_parse_documents


async def main():
    llama_parse_documents = await load_all_pdfs(pdf_files)

    parsed_doc = llama_parse_documents[0]
    print(parsed_doc)

    document_path = Path("data/parsed_document.md")
    with document_path.open("a") as f:
        f.write(parsed_doc[0].text)

    loader = UnstructuredMarkdownLoader(document_path)
    loaded_documents = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2048, chunk_overlap=128)
    docs = text_splitter.split_documents(loaded_documents)
    print(docs[0].page_content)

    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-base-en-v1.5")

    qdrant = Qdrant.from_documents(
        docs,
        embeddings,
        path="./db",
        collection_name="document_embeddings",
    )

    query = "What is Lithium Carbonate used for ?"
    similar_docs = qdrant.similarity_search_with_score(query)

    for doc, score in similar_docs:
        print(f"text: {doc.page_content[:256]}\n")
        print(f"score: {score}")
        print("-" * 80)
        print()

    retriever = qdrant.as_retriever(search_kwargs={"k": 5})
    retrieved_docs = retriever.invoke(query)

    for doc in retrieved_docs:
        print(f"id: {doc.metadata['_id']}\n")
        print(f"text: {doc.page_content[:256]}\n")
        print("-" * 80)
        print()

    compressor = FlashrankRerank(model="ms-marco-MiniLM-L-12-v2")
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor, base_retriever=retriever
    )

    reranked_docs = compression_retriever.invoke(query)

    for doc in reranked_docs:
        print(f"id: {doc.metadata['_id']}\n")
        print(f"text: {doc.page_content[:256]}\n")
        print(f"score: {doc.metadata['relevance_score']}")
        print("-" * 80)
        print()

    llm = ChatGroq(temperature=0, model_name="llama3-70b-8192")

    prompt_template = """
    Use the following pieces of information to answer the user's question.
    If you don't know the answer, just say that you don't know, don't try to make up an answer.

    Context: {context}
    Question: {question}

    Answer the question and provide additional helpful information,
    based on the pieces of information, if applicable. Be succinct.

    Responses should be properly formatted to be easily read.
    """

    prompt = PromptTemplate(
        template=prompt_template, input_variables=["context", "question"]
    )

    qa = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=compression_retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt, "verbose": True},
    )

    response = qa.invoke("What is Lithium Carbonate used for ?")
    print_response(response)

    response = qa.invoke("What is Lithium Carbonate used for and what dosages can I take for a child in their teens")
    print_response(response)


if __name__ == "__main__":
    asyncio.run(main())
