import sys
from pymilvus import MilvusClient, DataType, Collection
import torch
from PIL import Image
import timm
from sklearn.preprocessing import normalize
from timm.data import resolve_data_config
from timm.data.transforms_factory import create_transform


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

CLUSTER_ENDPOINT = str(sys.argv[1])
client = MilvusClient(uri=CLUSTER_ENDPOINT)
collection_name = str(sys.argv[2])
query_image =  str(sys.argv[3])
client.load_collection(collection_name)
extractor = FeatureExtractor("resnet34")
res = client.search(
    collection_name=collection_name,  # target collection
    data=[extractor(query_image)],  # query vectors
    limit=2,  # number of returned entities
    output_fields=["url"],  # specifies fields to be returned
    consistency_level="Strong" ## NOTE: without defining that, the search might return empty result.
)
print(res)
