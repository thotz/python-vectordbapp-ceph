# python-vectordbapp-ceph

This application creates vector storage based on RGW buckets using the S3 Vectors API (boto3 s3vectors client). It stores object URLs and vectors generated from object content. The app processes data based on notifications sent from RGW and uses RGW's native S3 vector support for storage, indexing, and searching.

## Key Features
- Uses boto3 `s3vectors` client for vector operations
- Vector bucket naming: `<bucket-name>-vectors` (preserves hyphens)
- Automatic vector bucket creation and index configuration
- Supports TEXT (dimension 384) and IMAGE (dimension 512) embeddings
- Uses S3 Vectors API: `create_bucket`, `create_index`, `put_vectors`, `search_vectors`, `delete_vectors`

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

# Setting up Bucket and vector storage for the `python vectordb app ceph`

Assuming the channel and obc are created in `default` namespace and rook resources in `rook-ceph` namespace. The app will be created in default namespace. The application now uses RGW's native S3 vector support instead of Milvus.

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

A configmap is needed for the application which refers to the following:

- `OBJECT_TYPE` : The type of object which bucket holds, currently supports `TEXT` and `IMAGE`.
- `VECTOR_DIMENSION` : The dimension of vector created by the embedding function. Currently supports two different embedding functions:
  - `TEXT` uses `SentenceTransformer` (all-MiniLM-L6-v2) which creates vectors of dimension `384`.
  - `IMAGE` uses `resnet34` which creates vectors of dimension `512`.

```yaml

kind: ConfigMap
apiVersion: v1
metadata:
  name: python-ceph-vectordb-text
data:
  OBJECT_TYPE     : "TEXT"
  VECTOR_DIMENSION: "384"

---

kind: ConfigMap
apiVersion: v1
metadata:
  name: python-ceph-vectordb-image
data:
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

The vector bucket name is automatically derived from the bucket name (appending '-vectors'). You can check the logs to see the vector bucket being created:

```sh
kubectl logs <pod name for python application> | grep "vector bucket"
```

### Searching Vectors

**Important:** Vector search operations require credentials from the CephObjectStoreUser (vector-user), not the OBC credentials.

To search for text objects, use the following command:

```sh
python search.py <endpoint_url> <vector_access_key> <vector_secret_key> <bucket_name> <search_text>
```

Example:
```sh
export AWS_URL=$(minikube service --url rook-ceph-rgw-my-store-external -n rook-ceph)
export VECTOR_ACCESS_KEY=$(kubectl get secret rook-ceph-object-user-my-store-vector-user -n rook-ceph -o jsonpath='{.data.AccessKey}' | base64 --decode)
export VECTOR_SECRET_KEY=$(kubectl get secret rook-ceph-object-user-my-store-vector-user -n rook-ceph -o jsonpath='{.data.SecretKey}' | base64 --decode)
export BUCKET_NAME=$(kubectl get obc ceph-notification-bucket-text -o jsonpath='{.spec.bucketName}')

python search.py "$AWS_URL" "$VECTOR_ACCESS_KEY" "$VECTOR_SECRET_KEY" "$BUCKET_NAME" "your search text"
```

For image searching:

```sh
python search_image.py <endpoint_url> <vector_access_key> <vector_secret_key> <bucket_name> <path_to_image>
```

Example:
```sh
export AWS_URL=$(minikube service --url rook-ceph-rgw-my-store-external -n rook-ceph)
export VECTOR_ACCESS_KEY=$(kubectl get secret rook-ceph-object-user-my-store-vector-user -n rook-ceph -o jsonpath='{.data.AccessKey}' | base64 --decode)
export VECTOR_SECRET_KEY=$(kubectl get secret rook-ceph-object-user-my-store-vector-user -n rook-ceph -o jsonpath='{.data.SecretKey}' | base64 --decode)
export BUCKET_NAME=$(kubectl get obc ceph-notification-bucket-image -o jsonpath='{.spec.bucketName}')

python search_image.py "$AWS_URL" "$VECTOR_ACCESS_KEY" "$VECTOR_SECRET_KEY" "$BUCKET_NAME" "/path/to/query/image.jpg"
```

The search scripts will return the top 2 most similar objects based on L2 distance.