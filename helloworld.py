
from flask import Flask, request
import uuid
import json
import milvus_model
from pymilvus import MilvusClient, DataType, Collection

import boto3
import os
import re

from dotenv import load_dotenv

from PIL import Image
# from io import BytesIO
import timm
from sklearn.preprocessing import normalize
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform
import torch

from transformers import AutoFeatureExtractor, AutoModelForImageClassification

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


i = 0

app = Flask(__name__)

@app.route('/', methods=['POST'])
def pythonvectordbappceph():

    collection_name = re.sub('-', '_', bucket_name)
    app.logger.debug(request.data)
    event_data = json.loads(request.data)
    object_key = event_data['Records'][0]['s3']['object']['key']
    app.logger.debug(object_key)
    if not client.has_collection(collection_name=collection_name):
        client.create_collection(
            collection_name=collection_name,
            dimension=os.getenv("VECTOR_DIMENSION"),
            enable_dynamic_field=True,
            metric_type="COSINE",
            )

    # define different functions below code snippet
    object_data = s3.get_object(Bucket=bucket_name, Key=object_key)
    match object_type:
        case "TEXT":
            object_content = object_data["Body"].read().decode("utf-8")
            objectlist = []
            objectlist.append(object_content)
            # embedding_fn = milvus_model.DefaultEmbeddingFunction() #dimension 768
            embedding_fn = milvus_model.dense.SentenceTransformerEmbeddingFunction(model_name='all-MiniLM-L6-v2',device='cpu') # dimension 384
            vectors = embedding_fn.encode_documents(objectlist)

        case "IMAGE1":
            object_stream = object_data['Body']
            # dimesnsion 512
            extractor = FeatureExtractor("resnet34")
            # issue : RPC error: [insert_rows], <DataNotMatchException: (code=1, message=The Input data type is inconsistent with defined schema, {vector} field should be a float_vector, but got a {<class 'numpy.float32'>} instead.)>
            vectors = extractor(object_stream)

        case "IMAGE2":
            extractor = AutoFeatureExtractor.from_pretrained("microsoft/resnet-50")
            model = AutoModelForImageClassification.from_pretrained("microsoft/resnet-50")
            object_stream = object_data['Body']
            object_content = Image.open(object_stream)
            inputs = extractor(images=object_content, return_tensors="pt")
            # dimension 2048
            outputs = model(**inputs)
            # issue : RPC error: [insert_rows], <DataNotMatchException: (code=1, message=The Input data type is inconsistent with defined schema,{vector} field should be a float_vector, but got a {<class 'float'> python
            vectors = outputs[0][0].squeeze().tolist()

        case _:
            app.logger.error("Unknown object format")

    client.load_collection(collection_name=collection_name)

    app.logger.debug(vectors)
    global i
    i = i + 1
    object_url = endpoint_url+ "/" + bucket_name + "/"+ object_key
    data = [ {"id": i, "vector": vectors[0], "url": object_url}
            ]

    res = client.insert(collection_name=collection_name, data=data)
    app.logger.debug(res)
    return ''

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
