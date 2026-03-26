from flask import Flask, request
import json
import boto3
from botocore.config import Config
import os
import re
import numpy as np

from PIL import Image
import timm
from sklearn.preprocessing import normalize
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform
import torch
from sentence_transformers import SentenceTransformer

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

# just assuming http is for the endpoint
endpoint_url = "http://" + os.getenv("BUCKET_HOST") + ":"+ os.getenv("BUCKET_PORT")

# Regular S3 client for object operations (uses OBC credentials)
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    endpoint_url=endpoint_url,
    use_ssl=False,
    verify=False,
)

# S3 Vectors client for vector operations (uses CephObjectStoreUser credentials)
# These credentials come from a separate CephObjectStoreUser CRD
vector_endpoint = os.getenv("VECTOR_ENDPOINT", endpoint_url)

# Configure with signature version 4 for S3 Vectors API
s3vectors_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)

s3vectors = boto3.client(
    "s3vectors",
    aws_access_key_id=os.getenv("VECTOR_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("VECTOR_SECRET_KEY"),
    endpoint_url=vector_endpoint,
    region_name='us-east-1',  # Required by boto3, but not used by Ceph
    use_ssl=False,
    verify=False,
    config=s3vectors_config
)

# Store bucket name
bucket_name = os.getenv("BUCKET_NAME")

# Vector bucket name keeps the same format as bucket name (with hyphens)
vector_bucket_name = bucket_name + "-vectors"

object_type = os.getenv("OBJECT_TYPE")

app = Flask(__name__)

def ensure_vector_bucket_exists():
    """Create vector bucket if it doesn't exist and set up index"""
    try:
        # Check if vector bucket exists using s3vectors API
        s3vectors.get_vector_bucket(vectorBucketName=vector_bucket_name)
        app.logger.debug(f"Vector bucket {vector_bucket_name} already exists")
    except:
        # Create vector bucket using s3vectors API
        try:
            s3vectors.create_vector_bucket(vectorBucketName=vector_bucket_name)
            app.logger.debug(f"Created vector bucket: {vector_bucket_name}")
            
            # Create index on the vector bucket
            vector_dimension = int(os.getenv("VECTOR_DIMENSION"))
            
            # Create index using s3vectors API
            s3vectors.create_index(
                vectorBucketName=vector_bucket_name,
                indexName='default',
                dataType='float32',
                dimension=vector_dimension,
                distanceMetric='euclidean'  # Use 'euclidean' for L2 distance
            )
            app.logger.debug(f"Created index on vector bucket: {vector_bucket_name} with dimension {vector_dimension}")
        except Exception as e:
            app.logger.error(f"Error creating vector bucket or index: {str(e)}")
            raise

@app.route('/', methods=['POST'])
def pythonvectordbappceph():
    
    # Ensure vector bucket exists
    ensure_vector_bucket_exists()
    
    # parse object name from event
    event_data = json.loads(request.data)
    object_key = event_data['Records'][0]['s3']['object']['key']
    event_type = event_data['Records'][0]['eventName']
    app.logger.debug(object_key)
    tags = event_data['Records'][0]['s3']['object']['tags']
    app.logger.debug("tags : " + str(tags))
    
    object_url = endpoint_url + "/" + bucket_name + "/" + object_key
    
    # Handle delete events
    if event_type == "ObjectRemoved:Delete":
        app.logger.debug("starting deletion of " + object_url)
        try:
            # Delete vector using s3vectors API
            vector_key = object_key  # Use object_key as vector key
            s3vectors.delete_vectors(
                vectorBucketName=vector_bucket_name,
                indexName='default',
                keys=[vector_key]
            )
            app.logger.debug(f"Deleted vector for {object_url}")
            return "delete success"
        except Exception as e:
            app.logger.error(f"Error deleting vector: {str(e)}")
            return "delete failed", 500
    
    # Get object data using regular S3 client
    object_data = s3.get_object(Bucket=bucket_name, Key=object_key)
    
    # Generate embeddings based on object type
    match object_type:
        case "TEXT":
            object_content = object_data["Body"].read().decode("utf-8")
            # Use SentenceTransformer for text embeddings (dimension 384)
            model = SentenceTransformer('all-MiniLM-L6-v2')
            vector = model.encode(object_content)

        case "IMAGE":
            object_stream = object_data['Body']
            # Use resnet34 for image embeddings (dimension 512)
            extractor = FeatureExtractor("resnet34")
            vector = extractor(object_stream)

        case _:
            app.logger.error("Unknown object format")
            return "Unknown object format", 400

    app.logger.debug(f"Generated vector with shape: {vector.shape}")

    # Prepare metadata
    metadata = {
        'url': object_url,
        'object_key': object_key,
        'bucket': bucket_name
    }
    if len(tags) > 0:
        metadata['tags'] = json.dumps(tags)

    # Store vector using S3 Vectors put_vectors API
    vector_key = object_key  # Use object_key as vector key
    
    try:
        # Convert vector to list for API (ensure float32)
        vector_float32 = np.array(vector, dtype=np.float32).tolist()
        
        # Store vector with metadata using s3vectors API
        s3vectors.put_vectors(
            vectorBucketName=vector_bucket_name,
            indexName='default',
            vectors=[
                {
                    'key': vector_key,
                    'data': {
                        'float32': vector_float32
                    },
                    'metadata': metadata
                }
            ]
        )
        
        app.logger.debug(f"Stored vector for {object_url} in {vector_bucket_name} with key {vector_key}")
        return 'success'
    except Exception as e:
        app.logger.error(f"Error storing vector: {str(e)}")
        return "Error storing vector", 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
