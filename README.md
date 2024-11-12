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
- set up milvus cluster using [helm](https://milvus.io/docs/install_cluster-helm.md).

# Setting up Bucket and collection for the `python vectordb app ceph`

Assuming the milvus, channel, obc is created in `default` namespace and rook resources in `rook-ceph` namespace. The app will be created in default namespace.

### Setting up channel and subscription

create default channel and subscription referring to the service of the this application. Subscription won't be active until service is up.

```yaml
apiVersion: messaging.knative.dev/v1
kind: InMemoryChannel
metadata:
   name: demo-channel
---
# subscription for the python-ceph-vectordb app which listens notifications from the channel
apiVersion: messaging.knative.dev/v1
kind: Subscription
metadata:
  name: my-subscription
spec:
  channel:
    apiVersion: messaging.knative.dev/v1
    kind: InMemoryChannel
    name: demo-channel
  subscriber:
    ref:
      apiVersion: v1
      kind: Service
      name: python-ceph-vectordb
```

The yaml file is located at knative-resources.yaml

```sh
kubectl create -f knative-resources.yaml
```

### Create Bucket resources

- create topic using the service endpoint of default knative channel, refer it in the uri field (default value will be `http://demo-channel-kn-channel.default.svc.cluster.local`)

```yaml
apiVersion: ceph.rook.io/v1
kind: CephBucketTopic
metadata:
  name: my-topic
spec:
  objectStoreName: my-store
  objectStoreNamespace: rook-ceph
  opaqueData: my@email.com
  persistent: true # to send notification asynchronously so that upload won't impacted
  endpoint:
    http:
      uri: http://demo-channel-kn-channel.default.svc.cluster.local # default channel uri
      disableVerifySSL: true
      sendCloudEvents: true # these are cloud events
```

- create bucket notification referring topic, current checks for put and copy. Ideally the should include delete/rename operations as well for updating entries in the vectordb.

```yaml
apiVersion: ceph.rook.io/v1
kind: CephBucketNotification
metadata:
  name: my-notification
spec:
  topic: my-topic
  events:
    - s3:ObjectCreated:Put
    - s3:ObjectCreated:Copy
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
  -  `TEXT` it uses `SentenceTransformerEmbeddingFunction` which creates vector of dimension `384`.
  -  `IMAGE` it uses `resnet34` which creates vector of dimension `512`.

```yaml

kind: ConfigMap
apiVersion: v1
metadata:
  name: python-ceph-vectordb-text
data:
  MILVUS_ENDPOINT : "http://my-release-milvus.default.svc:19530"
  OBJECT_TYPE     : "TEXT"
  VECTOR_DIMENSION: "384"
```

After creating the configmap, refer above configmap, secrets/configmap of obc in deployment file of the application.

```yaml

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
# Service that exposes python-vector-db-app app.
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
```

This will create the application and service for object type text.

The yaml configuration can be found at `sample-app.yaml`

```sh

kubectl create -f sample-app.yaml
```

### Testing

The `collection name` is based on the `bucket name`, will logged in the application pod. Currently is not exposed properly.
There are sample programs attached in the repo which can be used to search and display the collection index etc.

- to display the content -- `python describe.py <milvus uri> <collection name>`
- to do similar search -- `python search.py <milvus uri> <collection name> <text for searching in the object>`

### [Optional] Installing the milvus cluster using RGW as s3 backend

- create [CephObjectStoreUser](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGW/object-storage/#create-a-user) and create bucket using s3 client

```sh
# export AWS_ACCESS_KEY=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.AccessKey}' | base64 --decode)
# export AWS_SECRET_KEY=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.SecretKey}' | base64 --decode)
# export Endpoint=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.Endpoint}' | base64 --decode)
```

- create milvus via helm

```sh
# helm upgrade --install my-release --set cluster.enabled=true --set etcd.replicaCount=1 --set pulsar.enabled=false --set minio.mode=standalone milvus/milvus --set minio.enabled=false --set externalS3.enabled=true --set externalS3.host=<from Endpoint> --set externalS3.port=<from endpoint> --set externalS3.accessKey=$AWS_ACCESS_KEY --set externalS3.secretKey=$AWS_SECRET_KEY --set externalS3.bucketName=<bucket created by the user>
```
