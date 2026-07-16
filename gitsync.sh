#!/bin/bash

git add -A
git commit -m "7.16更新"

git pull --rebase origin liuxinke-custom
git push origin liuxinke-custom

