FROM python:3-alpine

COPY . /pylink

RUN \
  apk add --no-cache --virtual .fetch-deps linux-headers build-base \
  && cd /pylink \
  && pip3 install --no-cache-dir -r requirements.txt \
  && python3 setup.py install \
  && cd / \
  && rm -r /pylink \
  && apk del .fetch-deps \
  && adduser -D -H pylink

USER pylink

CMD pylink
