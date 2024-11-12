import sys, getopt
from pymilvus import MilvusClient, DataType, Collection

CLUSTER_ENDPOINT=str(sys.argv[0])
client = MilvusClient(uri=CLUSTER_ENDPOINT)

collection_name=str(sys.argv[1])
index_name="embedded_vector"
client.load_collection(collection_name)


res = client.describe_collection(
        collection_name=collection_name
    )
print(res)
res = client.list_indexes(
        collection_name=collection_name
    )

print(res)
res = client.describe_index(
        collection_name=collection_name,
        index_name=index_name
    )
print(res)

results = client.query(
        collection_name=collection_name,
        filter="",  # Empty string means no filter
        limit=10,
        output_fields=["*"]  # Get all fields
    )
print(" == query == ")
print(results)
print(" == End == ")


