#!/bin/bash

files=(
  kustomization.yaml
  cluster-role-binding.yaml
  cluster-role.yaml
  role-binding.yaml
  role.yaml
  service-account.yaml
  service.yaml
  statefulset.yaml
)

for file in "${files[@]}"
do
  rm $file
  wget https://raw.githubusercontent.com/kubernetes/kube-state-metrics/master/examples/autosharding/$file
done