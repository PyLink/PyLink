FROM python:3-alpine

RUN apk add linux-headers build-base

RUN mkdir /pylink
WORKDIR /pylink
COPY . /pylink

RUN pip3 install -r requirements.txt
RUN python3 setup.py install
RUN apk del linux-headers build-base

ENTRYPOINT pylink /pylink-source/pylink.yml
