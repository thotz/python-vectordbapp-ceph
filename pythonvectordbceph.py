
from flask import Flask, request
#import uuid
import json
import milvus_model
from pymilvus import MilvusClient, DataType, FieldSchema, CollectionSchema

import boto3
import os
import re

from PIL import Image
import timm
from sklearn.preprocessing import normalize
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform
import torch

# this is need for only when second image embedding function is used
# from transformers import AutoFeatureExtractor, AutoModelForImageClassification

class FeatureExtractor:
    def __init__(self, modelname):
        # Load the pre-trained model
        self.model = timm.create_model(
            modelname, pretrained=True, num_classes=0, global_pool="avg"
        )
        self.model.eval()

        # Get the input size required by the model
        self.input_size = self.model.default_cfg["input_size"]

        config = resolve_data_config({}, model=modelname)
        # Get the preprocessing function provided by TIMM for the model
        self.preprocess = create_transform(**config)

    def __call__(self, imagepath):
        # Preprocess the input image
        input_image = Image.open(imagepath).convert("RGB")  # Convert to RGB if needed
        input_image = self.preprocess(input_image)

        # Convert the image to a PyTorch tensor and add a batch dimension
        input_tensor = input_image.unsqueeze(0)

        # Perform inference
        with torch.no_grad():
            output = self.model(input_tensor)

        # Extract the feature vector
        feature_vector = output.squeeze().numpy()

        return normalize(feature_vector.reshape(1, -1), norm="l2").flatten()

client = MilvusClient(
    uri=os.getenv("MILVUS_ENDPOINT")
)

# just assuming http is for the endpoint
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

object_type = os.getenv("OBJECT_TYPE")


app = Flask(__name__)

@app.route('/', methods=['POST'])
def pythonvectordbappceph():

    # collection name only supports '_', so change '-' in bucketname to '_'
    collection_name = re.sub('-', '_', bucket_name)
    app.logger.debug("collection name from the bucket: " + collection_name)
    # parse object name from event
    # TODO: parse other metadatas and add to the collection
    event_data = json.loads(request.data)
    object_key = event_data['Records'][0]['s3']['object']['key']
    app.logger.debug(object_key)

    # Create collection which includes the id, object url, and embedded vector
    if not client.has_collection(collection_name=collection_name):
        fields = [
                FieldSchema(name='id', dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name='url', dtype=DataType.VARCHAR, max_length=2048),  # VARCHARS need a maximum length, so for this example they are set to 200 characters
                FieldSchema(name='embedded_vector', dtype=DataType.FLOAT_VECTOR, dim=os.getenv("VECTOR_DIMENSION"))
                ]
        schema = CollectionSchema(fields=fields, enable_dynamic_field=True)
        client.create_collection(collection_name=collection_name, schema=schema)
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="embedded_vector", metric_type="L2", index_type="IVF_FLAT", params={"nlist": 16384})
        client.create_index(collection_name=collection_name, index_params=index_params)
        app.logger.debug("collection " + collection_name + "created")

    # define different functions below code snippet
    object_data = s3.get_object(Bucket=bucket_name, Key=object_key)
    match object_type:
        case "TEXT":
            object_content = object_data["Body"].read().decode("utf-8")
            objectlist = []
            objectlist.append(object_content)
            # default embedding function provided by milvus, it has some size limtation for the object
            # embedding_fn = milvus_model.DefaultEmbeddingFunction() #dimension 768
            embedding_fn = milvus_model.dense.SentenceTransformerEmbeddingFunction(model_name='all-MiniLM-L6-v2',device='cpu') # dimension 384
            vectors = embedding_fn.encode_documents(objectlist)
            vector = vectors[0]

        case "IMAGE":
            object_stream = object_data['Body']
            # dimesnsion 512
            extractor = FeatureExtractor("resnet34")
            vector = extractor(object_stream)

#        Another embedding function for  image object
#        case "IMAGE2":
#            extractor = AutoFeatureExtractor.from_pretrained("microsoft/resnet-50")
#            model = AutoModelForImageClassification.from_pretrained("microsoft/resnet-50")
#            object_stream = object_data['Body']
#            object_content = Image.open(object_stream)
#            inputs = extractor(images=object_content, return_tensors="pt")
#            # dimension 2048
#            outputs = model(**inputs)
#            # issue : RPC error: [insert_rows], <DataNotMatchException: (code=1, message=The Input data type is inconsistent with defined schema,{vector} field should be a float_vector, but got a {<class 'float'> python
#            vector = outputs.squeeze().tolist()

        case _:
            app.logger.error("Unknown object format")

    client.load_collection(collection_name=collection_name)

    app.logger.debug(vector)
    object_url = endpoint_url+ "/" + bucket_name + "/"+ object_key
    data = [ {"embedded_vector": vector, "url": object_url} ]

    res = client.insert(collection_name=collection_name, data=data)
    app.logger.debug(res)
    return ''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
