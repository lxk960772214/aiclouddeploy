#!/bin/bash 

tar -zxvf packages/uv-x86_64-unknown-linux-gnu.tar.gz -C packages/
mv packages/uv-x86_64-unknown-linux-gnu/uv* /usr/local/bin/
uv venv 
source .venv/bin/activate
export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple
#uv pip install -r requirements.txt
export PYTHONPATH=$(pwd):$PYTHONPATH

#base
python src/main.py --step 0d --step 01 --step 04 --step 07 --step 08 --step 09 --step 12 --step 13 --step 15 --step 16 --step 17 --step 18 --step 19 --step 29 

# #磁盘
# python src/main.py --step 06 --step 34
python src/main.py --step 34

# #网络
# python src/main.py  --step 20

# #时间同步
# python src/main.py --step 30

# #gpu
python src/main.py --step 21 --step 22 --step 24 --step 25 --step 27 --step 28

# #测试
# python src/main.py --step 40 --step 41 --step 42 --step 43 --step 44 --step 45 
python src/main.py --step 41



