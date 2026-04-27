#!/usr/bin/env bash

export SOPS_AGE_KEY_FILE="$HOME/.age/sops/keys.txt"

dir=$(pwd)
if [[ $dir =~ "(.*)(hack)$" ]]; then
  cd ..
fi

function join_by {
  local d=${1-} f=${2-}
  if shift 2; then
    printf %s "$f" "${@/#/$d}"
  fi
}

age_keys=('age1r9chn8pl3d4msxktw457x3xz2l8p04pwuyd7pkgldkmkakras5ks7tfsyq')  # cedi@mae
age_keys+=('age10hzpv26wext204acftvf2n8r6hmnnwxdpkngzaysllpwynccjvjsjvhq4z') # argocd (k8s_cedi_dev_new)
age_keys+=('age1l4lhmkmvr4lype9x4dm3y9lxk2uekqwwj65mp4c36tnph6ytfakqesnats') # GH Codespaces (keys_ghcodespace)
age_keys+=('age15cq50fx3zeeqg5aqh06s6p9zsew3yjlggx3mzchqea6763uup5jsaz9pu3') # cedi@zia

find . -name "*.secret.yaml" | xargs -n1 sops --age $(join_by , "${age_keys[@]}") -e -i
