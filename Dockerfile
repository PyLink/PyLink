FROM python:3-alpine

COPY . /pylink

RUN \
  cd /pylink \
  && pip3 install --no-cache-dir -r requirements.txt \
  && python3 setup.py install \
  && rm -r /pylink

CMD pylink
