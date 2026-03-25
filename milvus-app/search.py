import milvus_model
import sys, getopt
from pymilvus import MilvusClient, DataType, Collection

CLUSTER_ENDPOINT=str(sys.argv[0])
client = MilvusClient(uri=CLUSTER_ENDPOINT)
collection_name=str(sys.argv[1])
client.load_collection(collection_name)

embedding_fn = milvus_model.dense.SentenceTransformerEmbeddingFunction(model_name='all-MiniLM-L6-v2',device='cpu')
query_vectors = embedding_fn.encode_queries([str(sys.argv[2])])

res = client.search(
    collection_name=collection_name,  # target collection
    data=query_vectors,  # query vectors
    limit=2,  # number of returned entities
    output_fields=["url"],  # specifies fields to be returned
    consistency_level="Strong" ## NOTE: without defining that, the search might return empty result.
)
print(res)
