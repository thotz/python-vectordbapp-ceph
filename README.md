# python-vectordbapp-ceph

This is application which runs creates a vectordb collection based on RGW bucket, containing object url and vector generated based on the object content. And all operations like searching and indexing can be performed directly on the collection without actual storing the data. The app inserts data based on the notification send from RGW.

# Prerequiste

- set up k8s cluster. For development purpose [minikube](https://minikube.sigs.k8s.io/docs/start/?arch=%2Flinux%2Fx86-64%2Fstable%2Fbinary+download) can be used.
- set ceph cluster using [Rook](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGW/object-storage/).
- Create [Object Bucket Claim with notifications](https://rook.io/docs/rook/latest-release/Storage-Configuration/Object-Storage-RGWceph-object-bucket-notifications/) defined on it
- Install [knative eventing](https://knative.dev/docs/install/yaml-install/eventing/install-eventing-with-yaml/#install-knative-eventing)
- set up milvus cluster using [helm](https://milvus.io/docs/install_cluster-helm.md).

# Installing the app

```sh
kubectl create -f knative-resource.yaml sample-app.yaml
```

# Testing

- create object using s3 client and check logs in the app side
- sample search program `search.py` can be found in this repo.
