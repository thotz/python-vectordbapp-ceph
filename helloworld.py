
from flask import Flask, request
import uuid
import json
import milvus_model
from pymilvus import MilvusClient, DataType, Collection

import boto3
import os

from dotenv import load_dotenv

client = MilvusClient(
    uri=os.getenv("MILVUS_ENDPOINT")
)

endpoint_url = "http://" + os.getenv("BUCKET_HOST") + ":"+ os.getenv("BUCKET_PORT")

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    endpoint_url=endpoint_url,
    use_ssl=False,
    verify=False,
)
# Store bucket name
bucket_name = os.getenv("BUCKET_NAME")

collection_name = os.getenv("COLLECTION_NAME")

i = 0

app = Flask(__name__)

@app.route('/', methods=['POST'])
def hello_world():
    app.logger.debug(request.data)
    event_data = json.loads(request.data)
    object_key = event_data['Records'][0]['s3']['object']['key']
    app.logger.debug(object_key)
    if not client.has_collection(collection_name=collection_name):
        client.create_collection(
            collection_name=collection_name,
            dimension=768,  # The vectors we will use in this demo has 768 dimensions
            )
    object_data = s3.get_object(Bucket=bucket_name, Key=object_key)

    object_content = object_data["Body"].read().decode("utf-8")
    app.logger.debug(object_content)
    # Load the collection into memory
    client.load_collection(collection_name=collection_name)
    objectlist = []

    objectlist.append(object_content)

    embedding_fn = milvus_model.DefaultEmbeddingFunction()

    vectors = embedding_fn.encode_documents(objectlist)

    app.logger.debug(vectors)
    global i
    i = i + 1
    object_url = endpoint_url+ "/" + bucket_name + "/"+ object_key
    data = [ {"id": i, "vector": vectors[0], "url": object_url} ]

    res = client.insert(collection_name=collection_name, data=data)
    app.logger.debug(res)
    return ''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

