import uuid
import json
import milvus_model
import sys, getopt
from pymilvus import MilvusClient, DataType, Collection

CLUSTER_ENDPOINT="http://localhost:27017"
client = MilvusClient(uri=CLUSTER_ENDPOINT)

client.load_collection("ceph_bkt_3cab575e_5080_4e5c_9675_86b8f53af5c7")

embedding_fn = milvus_model.dense.SentenceTransformerEmbeddingFunction(model_name='all-MiniLM-L6-v2',device='cpu')
query_vectors = embedding_fn.encode_queries([str(sys.argv)])

res = client.search(
    collection_name="ceph_bkt_3cab575e_5080_4e5c_9675_86b8f53af5c7",  # target collection
    data=query_vectors,  # query vectors
    limit=2,  # number of returned entities
    output_fields=["url"],  # specifies fields to be returned
    consistency_level="Strong" ## NOTE: without defining that, the search might return empty result.
)
print(res)