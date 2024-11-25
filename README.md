# python-vectordbapp-ceph

This is application which runs creates a vectordb collection based on RGW bucket, containing object url and vector generated based on the object content. And all operations like searching and indexing can be performed directly on the collection without actual storing the data. The app inserts data based on the notification send from RGW. Here we are using milvus as vectordb app, can be extended to other vectordbs as well

# Prerequisites

- set up k8s cluster. For development purpose [minikube](https://minikube.sigs.k8s.io/docs/start/?arch=%2Flinux%2Fx86-64%2Fstable%2Fbinary+download) can be used. Ceph needs an extra disk to work. So in case of minukube and kvm2 hyperviser, use:

```sh
minikube start --extra-disks=1
```

- set ceph cluster using [Rook](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGW/object-storage/).

```sh
kubectl apply -f https://raw.githubusercontent.com/rook/rook/refs/heads/master/deploy/examples/crds.yaml
kubectl apply -f https://raw.githubusercontent.com/rook/rook/refs/heads/master/deploy/examples/common.yaml
kubectl apply -f https://raw.githubusercontent.com/rook/rook/refs/heads/master/deploy/examples/operator.yaml
kubectl apply -f https://raw.githubusercontent.com/rook/rook/refs/heads/master/deploy/examples/cluster-test.yaml
kubectl apply -f https://raw.githubusercontent.com/rook/rook/refs/heads/master/deploy/examples/object-test.yaml
```

- Install [knative eventing](https://knative.dev/docs/install/yaml-install/eventing/install-eventing-with-yaml/#install-knative-eventing). Make sure to install the InMemory channel implementation.

```sh
kubectl apply -f https://github.com/knative/eventing/releases/download/knative-v1.16.0/eventing-crds.yaml
kubectl apply -f https://github.com/knative/eventing/releases/download/knative-v1.16.0/eventing-core.yaml
kubectl apply -f https://github.com/knative/eventing/releases/download/knative-v1.16.0/in-memory-channel.yaml
```

- set up milvus cluster using [helm](https://milvus.io/docs/install_cluster-helm.md).

# Setting up Bucket and collection for the `python vectordb app ceph`

Assuming the milvus, channel, obc is created in `default` namespace and rook resources in `rook-ceph` namespace. The app will be created in default namespace.

### Setting up channel and subscription

create channel and subscription for text/image referring to the service of the those applications. Subscription won't be active until service is up.

```yaml
# channel for rgw send notifications
apiVersion: messaging.knative.dev/v1
kind: InMemoryChannel
metadata:
   name: text-channel
---
apiVersion: messaging.knative.dev/v1
kind: InMemoryChannel
metadata:
   name: image-channel
---
# subscription for the python-ceph-vectordb app which listens notifications from the channel
apiVersion: messaging.knative.dev/v1
kind: Subscription
metadata:
  name: text-subscription
spec:
  channel:
    apiVersion: messaging.knative.dev/v1
    kind: InMemoryChannel
    name: text-channel
  subscriber:
    ref:
      apiVersion: v1
      kind: Service
      name: python-ceph-vectordb-text
---
# subscription for the python-ceph-vectordb app which listens notifications from the channel
apiVersion: messaging.knative.dev/v1
kind: Subscription
metadata:
  name: image-subscription
spec:
  channel:
    apiVersion: messaging.knative.dev/v1
    kind: InMemoryChannel
    name: image-channel
  subscriber:
    ref:
      apiVersion: v1
      kind: Service
      name: python-ceph-vectordb-image
```

The yaml file is located at knative-resources.yaml

```sh
kubectl create -f knative-resources.yaml
```

### Create Bucket resources

- create topic for text/image using the service endpoint of corresponding knative channel, refer it in the uri field 

```yaml
# topic for created for bucket notification
apiVersion: ceph.rook.io/v1
kind: CephBucketTopic
metadata:
  name: kn-text-topic
spec:
  objectStoreName: my-store
  objectStoreNamespace: rook-ceph
  opaqueData: my@email.com
  persistent: true
  endpoint:
    http:
      uri: http://text-channel-kn-channel.default.svc.cluster.local # default channel uri
      disableVerifySSL: true
      sendCloudEvents: true
---
# topic for created for bucket notification
apiVersion: ceph.rook.io/v1
kind: CephBucketTopic
metadata:
  name: kn-image-topic
spec:
  objectStoreName: my-store
  objectStoreNamespace: rook-ceph
  opaqueData: my@email.com
  persistent: true
  endpoint:
    http:
      uri: http://image-channel-kn-channel.default.svc.cluster.local # default channel uri
      disableVerifySSL: true
      sendCloudEvents: true
---
```

- create bucket notification for text/image referring topic, current checks for put and copy. Ideally the should include delete/rename operations as well for updating entries in the vectordb.

```yaml
# bucket notifications defined for event such as put and copy object
apiVersion: ceph.rook.io/v1
kind: CephBucketNotification
metadata:
  name: text-notification
spec:
  topic: kn-text-topic
  events:
    - s3:ObjectCreated:Put
    - s3:ObjectCreated:Copy
---
apiVersion: ceph.rook.io/v1
kind: CephBucketNotification
metadata:
  name: image-notification
spec:
  topic: kn-image-topic
  events:
    - s3:ObjectCreated:Put
    - s3:ObjectCreated:Copy
---

```

- create storage class and obc with notification reference for the application to monitor and create vector db entries in milvus
To make it more readable just append type of the object to the obc name. Below are two samples of obcs, one for text and other for image belongs to same storageclass

```yaml

apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: rook-ceph-delete-bucket
provisioner: rook-ceph.ceph.rook.io/bucket # driver:namespace:cluster
reclaimPolicy: Delete
parameters:
  objectStoreName: my-store
  objectStoreNamespace: rook-ceph # namespace:cluster
---

apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: ceph-notification-bucket-text
  labels:
    bucket-notification-my-notification: my-notification # reference for notification
spec:
  generateBucketName: ceph-bkt
  storageClassName: rook-ceph-delete-bucket
---
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: ceph-notification-bucket-image
  labels:
    bucket-notification-my-notification: my-notification # reference for notification
spec:
  generateBucketName: ceph-bkt
  storageClassName: rook-ceph-delete-bucket
```

Both obcs will be created with configmap and secrets referring to details access the bucket will be consumed the application
In the repo these resources can be found in `rook-resources.yaml` and can be create using :

```sh
kubectl create -f rook-resources.yaml
```

### Create python vector db app

The application can handle only bucket atm. For multiple buckets current requires different application with different configuration

A configmap is need for the application which refers following :

- `MILVUS_ENDPOINT` : The service endpoint or uri where milvus is running.
- `OBJECT_TYPE` : The type of object which bucket holds, current support `TEXT` and `IMAGE`.
- `VECTOR_DIMENSION` : The dimension of vector created by the embedded function. In the current have two different embedding function:
  - `TEXT` it uses `SentenceTransformerEmbeddingFunction` which creates vector of dimension `384`.
  - `IMAGE` it uses `resnet34` which creates vector of dimension `512`.

```yaml

kind: ConfigMap
apiVersion: v1
metadata:
  name: python-ceph-vectordb-text
data:
  MILVUS_ENDPOINT : "http://my-release-milvus.default.svc:19530"
  OBJECT_TYPE     : "TEXT"
  VECTOR_DIMENSION: "384"

---

kind: ConfigMap
apiVersion: v1
metadata:
  name: python-ceph-vectordb-image
data:
  MILVUS_ENDPOINT : "http://my-release-milvus.default.svc:19530"
  OBJECT_TYPE     : "IMAGE"
  VECTOR_DIMENSION: "512"

```

After creating the configmap, refer above configmap, secrets/configmap of obc in deployment file of the application.

```yaml
# python vector db app deployment for text
apiVersion: apps/v1
kind: Deployment
metadata:
  name: python-ceph-vectordb
spec:
  replicas: 1
  selector:
    matchLabels: &labels
      app: python-ceph-vectordb
  template:
    metadata:
      labels: *labels
    spec:
      containers:
        - name: python-ceph-vectordb-text
          image: quay.io/jthottan/pythonwebserver:python-vectordb-ceph
          envFrom:
          - configMapRef:
              name: ceph-notification-bucket-text # configmap created with obc `ceph-notification-bucket-text`
          - secretRef:
              name: ceph-notification-bucket-text # secret created wth obc `ceph-notification-bucket-text`
          - configMapRef:
              name: python-ceph-vectordb-text

---
# Service that exposes python-vector-db app for text.
# This will be the subscriber for the Trigger
kind: Service
apiVersion: v1
metadata:
  name: python-ceph-vectordb-text
spec:
  selector:
    app: python-ceph-vectordb-text
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080
---

# python vector db app deployment for image
apiVersion: apps/v1
kind: Deployment
metadata:
  name: python-ceph-vectordb-image
spec:
  replicas: 1
  selector:
    matchLabels: &labels
      app: python-ceph-vectordb-image
  template:
    metadata:
      labels: *labels
    spec:
      containers:
        - name: python-ceph-vectordb-image
          image: quay.io/jthottan/pythonwebserver:python-vectordb-ceph
          envFrom:
          - configMapRef:
              name: ceph-notification-bucket-image
          - secretRef:
              name: ceph-notification-bucket-image
          - configMapRef:
              name: python-ceph-vectordb-image
---
# Service that exposes python-vector-db app for text.
# This will be the subscriber for the Trigger
kind: Service
apiVersion: v1
metadata:
  name: python-ceph-vectordb-image
spec:
  selector:
    app: python-ceph-vectordb-image
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8080

```

This will create the application and service for object type text/image.

The yaml configuration can be found:

```sh
kubectl create -f sample-deployment-text.yaml # for text
kubectl create -f sample-deployment-image.yaml # for image
```

### Testing

Make sure that there is access from the outside to the object store.
Create an external service:

```sh
cat << EOF | kubectl apply -f -
apiVersion: v1
kind: Service
metadata:
  name: rook-ceph-rgw-my-store-external
  namespace: rook-ceph
  labels:
    app: rook-ceph-rgw
    rook_cluster: rook-ceph
    rook_object_store: my-store
spec:
  ports:
  - name: rgw
    port: 80
    protocol: TCP
    targetPort: 8080
  selector:
    app: rook-ceph-rgw
    rook_cluster: rook-ceph
    rook_object_store: my-store
  sessionAffinity: None
  type: NodePort
EOF
```

Get the URL from minikube:

```sh
export AWS_URL=$(minikube service --url rook-ceph-rgw-my-store-external -n rook-ceph)
```

To upload radosgw documentation to the text bucket, use:

```sh
export AWS_ACCESS_KEY_ID=$(kubectl get secret ceph-notification-bucket-text -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' |  base64 --decode)
export AWS_SECRET_ACCESS_KEY=$(kubectl get secret ceph-notification-bucket-text -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' |  base64 --decode)
export BUCKET_NAME=$(kubectl get obc ceph-notification-bucket-text -o jsonpath='{.spec.bucketName}')

aws --endpoint-url "$AWS_URL" s3 sync <path to local docs> s3://"$BUCKET_NAME"
```

Expose the milvus service via executing following command from different terminal make sure 27017 port is available:

```sh
kubectl port-forward --address 0.0.0.0 service/my-release-milvus 27017:19530
```

This port forward milvus port locally to the host

Now milvus uri can accessed via http://localhost:27017

The collection name can be found by grepping "collection name from the bucket:" in kubectl logs.

```sh
kubectl logs <pod name for python application> | grep "collection name from the bucket"
```

following is the python program to search text and requires input as "milvus uri" "collection name" "text to search"

```py

import milvus_model
import sys, getopt
from pymilvus import MilvusClient, DataType, Collection

CLUSTER_ENDPOINT=str(sys.argv[1])
client = MilvusClient(uri=CLUSTER_ENDPOINT)
collection_name=str(sys.argv[2])
client.load_collection(collection_name)

embedding_fn = milvus_model.dense.SentenceTransformerEmbeddingFunction(model_name='all-MiniLM-L6-v2',device='cpu')
query_vectors = embedding_fn.encode_queries([str(sys.argv[3])])

res = client.search(
    collection_name=collection_name,  # target collection
    data=query_vectors,  # query vectors
    limit=2,  # number of returned entities
    output_fields=["url"],  # specifies fields to be returned
    consistency_level="Strong" ## NOTE: without defining that, the search might return empty result.
)
print(res)
```

```sh
python search.py  http://localhost:27017 <collection name> <search text>
```

Similarly for image searching can be done with help following python script:

```py
import sys, getopt
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
```

```sh
python search.py  http://localhost:27017 <collection name> <path to image>
```

This requires python 3.12 atleast, if you don't have it please use below container images:

```sh
# for text
docker pull quay.io/jthottan/pythonwebserver:python-vectordb-search-text

docker run --rm <image id> search.py  http://localhost:27017 <collection name> <search text> --add-host=host.docker.internal:host-gateway

```

```sh
# for image

docker pull quay.io/jthottan/pythonwebserver:python-vectordb-search-image

docker run --rm <image id> <collection name> <path to file> --add-host=host.docker.internal:host-gateway -v <path to directory for the input file>:/mnt/<directory name>

```

### [Optional] Installing the milvus cluster using RGW as s3 backend

- create [CephObjectStoreUser](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGW/object-storage/#create-a-user) and create bucket using s3 client

```sh
# export AWS_ACCESS_KEY=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.AccessKey}' | base64 --decode)
# export AWS_SECRET_KEY=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.SecretKey}' | base64 --decode)
# export Endpoint=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.Endpoint}' | base64 --decode)
```

- create milvus via helm

```sh
# helm upgrade --install my-release --set cluster.enabled=true --set etcd.replicaCount=1 --set pulsar.enabled=false --set minio.mode=standalone milvus/milvus --set minio.enabled=false --set externalS3.enabled=true --set externalS3.host=$ENDPOINT --set externalS3.port=<from endpoint> --set externalS3.accessKey=$AWS_ACCESS_KEY --set externalS3.secretKey=$AWS_SECRET_KEY --set externalS3.bucketName=<bucket created by the user>
```
