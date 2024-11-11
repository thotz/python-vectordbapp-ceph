# python-vectordbapp-ceph

This is application which runs creates a vectordb collection based on RGW bucket, containing object url and vector generated based on the object content. And all operations like searching and indexing can be performed directly on the collection without actual storing the data. The app inserts data based on the notification send from RGW.

# Prerequiste

- set up k8s cluster. For development purpose [minikube](https://minikube.sigs.k8s.io/docs/start/?arch=%2Flinux%2Fx86-64%2Fstable%2Fbinary+download) can be used.
- set ceph cluster using [Rook](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGW/object-storage/).
- Create [Object Bucket Claim with notifications](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGWceph-object-bucket-notifications/) defined on it
- Install [knative eventing](https://knative.dev/docs/install/yaml-install/eventing/install-eventing-with-yaml/#install-knative-eventing)
- Create [default channel](https://knative.dev/docs/install/yaml-install/eventing/install-eventing-with-yaml/#optional-install-a-default-channel-messaging-layer) for receiving bucket notification on the bucket.
- set up milvus cluster using [helm](https://milvus.io/docs/install_cluster-helm.md).

# Installing the milvus cluster using RGW as s3 store(optional)

- create [CephObjectStoreUser](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGW/object-storage/#create-a-user) and create bucket using s3 client.

```sh
# export AWS_ACCESS_KEY=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.AccessKey}' | base64 --decode)
# export AWS_SECRET_KEY=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.SecretKey}' | base64 --decode)
# export Endpoint=$(kubectl -n rook-ceph get secret rook-ceph-object-user-my-store-milvus-user -o jsonpath='{.data.Endpoint}' | base64 --decode)
```

- create milvus via helm
```sh
# helm upgrade --install my-release --set cluster.enabled=true --set etcd.replicaCount=1 --set pulsar.enabled=false --set minio.mode=standalone milvus/milvus --set minio.enabled=false --set externalS3.enabled=true --set externalS3.host=<from Endpoint> --set externalS3.port=<from endpoint> --set externalS3.accessKey=$AWS_ACCESS_KEY --set externalS3.secretKey=$AWS_SECRET_KEY --set externalS3.bucketName=<bucket created by the user>
```

# Installing the app

Create after modify the crds in the repo accordingly :
```sh
kubectl create -f knative-resource.yaml rook-resource.yaml sample-app.yaml
```

# Testing
- collection name is based on bucket name and can be found in logs
- create object using s3 client and check logs in the app side
- sample search program `search.py` and `describe.py` can be found in this repo.
