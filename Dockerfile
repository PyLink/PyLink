FROM python:3-alpine

WORKDIR /pylink
COPY . /pylink

RUN \
  apk add --no-cache --virtual .fetch-deps linux-headers build-base \
  && pip3 install --no-cache-dir -r requirements.txt \
  && python3 setup.py install \
  && apk del .fetch-deps

WORKDIR /
RUN rm -r pylink
CMD pylink
