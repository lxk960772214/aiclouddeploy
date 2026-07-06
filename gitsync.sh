#!/bin/bash

git add -A
git commit -m "7.6更新"

git pull --rebase origin liuxinke-custom
git push origin liuxinke-custom

