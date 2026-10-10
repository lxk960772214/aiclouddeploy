#!/bin/bash

export https_proxy=http://127.0.0.1:7890 http_proxy=http://127.0.0.1:7890 

git add -A
git commit -m "10.10更新"

git pull --rebase origin liuxinke-custom
git push origin liuxinke-custom

