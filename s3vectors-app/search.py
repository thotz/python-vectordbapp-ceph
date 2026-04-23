import sys
import boto3
from botocore.config import Config
from sentence_transformers import SentenceTransformer
import json

# Usage: python search.py <endpoint_url> <vector_access_key> <vector_secret_key> <bucket_name> <search_text>
# Note: Use vector user credentials (from CephObjectStoreUser), not OBC credentials
endpoint_url = str(sys.argv[1])
vector_access_key = str(sys.argv[2])
vector_secret_key = str(sys.argv[3])
bucket_name = str(sys.argv[4])
search_text = str(sys.argv[5])

# Vector bucket name keeps the same format as bucket name (with hyphens)
vector_bucket_name = bucket_name + "-vectors"

# Configure with signature version 4 for S3 Vectors API
s3vectors_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)

# Initialize S3 Vectors client with vector user credentials
s3vectors = boto3.client(
    "s3vectors",
    aws_access_key_id=vector_access_key,
    aws_secret_access_key=vector_secret_key,
    endpoint_url=endpoint_url,
    region_name='us-east-1',  # Required by boto3, but not used by Ceph
    use_ssl=False,
    verify=False,
    config=s3vectors_config
)

# Generate query vector
model = SentenceTransformer('all-MiniLM-L6-v2')
query_vector = model.encode(search_text)

# Convert query vector to list for API
query_vector_list = query_vector.tolist()

try:
    # Convert query vector to float32
    import numpy as np
    query_vector_float32 = np.array(query_vector, dtype=np.float32).tolist()
    
    # Search vectors using s3vectors API
    response = s3vectors.query_vectors(
        vectorBucketName=vector_bucket_name,
        indexName='default',
        queryVector={
            'float32': query_vector_float32
        },
        topK=2,  # Get top 2 results
        returnMetadata=True,
        returnDistance=True
    )
    
    # Format results
    results = []
    if 'vectors' in response:
        for vector_result in response['vectors']:
            result = {
                'vector_key': vector_result.get('key', 'N/A'),
                'distance': vector_result.get('distance', 'N/A'),
                'metadata': vector_result.get('metadata', {})
            }
            results.append(result)
    
    print("Search Results:")
    print(json.dumps(results, indent=2))
    
except Exception as e:
    print(f"Error searching vectors: {str(e)}")
    sys.exit(1)
